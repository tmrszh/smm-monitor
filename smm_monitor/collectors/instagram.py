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


def _app_client(settings: dict | None = None):
    """Клиент, который ходит в инстаграм так же, как его мобильное приложение."""
    from instagrapi import Client

    from ..net import system_ca_bundle

    client = Client(settings=settings, delay_range=[1, 3], timezone_offset=5 * 3600)
    client.logger.disabled = True
    # В рабочей сети трафик идёт через шлюз со своим сертификатом. Python его
    # берёт из хранилища Windows, а curl внутри instagrapi — нет, поэтому
    # отдаём ему файл со всеми сертификатами компьютера.
    bundle = system_ca_bundle(_settings_folder())
    client.set_tls_verify(bundle or True)
    return client


def _is_tls_problem(error: BaseException) -> bool:
    text = f"{type(error).__name__} {error}".lower()
    return "ssl" in text or "certificate" in text or "tls" in text


def _use_plain_transport(client) -> None:
    """Запасной путь: обычные запросы Python, которые сверяются с хранилищем
    Windows (через truststore). Нужен, если шлюз сети не пропускает curl."""
    client.set_retry_config(private_transport="requests")


def call_with_fallback(client, action):
    """Выполнить запрос; при проблеме с сертификатом — повторить запасным путём."""
    try:
        return action()
    except Exception as error:
        if not _is_tls_problem(error):
            raise
        _use_plain_transport(client)
        return action()


def login(username: str, password: str, ask_code) -> str:
    """Войти и сохранить вход. ask_code() спрашивает код подтверждения.

    Вход идёт как из мобильного приложения: вход через сайт инстаграм
    программам больше не даёт («fail» без объяснений). Возвращает имя
    аккаунта. Пароль не сохраняется.
    """
    from instagrapi.exceptions import (
        BadCredentials,
        BadPassword,
        ChallengeRequired,
        ChallengeUnknownStep,
        PleaseWaitFewMinutes,
        RecaptchaChallengeForm,
        SelectContactPointRecoveryForm,
        TwoFactorRequired,
    )

    username = username.strip().lstrip("@")
    client = _app_client()
    client.challenge_code_handler = lambda _user, _choice: ask_code().strip().replace(" ", "")
    try:
        try:
            call_with_fallback(client, lambda: client.login(username, password))
        except TwoFactorRequired:
            code = ask_code().strip().replace(" ", "")
            call_with_fallback(client, lambda: client.login(username, password, verification_code=code))
    except (BadPassword, BadCredentials) as error:
        raise LoginProblem(
            "Неверный логин или пароль. Проверьте, что включена английская раскладка."
        ) from error
    except PleaseWaitFewMinutes as error:
        raise LoginProblem("Инстаграм просит подождать. Попробуйте минут через 15.") from error
    except (
        ChallengeRequired,
        ChallengeUnknownStep,
        RecaptchaChallengeForm,
        SelectContactPointRecoveryForm,
    ) as error:
        raise LoginProblem(
            "Инстаграм просит подтвердить вход. Откройте инстаграм на телефоне,\n"
            "там будет вопрос, вы ли это входите, нажмите «Это я».\n"
            "Потом запустите программу и войдите ещё раз."
        ) from error
    except LoginProblem:
        raise
    except Exception as error:
        if _is_tls_problem(error):
            from ..net import CERTIFICATE_HELP

            raise LoginProblem(CERTIFICATE_HELP) from error
        raise LoginProblem(f"Инстаграм не пустил: {error}") from error

    data = {"engine": "app", "username": username, "settings": client.get_settings()}
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, default=str), encoding="utf-8")
    return username


_app = None


def app_client():
    """Клиент со входом через приложение или None, если так не входили."""
    global _app
    if _app is None:
        data = _read_session()
        if not data or data.get("engine") != "app":
            return None
        _app = _app_client(data["settings"])
    return _app


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
        if data and "session" in data:
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
