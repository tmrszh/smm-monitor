"""Демо-набор постов для проверки отчёта без доступа к сети."""

from smm_monitor.models import Post

RAW = [
    ("telegram", "https://t.me/demo/101", "Рейд в Туркестанской области: изъято 120 кг", 15400, 210, 18),
    ("telegram", "https://t.me/demo/102", "Задержание в Шымкенте и Туркестанской области", 9800, 150, 7),
    ("telegram", "https://t.me/demo/103", "Профилактика в Астане", 22100, 430, 51),
    ("instagram", "https://www.instagram.com/p/AAA/", "Туркестанская область: итоги месяца", 5400, 820, 34),
    ("instagram", "https://www.instagram.com/p/BBB/", "Операция в Атырау", None, 640, 12),
    ("instagram", "https://www.instagram.com/p/CCC/", "Без привязки к региону", None, 300, 4),
]


def demo_posts(region_book):
    posts = []
    for platform, url, text, views, likes, comments in RAW:
        post = Post(
            platform=platform,
            url=url,
            source="demo",
            posted_at="2026-10-20T10:00:00",
            description=text,
            views=views,
            likes=likes,
            comments=comments,
        )
        post.regions = region_book.detect(text)
        posts.append(post)
    return posts
