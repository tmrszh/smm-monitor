"""Telegram без авторизации: разбор публичной веб-версии канала t.me/s/<канал>.

Даёт ссылку на пост, описание, дату, просмотры и сумму реакций.
Количество комментариев в веб-превью не отдаётся — для него нужен backend "api"
(Telethon), см. telegram_api.py.
"""

from __future__ import annotations

import requests
from bs4 import BeautifulSoup

from ..models import Post
from .common import channel_username, parse_count

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ru,en;q=0.9",
}
TIMEOUT = 30


def _fetch(username: str, before: str | None) -> str:
    url = f"https://t.me/s/{username}"
    params = {"before": before} if before else None
    response = requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.text


def _parse_page(html: str, username: str) -> list[Post]:
    soup = BeautifulSoup(html, "html.parser")
    posts: list[Post] = []
    for block in soup.select("div.tgme_widget_message"):
        data_post = block.get("data-post")
        if not data_post:
            continue
        text_node = block.select_one("div.tgme_widget_message_text")
        description = text_node.get_text("\n", strip=True) if text_node else ""

        time_node = block.select_one("time[datetime]")
        posted_at = time_node["datetime"] if time_node else None

        views_node = block.select_one("span.tgme_widget_message_views")
        views = parse_count(views_node.get_text(strip=True)) if views_node else None

        # лайки = сумма обычных реакций (платные «звёзды» не считаем)
        likes = None
        reactions = [
            node
            for node in block.select("div.tgme_widget_message_reactions span.tgme_reaction")
            if "tgme_reaction_paid" not in (node.get("class") or [])
        ]
        if reactions:
            likes = sum(parse_count(node.get_text(strip=True)) or 0 for node in reactions)

        posts.append(
            Post(
                platform="telegram",
                url=f"https://t.me/{data_post}",
                source=f"https://t.me/{username}",
                posted_at=posted_at,
                description=description,
                views=views,
                likes=likes,
                comments=None,
            )
        )
    return posts


def collect_telegram_web(url: str, limit: int = 100) -> list[Post]:
    username = channel_username(url)
    collected: dict[str, Post] = {}
    before: str | None = None

    while len(collected) < limit:
        page = _parse_page(_fetch(username, before), username)
        if not page:
            break
        new = [post for post in page if post.url not in collected]
        if not new:
            break
        for post in new:
            collected[post.url] = post
        before = page[0].url.rsplit("/", 1)[-1]  # самый старый пост на странице
        if not before.isdigit():
            break

    posts = sorted(collected.values(), key=lambda p: p.posted_at or "", reverse=True)
    return posts[:limit]
