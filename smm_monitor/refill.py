"""Дозаполнение готового файла: по вставленным вручную ссылкам подтянуть метрики.

Человек вставляет ссылки в колонку «Ссылка» на листе «Ссылки» и запускает сбор.
Пустые ячейки строки заполняются, уже заполненные руками не трогаются
(кроме режима обновления, когда цифры перезаписываются свежими).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

from .collectors.single import fetch_post, platform_of
from .excel_report import LINKS_SHEET
from .regions import RegionBook

COL_NUMBER, COL_PLATFORM, COL_LINK, COL_DATE = 1, 2, 3, 4
COL_REGION, COL_DESCRIPTION, COL_VIEWS, COL_COMMENTS, COL_SOURCE = 5, 6, 7, 8, 9


def is_own_page(url: str, own_pages: list[str] | None) -> bool:
    """Ссылка ведёт на страницу самого ведомства?"""
    if not own_pages:
        return True
    lowered = url.lower()
    return any(page.lower().strip("/ ") in lowered for page in own_pages)


def normalize_region(value: str, region_book: RegionBook) -> str | None:
    """Привести то, что человек вписал в «Регион», к названию из таблицы.

    «Алматы» -> «г. Алматы», «Улытау» -> «Ұлытау», «Семей» -> «Абай».
    None — если хотя бы одну часть не удалось узнать однозначно.
    """
    names = {name.lower(): name for name in region_book.names}
    resolved: list[str] = []
    for part in re.split(r"[;,]", value):
        part = part.strip()
        if not part:
            continue
        if part.lower() in names:
            resolved.append(names[part.lower()])
            continue
        found = region_book.detect(part)
        if len(found) != 1:
            return None
        resolved.append(found[0])
    return "; ".join(dict.fromkeys(resolved)) or None


def _misplaced_link(sheet, row: int) -> str | None:
    """Ссылку вставили в соседнюю колонку — переносим в «Ссылка»."""
    from openpyxl.utils import get_column_letter

    for column in range(1, COL_SOURCE):
        if column == COL_LINK:
            continue
        cell = sheet.cell(row=row, column=column)
        value = str(cell.value or "").strip()
        if value.startswith("http") and " " not in value:
            sheet.cell(row=row, column=COL_LINK).value = value
            cell.value = None
            return get_column_letter(column)
    return None


def _region_from_page(url: str, region_book: RegionBook) -> str | None:
    """Регион новости по заголовку и описанию страницы, если его не проставили."""
    try:
        import requests
        from bs4 import BeautifulSoup

        from .collectors.telegram_web import HEADERS

        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        parts = [soup.title.get_text(" ", strip=True) if soup.title else ""]
        for name in ("og:title", "og:description", "description"):
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                parts.append(tag["content"])
        found = region_book.detect(" ".join(parts))
        return "; ".join(found) if found else None
    except Exception:
        return None


def link_key(url: str) -> str:
    """Один и тот же пост под разными ссылками: /p/ и /reel/, хвосты ?utm=..."""
    match = re.search(r"instagram\.com/(?:p|reel|tv)/([\w\-]+)", url)
    if match:
        return f"instagram:{match.group(1)}"
    match = re.search(r"t\.me/(?:s/)?([\w]+)/(\d+)", url)
    if match:
        return f"telegram:{match.group(1).lower()}/{match.group(2)}"
    return url.split("?")[0].rstrip("/").lower()


@dataclass
class RefillResult:
    filled: int = 0
    updated: int = 0
    skipped: int = 0
    foreign: int = 0  # ссылки на чужие ресурсы: считаются как публикации, без метрик
    cleared: int = 0  # строки, где чужие метрики пришлось убрать
    failed: list[str] = field(default_factory=list)
    renamed: list[str] = field(default_factory=list)  # «Алматы» -> «г. Алматы»
    unknown_regions: list[str] = field(default_factory=list)  # не узнали, что вписано
    duplicates: list[str] = field(default_factory=list)  # одна публикация в нескольких строках
    no_region: list[str] = field(default_factory=list)  # без региона строка никуда не идёт
    moved: list[str] = field(default_factory=list)  # ссылку вставили не в ту колонку


class FileLockedError(RuntimeError):
    """Файл открыт в Excel, и сохранить его нельзя."""


def is_open_in_excel(path: Path) -> bool:
    """Excel, открывая книгу, кладёт рядом скрытый файл «~$имя.xlsx»."""
    return (path.parent / f"~${path.name}").exists()


def save_workbook(workbook, path: Path, on_locked=None) -> None:
    """Сохранить; если файл занят — дать человеку закрыть его и попробовать снова."""
    while True:
        try:
            workbook.save(path)
            return
        except PermissionError as error:
            if on_locked is None or not on_locked(path):
                raise FileLockedError(
                    f"Файл «{path.name}» открыт в Excel, закройте его и запустите снова"
                ) from error


def refill_workbook(
    path: str | Path,
    region_book: RegionBook,
    refresh: bool = False,
    progress=None,
    own_pages: list[str] | None = None,
    on_locked=None,
) -> RefillResult:
    path = Path(path)
    workbook = load_workbook(path)
    if LINKS_SHEET not in workbook.sheetnames:
        raise ValueError(f"В файле нет листа «{LINKS_SHEET}»")
    sheet = workbook[LINKS_SHEET]

    # в таблицах, сделанных раньше, колонки «Страница» ещё нет
    if not sheet.cell(row=1, column=COL_SOURCE).value:
        from openpyxl.styles import Alignment

        from .excel_report import HEADER_FILL, HEADER_FONT

        header = sheet.cell(row=1, column=COL_SOURCE, value="Страница")
        header.fill = HEADER_FILL
        header.font = HEADER_FONT
        header.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.column_dimensions["I"].width = 30

    result = RefillResult()
    seen: dict[str, list[int]] = {}

    for row in range(2, sheet.max_row + 1):
        link_cell = sheet.cell(row=row, column=COL_LINK)
        if not link_cell.value:
            moved_from = _misplaced_link(sheet, row)
            if moved_from:
                result.moved.append(f"строка {row}: из колонки {moved_from} в «Ссылка»")
        link = link_cell.value
        if not link or not str(link).strip().startswith("http"):
            continue
        link = str(link).strip()
        if link_cell.value != link:
            link_cell.value = link  # лишний пробел в начале ссылки

        seen.setdefault(link_key(link), []).append(row)

        # Таблица считает регион по точному названию: «Алматы» вместо
        # «г. Алматы» она не увидит, поэтому приводим к нужному виду.
        region_cell = sheet.cell(row=row, column=COL_REGION)
        typed = str(region_cell.value).strip() if region_cell.value else ""
        if typed and typed not in region_book.names:
            fixed = normalize_region(typed, region_book)
            if fixed and fixed != typed:
                region_cell.value = fixed
                result.renamed.append(f"строка {row}: «{typed}» → «{fixed}»")
            elif not fixed:
                result.unknown_regions.append(f"строка {row}: «{typed}»")

        has_numbers = any(
            sheet.cell(row=row, column=column).value is not None
            for column in (COL_VIEWS, COL_COMMENTS)
        )
        known_source = sheet.cell(row=row, column=COL_SOURCE).value

        # Правило простое: метрики только со своих страниц. Если по строке уже
        # известно, чья это публикация, в сеть не ходим.
        if known_source:
            if not is_own_page(str(known_source), own_pages):
                if has_numbers:
                    for column in (COL_VIEWS, COL_COMMENTS):
                        sheet.cell(row=row, column=column).value = None
                    result.cleared += 1
                result.foreign += 1
                continue
            if has_numbers and not refresh:
                result.skipped += 1
                continue
        elif has_numbers and not refresh and is_own_page(link, own_pages):
            result.skipped += 1
            continue

        # Новостной сайт, а не телеграм или инстаграм — это репост: считаем
        # его по региону, а метрик у него нет и не нужно.
        if platform_of(link) is None:
            if not region_cell.value:
                if progress:
                    progress(link)
                found = _region_from_page(link, region_book)
                if found:
                    region_cell.value = found
            result.foreign += 1
            continue

        if progress:
            progress(link)
        try:
            post = fetch_post(link)
        except Exception as error:
            result.failed.append(f"{link} — {error}")
            continue
        if post is None:
            result.failed.append(f"{link} — ссылка не распознана")
            continue

        def put(column: int, value, overwrite: bool = False) -> None:
            cell = sheet.cell(row=row, column=column)
            if value is not None and (overwrite or cell.value in (None, "")):
                cell.value = value

        put(COL_NUMBER, row - 1)
        put(COL_PLATFORM, post.platform.capitalize())
        put(COL_DATE, (post.posted_at or "")[:19].replace("T", " ") or None)
        put(COL_DESCRIPTION, post.description or None)
        put(COL_REGION, "; ".join(region_book.detect(post.description)) or None)

        # В ссылке на пост инстаграма имени аккаунта нет, поэтому смотрим,
        # чья это публикация, по самому посту.
        put(COL_SOURCE, post.source or None)

        owner = post.source or link
        if is_own_page(owner, own_pages) or is_own_page(link, own_pages):
            for column, value in ((COL_VIEWS, post.views), (COL_COMMENTS, post.comments)):
                put(column, value, overwrite=refresh)
        else:
            if has_numbers:
                for column in (COL_VIEWS, COL_COMMENTS):
                    sheet.cell(row=row, column=column).value = None
                result.cleared += 1
            result.foreign += 1

        if has_numbers:
            result.updated += 1
        else:
            result.filled += 1

    for row in range(2, sheet.max_row + 1):
        if str(sheet.cell(row=row, column=COL_LINK).value or "").strip().startswith("http"):
            if not sheet.cell(row=row, column=COL_REGION).value:
                result.no_region.append(f"строка {row}")

    for rows in seen.values():
        if len(rows) > 1:
            regions = [str(sheet.cell(row=r, column=COL_REGION).value or "—") for r in rows]
            places = ", ".join(f"{r} ({reg})" for r, reg in zip(rows, regions))
            result.duplicates.append(f"строки {places}")

    save_workbook(workbook, path, on_locked)
    return result
