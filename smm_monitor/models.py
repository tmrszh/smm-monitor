"""Модель одного поста и его метрик."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Post:
    platform: str                      # "telegram" | "instagram"
    url: str                           # ссылка на конкретный пост
    source: str                        # ссылка/имя канала или аккаунта
    posted_at: str | None = None       # ISO-дата публикации
    description: str = ""               # описание (подпись) поста
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    regions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def regions_cell(self) -> str:
        """Строка для колонки «Регион» в Excel (несколько регионов — через «; »)."""
        return "; ".join(self.regions)
