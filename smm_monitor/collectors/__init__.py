"""Сборщики метрик по платформам."""

from .telegram_web import collect_telegram_web
from .telegram_api import collect_telegram_api
from .instagram import collect_instagram

__all__ = ["collect_telegram_web", "collect_telegram_api", "collect_instagram", "collect"]


def collect(source: dict, limit: int, region_book, telegram_backend: str = "web"):
    """Собрать посты одного источника: {"platform": ..., "url": ...}."""
    platform = source["platform"].strip().lower()
    url = source["url"].strip()
    if platform == "telegram":
        if telegram_backend == "api":
            posts = collect_telegram_api(url, limit=limit)
        else:
            posts = collect_telegram_web(url, limit=limit)
    elif platform == "instagram":
        posts = collect_instagram(url, limit=limit)
    else:
        raise ValueError(f"Неизвестная платформа: {platform}")
    for post in posts:
        post.regions = region_book.detect(post.description)
    return posts
