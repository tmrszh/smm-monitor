"""Telegram через Telethon: просмотры, реакции и комментарии по каждому посту.

Нужны TELEGRAM_API_ID / TELEGRAM_API_HASH (my.telegram.org) в окружении или .env.
Первый запуск попросит код подтверждения и сохранит сессию в файл smm-monitor.session.
"""

from __future__ import annotations

import os

from ..models import Post
from .common import channel_username

SESSION_NAME = os.getenv("TELEGRAM_SESSION", "smm-monitor")


def collect_telegram_api(url: str, limit: int = 100) -> list[Post]:
    try:
        from telethon.sync import TelegramClient
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise RuntimeError(
            "Для backend=api установите telethon: pip install telethon"
        ) from exc

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise RuntimeError("Задайте TELEGRAM_API_ID и TELEGRAM_API_HASH")

    username = channel_username(url)
    posts: list[Post] = []

    with TelegramClient(SESSION_NAME, int(api_id), api_hash) as client:
        for message in client.iter_messages(username, limit=limit):
            if message is None:
                continue
            likes = None
            if getattr(message, "reactions", None) and message.reactions.results:
                likes = sum(r.count for r in message.reactions.results)
            comments = None
            if getattr(message, "replies", None):
                comments = message.replies.replies
            posts.append(
                Post(
                    platform="telegram",
                    url=f"https://t.me/{username}/{message.id}",
                    source=f"https://t.me/{username}",
                    posted_at=message.date.isoformat() if message.date else None,
                    description=(message.message or "").strip(),
                    views=getattr(message, "views", None),
                    likes=likes,
                    comments=comments,
                )
            )
    return posts
