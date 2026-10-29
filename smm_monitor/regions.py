"""Справочник регионов и определение региона по тексту поста."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "regions.json"

NO_REGION = "Без региона"


def _compile_alias(alias: str) -> re.Pattern[str]:
    """«караганд*» — любое слово с таким началом, «ско» — только слово целиком,
    «re:...» — готовое регулярное выражение для сложных случаев."""
    alias = alias.strip().lower()
    if alias.startswith("re:"):
        return re.compile(alias[3:], re.IGNORECASE)
    if alias.endswith("*"):
        return re.compile(r"(?<!\w)" + re.escape(alias[:-1]), re.IGNORECASE)
    return re.compile(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", re.IGNORECASE)


@dataclass(frozen=True)
class Region:
    name: str
    aliases: tuple[str, ...]


class RegionBook:
    """Список регионов учёта + поиск упоминаний в тексте."""

    def __init__(self, regions: list[Region]) -> None:
        self.regions = regions
        self._patterns = [
            (region, [_compile_alias(alias) for alias in region.aliases]) for region in regions
        ]

    @classmethod
    def load(cls, path: str | Path | None = None) -> "RegionBook":
        path = Path(path) if path else DEFAULT_CONFIG
        data = json.loads(path.read_text(encoding="utf-8"))
        regions = [
            Region(name=item["name"], aliases=tuple(item.get("aliases") or [item["name"]]))
            for item in data["regions"]
        ]
        if not regions:
            raise ValueError(f"В {path} не задан ни один регион")
        return cls(regions)

    @property
    def names(self) -> list[str]:
        return [r.name for r in self.regions]

    def detect(self, text: str) -> list[str]:
        """Все регионы, упомянутые в тексте, в порядке справочника."""
        if not text:
            return []
        lowered = text.lower()
        found: list[str] = []
        for region, patterns in self._patterns:
            if any(p.search(lowered) for p in patterns):
                found.append(region.name)
        return found
