"""Метрики по одной конкретной ссылке на пост.

Нужно, когда ссылки вставляют руками в готовый файл: по каждой строке идём
на сам пост и дотягиваем описание, дату и цифры.
"""

from __future__ import annotations

import re

import requests

from ..models import Post
from .common import channel_username, instagram_username
from .telegram_web import HEADERS, TIMEOUT, _parse_page

TELEGRAM_POST = re.compile(r"(?:t|telegram)\.me/(?:s/)?([\w\d_]+)/(\d+)")
INSTAGRAM_POST = re.compile(r"instagram\.com/(?:p|reel|tv)/([\w\-]+)")


def platform_of(url: str) -> str | None:
    if TELEGRAM_POST.search(url):
        return "telegram"
    if INSTAGRAM_POST.search(url):
        return "instagram"
    return None


def _telegram_post(url: str) -> Post | None:
    match = TELEGRAM_POST.search(url)
    if not match:
        return None
    username, post_id = match.group(1), match.group(2)
    embed = f"https://t.me/{username}/{post_id}?embed=1&mode=tme"
    response = requests.get(embed, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    posts = _parse_page(response.text, username)
    for post in posts:
        if post.url.rsplit("/", 1)[-1] == post_id:
            return post
    if posts:
        return posts[0]
    if "tgme_widget_message_error" in response.text:
        raise ValueError(
            "телеграм не отдаёт этот пост по прямой ссылке "
            "(бывает у отдельных фото внутри альбома) — скопируйте ссылку заново из канала"
        )
    return None


def _instagram_post(url: str) -> Post | None:
    match = INSTAGRAM_POST.search(url)
    if not match:
        return None
    from .instagram import _client, _views

    instaloader, loader = _client()
    item = instaloader.Post.from_shortcode(loader.context, match.group(1))
    return Post(
        platform="instagram",
        url=f"https://www.instagram.com/p/{item.shortcode}/",
        source=f"https://www.instagram.com/{item.owner_username}/",
        posted_at=item.date_utc.isoformat() if item.date_utc else None,
        description=(item.caption or "").strip(),
        views=_views(item),
        likes=item.likes,
        comments=item.comments,
    )


def fetch_post(url: str) -> Post | None:
    """Пост по прямой ссылке. None — если ссылка не распознана."""
    platform = platform_of(url)
    if platform == "telegram":
        return _telegram_post(url)
    if platform == "instagram":
        return _instagram_post(url)
    return None
