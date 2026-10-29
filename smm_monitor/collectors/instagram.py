"""Instagram через instaloader: лайки, комментарии, просмотры видео по каждому посту.

Instagram закрывает анонимный доступ, поэтому полезно указать
INSTAGRAM_LOGIN (сессия берётся из `instaloader --login <логин>`).
"""

from __future__ import annotations

import os
from itertools import islice

from ..models import Post
from .common import instagram_username


def _client():
    try:
        import instaloader
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise RuntimeError(
            "Для Instagram установите instaloader: pip install instaloader"
        ) from exc

    loader = instaloader.Instaloader(
        quiet=True,
        download_pictures=False,
        download_videos=False,
        download_comments=False,
        save_metadata=False,
        request_timeout=30.0,
    )
    login = os.getenv("INSTAGRAM_LOGIN")
    session_file = os.getenv("INSTAGRAM_SESSION_FILE")
    if login:
        loader.load_session_from_file(login, session_file)
    return instaloader, loader


def _views(item) -> int | None:
    """У фото просмотров в API нет; у видео/reels счётчик лежит в разных полях."""
    if not item.is_video:
        return None
    for attr in ("video_view_count", "video_play_count"):
        value = getattr(item, attr, None)
        if value:
            return int(value)
    return None


def collect_instagram(url: str, limit: int = 100) -> list[Post]:
    instaloader, loader = _client()
    username = instagram_username(url)
    profile = instaloader.Profile.from_username(loader.context, username)

    posts: list[Post] = []
    for item in islice(profile.get_posts(), limit):
        posts.append(
            Post(
                platform="instagram",
                url=f"https://www.instagram.com/p/{item.shortcode}/",
                source=f"https://www.instagram.com/{username}/",
                posted_at=item.date_utc.isoformat() if item.date_utc else None,
                description=(item.caption or "").strip(),
                views=_views(item),
                likes=item.likes,
                comments=item.comments,
            )
        )
    return posts
