"""Общие утилиты сборщиков."""

from __future__ import annotations

import re

_SUFFIX = {"k": 1_000, "к": 1_000, "m": 1_000_000, "м": 1_000_000, "g": 1_000_000_000}


def parse_count(raw: str | None) -> int | None:
    """«1.2K», «12 345», «3,4 тыс.» -> int."""
    if raw is None:
        return None
    text = raw.strip().lower().replace("\xa0", " ")
    if not text:
        return None
    text = text.replace("тыс.", "k").replace("тыс", "k").replace("млн", "m")
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*([kкmмg]?)", text)
    if not match:
        return None
    number = float(match.group(1).replace(",", "."))
    return int(round(number * _SUFFIX.get(match.group(2), 1)))


def channel_username(url: str) -> str:
    """https://t.me/s/foo/123 -> foo; @foo -> foo."""
    cleaned = url.strip().rstrip("/")
    cleaned = re.sub(r"^https?://", "", cleaned)
    cleaned = re.sub(r"^(t\.me|telegram\.me)/", "", cleaned)
    cleaned = re.sub(r"^s/", "", cleaned)
    cleaned = cleaned.lstrip("@")
    return cleaned.split("/")[0].split("?")[0]


def instagram_username(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    cleaned = re.sub(r"^https?://", "", cleaned)
    cleaned = re.sub(r"^(www\.)?instagram\.com/", "", cleaned)
    cleaned = cleaned.lstrip("@")
    return cleaned.split("/")[0].split("?")[0]
