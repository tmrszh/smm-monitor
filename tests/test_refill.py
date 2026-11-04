"""Правила дозаполнения, которые проверяются без интернета."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smm_monitor.refill import is_own_page, link_key, normalize_region
from smm_monitor.regions import RegionBook


def main() -> None:
    book = RegionBook.load()

    # как люди пишут регион руками -> как он назван в таблице
    cases = {
        "Алматы": "г. Алматы",
        "алматы": "г. Алматы",
        "Астана": "г. Астана",
        "Шымкент": "г. Шымкент",
        "Улытау": "Ұлытау",
        "Алматинская обл": "Алмат. обл.",
        "Семей": "Абай",
        "Абай; Алматы": "Абай; г. Алматы",
    }
    for typed, expected in cases.items():
        got = normalize_region(typed, book)
        assert got == expected, f"{typed!r}: {got!r} вместо {expected!r}"
    assert normalize_region("непонятно что", book) is None

    # город Семей — да, «семейный» — нет
    assert book.detect("Студенту Семея перевели деньги") == ["Абай"]
    assert book.detect("семейный бюджет") == []

    # один пост под разными ссылками
    assert link_key("https://www.instagram.com/reel/DeHCeC1uU0D/?cplk=O") == link_key(
        "https://www.instagram.com/p/DeHCeC1uU0D/"
    )
    assert link_key("https://t.me/s/afm_rk/3816") == link_key("https://t.me/afm_rk/3816")

    pages = ["t.me/afm_rk", "instagram.com/afm_rk"]
    assert is_own_page("https://www.instagram.com/afm_rk/", pages)
    assert not is_own_page("https://www.instagram.com/tengrinewskz/", pages)

    print("OK: правила дозаполнения")


if __name__ == "__main__":
    main()
