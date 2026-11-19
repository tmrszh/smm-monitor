"""Instagram через instaloader: лайки, комментарии, просмотры видео по каждому посту.

Instagram закрыл анонимный доступ, поэтому нужен вход в аккаунт. Пароль
нигде не хранится: после входа сохраняется только сессия (как «запомнить меня»
в браузере) в файл SESSION_FILE рядом с программой.

Для запуска из консоли можно по-старому указать INSTAGRAM_LOGIN
(сессия из `instaloader --login <логин>`).
"""

from __future__ import annotations

import json
import os
from itertools import islice
from pathlib import Path

from ..models import Post
from .common import instagram_username

SESSION_FILE = "инстаграм-вход.json"
# куда app.py кладёт файл сессии; None — рядом с текущей папкой
session_folder: Path | None = None


def session_path() -> Path:
    return (session_folder or Path.cwd()) / SESSION_FILE


def has_session() -> bool:
    return session_path().is_file()


def _new_loader():
    import instaloader

    return instaloader.Instaloader(
        quiet=True,
        download_pictures=False,
        download_videos=False,
        download_comments=False,
        save_metadata=False,
        request_timeout=30.0,
    )


class LoginProblem(RuntimeError):
    """Понятное человеку объяснение, почему войти не вышло."""


def login(username: str, password: str, ask_code) -> str:
    """Войти и сохранить сессию. ask_code() спрашивает код двухэтапной проверки.

    Возвращает имя аккаунта. Пароль не сохраняется.
    """
    from instaloader.exceptions import (
        BadCredentialsException,
        ConnectionException,
        TwoFactorAuthRequiredException,
    )

    username = username.strip().lstrip("@")
    loader = _new_loader()
    try:
        try:
            loader.login(username, password)
        except TwoFactorAuthRequiredException:
            loader.two_factor_login(ask_code().strip().replace(" ", ""))
    except BadCredentialsException as error:
        raise LoginProblem("Неверный логин или пароль.") from error
    except ConnectionException as error:
        text = str(error).lower()
        if "checkpoint" in text or "challenge" in text:
            raise LoginProblem(
                "Инстаграм просит подтвердить вход. Откройте инстаграм на телефоне,\n"
                "там будет вопрос, вы ли это входите, нажмите «Это я».\n"
                "Потом запустите программу и войдите ещё раз."
            ) from error
        if "wait a few minutes" in text or "429" in text:
            raise LoginProblem("Инстаграм просит подождать. Попробуйте минут через 15.") from error
        raise LoginProblem(f"Инстаграм не пустил: {error}") from error

    data = {"username": loader.context.username or username, "session": loader.save_session()}
    path = session_path()
    path.write_text(json.dumps(data), encoding="utf-8")
    return data["username"]


def logout() -> None:
    try:
        session_path().unlink()
    except FileNotFoundError:
        pass


def session_owner() -> str | None:
    try:
        return json.loads(session_path().read_text(encoding="utf-8"))["username"]
    except Exception:
        return None


def _client():
    try:
        import instaloader
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise RuntimeError(
            "Для Instagram установите instaloader: pip install instaloader"
        ) from exc

    loader = _new_loader()
    env_login = os.getenv("INSTAGRAM_LOGIN")
    if env_login:
        loader.load_session_from_file(env_login, os.getenv("INSTAGRAM_SESSION_FILE"))
    elif has_session():
        try:
            data = json.loads(session_path().read_text(encoding="utf-8"))
            loader.load_session(data["username"], data["session"])
        except Exception:
            pass  # файл испорчен — работаем без входа, app.py предложит войти заново
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
