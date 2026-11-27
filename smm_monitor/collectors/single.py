"""Метрики по одной конкретной ссылке на пост.

Нужно, когда ссылки вставляют руками в готовый файл: по каждой строке идём
на сам пост и дотягиваем описание, дату и цифры.
"""

from __future__ import annotations

import re
import time

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


# Инстаграм быстро ограничивает частые запросы, особенно если на каждую ссылку
# открывать новое соединение. Поэтому одно соединение на весь прогон и пауза.
INSTAGRAM_PAUSE = 3.0
_instagram: tuple | None = None
_last_instagram_request = 0.0


def _instagram_client():
    global _instagram
    if _instagram is None:
        from .instagram import _client

        _instagram = _client()
    return _instagram


def _explain_instagram_error(error: Exception) -> str:
    text = str(error).lower()
    if "wait a few minutes" in text or "429" in text or "too many" in text:
        return (
            "инстаграм временно ограничил запросы. Запустите программу ещё раз "
            "минут через 15, уже заполненные строки она повторно не тронет"
        )
    if "please wait" in text or "feedback" in text:
        return (
            "инстаграм временно ограничил запросы. Запустите программу ещё раз "
            "минут через 15, уже заполненные строки она повторно не тронет"
        )
    if "challenge" in text or "checkpoint" in text:
        return (
            "инстаграм просит подтвердить вход: откройте его на телефоне, "
            "нажмите «Это я», потом в программе введите 4 и войдите заново"
        )
    if "login" in text or "401" in text or "403" in text or "metadata failed" in text:
        from .instagram import has_session

        if has_session():
            return (
                "инстаграм не открыл пост. Возможно, вход в аккаунт устарел: "
                "запустите программу, введите 4 и войдите заново"
            )
        return "инстаграм не показывает пост без входа в аккаунт: запустите программу и введите 4"
    if "not found" in text or "404" in text or "doesn't exist" in text:
        return "пост не найден, возможно, его удалили или ссылка неполная"
    return f"инстаграм не ответил ({error})"


def _instagram_post_via_app(client, shortcode: str) -> Post:
    """Пост через клиент, вошедший как мобильное приложение."""
    from .instagram import call_with_fallback

    media = call_with_fallback(client, lambda: client.media_info_v1(client.media_pk_from_code(shortcode)))
    owner = media.user.username if media.user else ""
    views = media.play_count or media.view_count
    return Post(
        platform="instagram",
        url=f"https://www.instagram.com/p/{media.code or shortcode}/",
        source=f"https://www.instagram.com/{owner}/" if owner else None,
        posted_at=media.taken_at.isoformat() if media.taken_at else None,
        description=(media.caption_text or "").strip(),
        views=int(views) if views else None,
        likes=media.like_count,
        comments=media.comment_count,
    )


def _instagram_post_app(instaloader, loader, shortcode: str) -> Post:
    """Пост через запрос мобильного приложения (только после входа)."""
    media_id = instaloader.Post.shortcode_to_mediaid(shortcode)
    data = loader.context.get_iphone_json(f"api/v1/media/{media_id}/info/", {})
    media = (data.get("items") or [None])[0]
    if not media:
        raise ValueError("пустой ответ")
    caption = media.get("caption") or {}
    taken_at = media.get("taken_at")
    views = media.get("play_count") or media.get("view_count") or media.get("ig_play_count")
    from datetime import datetime, timezone

    owner = (media.get("user") or {}).get("username") or ""
    return Post(
        platform="instagram",
        url=f"https://www.instagram.com/p/{media.get('code') or shortcode}/",
        source=f"https://www.instagram.com/{owner}/" if owner else None,
        posted_at=datetime.fromtimestamp(taken_at, timezone.utc).isoformat() if taken_at else None,
        description=(caption.get("text") or "").strip(),
        views=int(views) if views else None,
        likes=media.get("like_count"),
        comments=media.get("comment_count"),
    )


def _instagram_post(url: str) -> Post | None:
    global _last_instagram_request
    match = INSTAGRAM_POST.search(url)
    if not match:
        return None
    from .instagram import _views

    from .instagram import app_client

    wait = INSTAGRAM_PAUSE - (time.monotonic() - _last_instagram_request)
    if wait > 0:
        time.sleep(wait)

    client = app_client()
    if client is not None:
        try:
            return _instagram_post_via_app(client, match.group(1))
        except Exception as error:
            raise RuntimeError(_explain_instagram_error(error)) from error
        finally:
            _last_instagram_request = time.monotonic()

    instaloader, loader = _instagram_client()
    try:
        if loader.context.is_logged_in:
            # После входа берём пост тем же способом, что и приложение
            # инстаграма: этот запрос работает, даже когда веб-запрос
            # instaloader перестаёт отвечать после очередных изменений сайта.
            try:
                return _instagram_post_app(instaloader, loader, match.group(1))
            except Exception:
                pass
        item = instaloader.Post.from_shortcode(loader.context, match.group(1))
    except Exception as error:
        raise RuntimeError(_explain_instagram_error(error)) from error
    finally:
        _last_instagram_request = time.monotonic()
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
