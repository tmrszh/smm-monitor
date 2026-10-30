"""Встраивание автоподсчёта в готовую таблицу заказчика.

У таблицы «имиджевая работа» свои колонки и своя система баллов. Ломать её
нельзя, поэтому мы ничего не пересчитываем сами: добавляем в книгу лист
«Ссылки» и подставляем в колонки «кол-во» формулы, которые считают строки с
этого листа. Баллы, общий балл и место остаются такими, как их задал заказчик.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .excel_report import (
    COL_COMMENTS,
    COL_LINK,
    COL_REGION,
    COL_VIEWS,
    HEADER_FILL,
    HEADER_FONT,
    LINK_COLUMNS,
    LINKS_SHEET,
    MAX_ROWS,
)
from .regions import RegionBook

# какие слова в шапке означают какую метрику
METRICS = {
    "репост": "links",
    "публикац": "links",
    "просмотр": "views",
    "комментар": "comments",
}


@dataclass
class AttachResult:
    sheet: str
    first_row: int
    last_row: int
    already_prepared: bool = False
    columns: dict[str, str] = field(default_factory=dict)  # метрика -> буква колонки
    regions: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # метрики, которых нет в таблице


def _metric_of(text: str) -> str | None:
    lowered = re.sub(r"\s+", " ", str(text or "")).lower()
    for word, metric in METRICS.items():
        if word in lowered:
            return metric
    return None


def _find_metric_columns(sheet) -> dict[str, int]:
    """Колонки «кол-во» под заголовками «Репосты», «Просмотры», «Комментарии»."""
    found: dict[str, int] = {}
    for row in range(1, min(sheet.max_row, 15) + 1):
        for column in range(1, sheet.max_column + 1):
            value = sheet.cell(row=row, column=column).value
            if not isinstance(value, str) or "кол-во" not in value.lower():
                continue
            # заголовок метрики стоит выше: либо прямо над ячейкой, либо левее в объединении
            for header_row in range(row - 1, 0, -1):
                metric = None
                for shift in (0, -1, -2):
                    if column + shift < 1:
                        continue
                    metric = _metric_of(sheet.cell(row=header_row, column=column + shift).value)
                    if metric:
                        break
                if metric:
                    found.setdefault(metric, column)
                    break
    return found


def _rank_column(sheet, first_row: int, last_row: int) -> tuple[str, int] | None:
    """Колонка «МЕСТО» и колонка общего балла, по которому его считать."""
    total_column = place_column = None
    for row in range(1, min(sheet.max_row, 15) + 1):
        for column in range(1, sheet.max_column + 1):
            value = sheet.cell(row=row, column=column).value
            if not isinstance(value, str):
                continue
            lowered = re.sub(r"\s+", " ", value).lower()
            if "общий балл" in lowered:
                total_column = column
            elif lowered.strip() == "место":
                place_column = column
    if total_column and place_column:
        return get_column_letter(total_column), place_column
    return None


def _find_region_rows(sheet, region_book: RegionBook) -> tuple[int, int, int, list[str]]:
    """Колонка с названиями регионов и диапазон строк с ними."""
    names = {name.strip().lower() for name in region_book.names}
    best: tuple[int, list[int], list[str]] | None = None

    for column in range(1, min(sheet.max_column, 8) + 1):
        rows: list[int] = []
        titles: list[str] = []
        for row in range(1, sheet.max_row + 1):
            value = sheet.cell(row=row, column=column).value
            if isinstance(value, str) and value.strip().lower() in names:
                rows.append(row)
                titles.append(value.strip())
        if rows and (best is None or len(rows) > len(best[1])):
            best = (column, rows, titles)

    if best is None:
        raise ValueError(
            "В таблице не нашлось колонки с названиями регионов. "
            "Проверьте, что они написаны так же, как в справочнике."
        )
    column, rows, titles = best
    return column, rows[0], rows[-1], titles


def _add_links_sheet(workbook, region_column_letter: str, first: int, last: int, source: str):
    """Лист, куда вставляют ссылки. Регионы в выпадающем списке — из самой таблицы."""
    if LINKS_SHEET in workbook.sheetnames:
        return workbook[LINKS_SHEET]

    sheet = workbook.create_sheet(LINKS_SHEET, 0)
    for index, (title, width) in enumerate(LINK_COLUMNS, start=1):
        cell = sheet.cell(row=1, column=index, value=title)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"

    formula = f"='{source}'!${region_column_letter}${first}:${region_column_letter}${last}"
    validation = DataValidation(type="list", formula1=formula, allow_blank=True, showDropDown=False)
    validation.error = "Выберите регион из таблицы"
    validation.errorTitle = "Регион не из списка"
    sheet.add_data_validation(validation)
    validation.add(f"{COL_REGION}2:{COL_REGION}{MAX_ROWS + 1}")

    hint = sheet.cell(
        row=MAX_ROWS + 3,
        column=1,
        value=(
            "Вставьте сюда ссылки на публикации в колонку «Ссылка», по одной в строку. "
            "Остальные колонки заполнит программа: запустите её и выберите пункт 2."
        ),
    )
    hint.alignment = Alignment(wrap_text=True, vertical="top")
    hint.font = Font(italic=True)
    return sheet


def attach_counting(
    path: str | Path,
    region_book: RegionBook,
    out_path: str | Path | None = None,
) -> tuple[Path, AttachResult]:
    """Добавить в книгу лист «Ссылки» и формулы автоподсчёта в колонки «кол-во»."""
    path = Path(path)
    workbook = load_workbook(path)

    # лист со ссылками пропускаем: таблица с регионами — любой другой
    sheet = None
    found = None
    for name in workbook.sheetnames:
        if name == LINKS_SHEET:
            continue
        try:
            found = _find_region_rows(workbook[name], region_book)
        except ValueError:
            continue
        sheet = workbook[name]
        break
    if sheet is None or found is None:
        raise ValueError(
            "В таблице не нашлось колонки с названиями регионов. "
            "Проверьте, что они написаны так же, как в справочнике."
        )

    region_column, first_row, last_row, titles = found
    metric_columns = _find_metric_columns(sheet)
    if not metric_columns:
        raise ValueError(
            "В шапке таблицы не нашлось колонок «кол-во» под «Репосты», "
            "«Просмотры» или «Комментарии»."
        )

    already_prepared = LINKS_SHEET in workbook.sheetnames
    region_letter = get_column_letter(region_column)
    _add_links_sheet(workbook, region_letter, first_row, last_row, sheet.title)

    links = f"'{LINKS_SHEET}'"
    region_range = f"{links}!${COL_REGION}$2:${COL_REGION}${MAX_ROWS + 1}"
    result = AttachResult(
        sheet=sheet.title,
        already_prepared=already_prepared,
        first_row=first_row,
        last_row=last_row,
    )

    for row in range(first_row, last_row + 1):
        key = f'"*"&${region_letter}{row}&"*"'
        for metric, column in metric_columns.items():
            if metric == "links":
                formula = f"=COUNTIF({region_range},{key})"
            else:
                values = COL_VIEWS if metric == "views" else COL_COMMENTS
                value_range = f"{links}!${values}$2:${values}${MAX_ROWS + 1}"
                formula = f"=SUMIF({region_range},{key},{value_range})"
            sheet.cell(row=row, column=column, value=formula)

    place = _rank_column(sheet, first_row, last_row)
    if place:
        total_letter, place_column = place
        for row in range(first_row, last_row + 1):
            sheet.cell(
                row=row,
                column=place_column,
                value=f"=RANK(${total_letter}{row},${total_letter}${first_row}:${total_letter}${last_row})",
            )
        result.columns["place"] = get_column_letter(place_column)

    result.columns.update({m: get_column_letter(c) for m, c in metric_columns.items()})
    result.regions = titles
    result.missing = [m for m in ("links", "views", "comments") if m not in metric_columns]

    if out_path is None:
        # повторная настройка уже готовой таблицы не плодит копии
        out_path = path if already_prepared else path.with_name(
            f"{path.stem} (автоподсчёт){path.suffix}"
        )
    out_path = Path(out_path)
    workbook.save(out_path)
    return out_path, result
