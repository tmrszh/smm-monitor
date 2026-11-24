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
# старое место: рядом с программой (app.py задаёт папку). Его читаем, чтобы
# не просить войти заново тех, кто уже вошёл в прошлой версии.
session_folder: Path | None = None


def _settings_folder() -> Path:
    """Постоянная папка настроек: вход не теряется, если программу заменить
    новой версией или положить в другую папку."""
    base = os.getenv("APPDATA")
    folder = Path(base) / "Отчёт АФМ" if base else Path.home() / ".afm-report"
    return folder


def session_path() -> Path:
    """Куда сохранять вход."""
    return _settings_folder() / SESSION_FILE


def _old_places() -> list[Path]:
    """Где мог остаться вход от прошлой версии: рядом с программой, в Загрузках
    или на Рабочем столе (и в папках на один уровень глубже)."""
    places = [(session_folder or Path.cwd()) / SESSION_FILE]
    home = Path.home()
    for folder in (
        home / "Downloads", home / "Загрузки", home / "Desktop", home / "Рабочий стол",
        home / "OneDrive" / "Desktop", home / "OneDrive" / "Рабочий стол",
    ):
        try:
            places.append(folder / SESSION_FILE)
            places.extend(folder.glob(f"*/{SESSION_FILE}"))
        except Exception:
            continue
    return places


def _existing_session() -> Path | None:
    if session_path().is_file():
        return session_path()
    for path in _old_places():
        try:
            if path.is_file():
                # переносим в постоянное место, чтобы дальше не искать
                try:
                    session_path().parent.mkdir(parents=True, exist_ok=True)
                    session_path().write_bytes(path.read_bytes())
                    return session_path()
                except Exception:
                    return path
        except Exception:
            continue
    return None


def has_session() -> bool:
    return _existing_session() is not None


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data["username"]


def logout() -> None:
    for path in (session_path(), *_old_places()):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _read_session() -> dict | None:
    path = _existing_session()
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def session_owner() -> str | None:
    data = _read_session()
    return data.get("username") if data else None


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
    else:
        data = _read_session()
        if data:
            try:
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
