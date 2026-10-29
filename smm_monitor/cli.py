"""CLI: собрать метрики по ссылкам и выгрузить Excel.

    python -m smm_monitor.cli collect --source https://t.me/channel \
        --source https://www.instagram.com/account/ --limit 100

    python -m smm_monitor.cli template          # пустая экселька с формулами
    python -m smm_monitor.cli from-json out/posts.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .collectors import collect
from .excel_report import build_workbook
from .refill import refill_workbook
from .models import Post
from .regions import RegionBook

DEFAULT_OUT = Path("out")


def _platform_of(url: str) -> str:
    low = url.lower()
    if "t.me" in low or "telegram.me" in low:
        return "telegram"
    if "instagram.com" in low:
        return "instagram"
    raise SystemExit(f"Не понял платформу по ссылке: {url}")


def _sources_from_args(args) -> list[dict]:
    sources: list[dict] = []
    if args.config:
        data = json.loads(Path(args.config).read_text(encoding="utf-8"))
        sources.extend(data.get("sources", []))
    for url in args.source or []:
        sources.append({"platform": _platform_of(url), "url": url})
    if not sources:
        raise SystemExit("Укажите --source <ссылка> или --config config/sources.json")
    return sources


def cmd_collect(args) -> None:
    region_book = RegionBook.load(args.regions)
    posts: list[Post] = []
    for source in _sources_from_args(args):
        print(f"→ {source['platform']}: {source['url']}", file=sys.stderr)
        try:
            found = collect(source, args.limit, region_book, telegram_backend=args.telegram_backend)
        except Exception as error:  # сбор по одному источнику не должен ломать весь прогон
            print(f"  ! ошибка: {error}", file=sys.stderr)
            continue
        print(f"  собрано постов: {len(found)}", file=sys.stderr)
        posts.extend(found)

    json_path = Path(args.json or DEFAULT_OUT / "posts.json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps([p.to_dict() for p in posts], ensure_ascii=False, indent=2), encoding="utf-8"
    )

    xlsx = build_workbook(posts, region_book, args.out or DEFAULT_OUT / "smm-report.xlsx")
    print(f"JSON:  {json_path.resolve()}")
    print(f"Excel: {xlsx.resolve()}")


def cmd_template(args) -> None:
    region_book = RegionBook.load(args.regions)
    xlsx = build_workbook([], region_book, args.out or DEFAULT_OUT / "smm-template.xlsx")
    print(f"Excel: {xlsx.resolve()}")


def cmd_from_json(args) -> None:
    region_book = RegionBook.load(args.regions)
    raw = json.loads(Path(args.path).read_text(encoding="utf-8"))
    posts = [Post(**item) for item in raw]
    for post in posts:  # справочник мог измениться с момента сбора
        post.regions = region_book.detect(post.description)
    xlsx = build_workbook(posts, region_book, args.out or DEFAULT_OUT / "smm-report.xlsx")
    print(f"Excel: {xlsx.resolve()}")


def cmd_refill(args) -> None:
    region_book = RegionBook.load(args.regions)
    result = refill_workbook(
        args.path,
        region_book,
        refresh=args.refresh,
        progress=lambda link: print(f"  {link}", file=sys.stderr),
    )
    print(f"Заполнено строк: {result.filled}")
    if result.updated:
        print(f"Обновлено строк: {result.updated}")
    if result.skipped:
        print(f"Пропущено (цифры уже есть): {result.skipped}")
    for problem in result.failed:
        print(f"Не удалось: {problem}")
    print(f"Файл: {Path(args.path).resolve()}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="smm-monitor", description=__doc__)
    parser.add_argument("--regions", help="путь к справочнику регионов (по умолчанию config/regions.json)")
    parser.add_argument("--out", help="путь к .xlsx")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(target):
        """--regions/--out можно указывать и после имени команды."""
        target.add_argument("--regions", default=argparse.SUPPRESS)
        target.add_argument("--out", default=argparse.SUPPRESS)

    collect_parser = sub.add_parser("collect", help="собрать метрики и выгрузить Excel")
    collect_parser.add_argument("--source", action="append", help="ссылка на канал/аккаунт (можно несколько)")
    collect_parser.add_argument("--config", help="json со списком источников")
    collect_parser.add_argument("--limit", type=int, default=100, help="сколько последних постов брать")
    collect_parser.add_argument(
        "--telegram-backend",
        choices=["web", "api"],
        default="web",
        help="web — без авторизации (просмотры, реакции); api — Telethon (ещё и комментарии)",
    )
    collect_parser.add_argument("--json", help="куда сохранить сырые данные")
    add_common(collect_parser)
    collect_parser.set_defaults(func=cmd_collect)

    template_parser = sub.add_parser("template", help="пустая экселька с листами и формулами")
    add_common(template_parser)
    template_parser.set_defaults(func=cmd_template)

    refill_parser = sub.add_parser(
        "refill", help="дозаполнить метрики по ссылкам, вставленным в готовый файл"
    )
    refill_parser.add_argument("path", help="путь к .xlsx")
    refill_parser.add_argument(
        "--refresh", action="store_true", help="перезаписать цифры во всех строках свежими"
    )
    add_common(refill_parser)
    refill_parser.set_defaults(func=cmd_refill)

    json_parser = sub.add_parser("from-json", help="пересобрать Excel из ранее собранного JSON")
    json_parser.add_argument("path")
    add_common(json_parser)
    json_parser.set_defaults(func=cmd_from_json)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
