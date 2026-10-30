"""Приложение «в один клик»: собирает отчёт и открывает его.

Запускается двойным щелчком (внутри — собранный PyInstaller исполняемый файл),
поэтому здесь нет аргументов командной строки: всё спрашивается у человека
и пишется на Рабочий стол.
"""

from __future__ import annotations

import json
import subprocess
import sys
import traceback
from datetime import date
from pathlib import Path

from smm_monitor.collectors import collect
from smm_monitor.net import CERTIFICATE_HELP, is_certificate_error, use_system_certificates
from smm_monitor.excel_report import build_workbook
from smm_monitor.refill import refill_workbook
from smm_monitor.regions import RegionBook

DEFAULT_LIMIT = 100


def base_dir() -> Path:
    """Папка с данными: рядом с исполняемым файлом или рядом с исходниками."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def windows_desktop() -> Path | None:
    """Настоящий Рабочий стол Windows: при включённом OneDrive он лежит внутри него."""
    try:
        import ctypes
        from ctypes import windll, wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_byte * 8),
            ]

        desktop_id = GUID(
            0xB4BFCC3A, 0xDB2C, 0x424C,
            (ctypes.c_byte * 8)(0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41),
        )
        buffer = ctypes.c_wchar_p()
        if windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(desktop_id), 0, None, ctypes.byref(buffer)
        ) != 0:
            return None
        path = Path(buffer.value)
        windll.ole32.CoTaskMemFree(buffer)
        return path if path.is_dir() else None
    except Exception:
        return None


def app_folder() -> Path:
    """Папка, где лежит сам файл программы (туда же можно положить сертификат)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def use_local_certificate() -> Path | None:
    """Если рядом с программой лежит файл сертификата организации — взять его."""
    import os

    for name in ("сертификат.pem", "certificate.pem", "сертификат.crt", "certificate.crt"):
        path = app_folder() / name
        if path.is_file():
            os.environ["REQUESTS_CA_BUNDLE"] = str(path)
            os.environ["SSL_CERT_FILE"] = str(path)
            return path
    return None


def desktop() -> Path:
    if sys.platform.startswith("win"):
        found = windows_desktop()
        if found:
            return found
        one_drive = Path.home() / "OneDrive" / "Desktop"
        if one_drive.is_dir():
            return one_drive
    for name in ("Desktop", "Рабочий стол"):
        path = Path.home() / name
        if path.is_dir():
            return path
    return Path.home()


def open_file(path: Path) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        elif sys.platform.startswith("win"):
            import os

            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception:
        pass


def ask_limit() -> int:
    print("Сколько последних публикаций брать с каждой площадки?")
    answer = input(f"Нажмите Enter для {DEFAULT_LIMIT} или введите число: ").strip()
    if not answer:
        return DEFAULT_LIMIT
    try:
        value = int(answer)
    except ValueError:
        print(f"Не похоже на число, беру {DEFAULT_LIMIT}.")
        return DEFAULT_LIMIT
    return max(1, min(value, 1000))


def ask_mode() -> str:
    print("Что сделать?")
    print("  1 — собрать свежий отчёт по каналам АФМ")
    print("  2 — дополнить файл, в который вы вставили ссылки")
    print()
    while True:
        answer = input("Введите 1 или 2 и нажмите Enter: ").strip()
        if answer in ("1", "2", ""):
            return answer or "1"
        print("Нужно 1 или 2.")


def ask_file() -> Path | None:
    print()
    print("Перетащите файл Excel в это окно и нажмите Enter.")
    raw = input("Путь к файлу: ").strip().strip("'\"")
    if not raw:
        return None
    path = Path(raw.replace("\\ ", " ")).expanduser()
    if not path.is_file():
        print(f"Файл не найден: {path}")
        return None
    return path


def run_refill(region_book: RegionBook) -> None:
    path = ask_file()
    if path is None:
        return
    print()
    print("Иду по ссылкам, это может занять несколько минут. Окно не закрывайте.")
    print()
    result = refill_workbook(path, region_book, progress=lambda link: print(f"  {link}", flush=True))
    if any(is_certificate_error(Exception(problem)) for problem in result.failed):
        print(CERTIFICATE_HELP)
    print()
    print(f"Заполнено строк: {result.filled}")
    if result.skipped:
        print(f"Пропущено, цифры уже были: {result.skipped}")
    for problem in result.failed:
        print(f"Не получилось: {problem}")
    print()
    print(f"Файл сохранён: {path}")
    open_file(path)


def run_collect(sources: list, region_book: RegionBook) -> None:
    limit = ask_limit()
    print()
    print("Собираю. Телеграм занимает около минуты, инстаграм — несколько минут.")
    print("Окно не закрывайте.")
    print()

    posts = []
    for source in sources:
        title = source.get("title") or source["url"]
        print(f"  {title} ...", flush=True)
        try:
            found = collect(source, limit, region_book)
        except Exception as error:
            if is_certificate_error(error):
                print(f"    {CERTIFICATE_HELP}")
            else:
                print(f"    не удалось собрать: {error}")
            continue
        print(f"    публикаций: {len(found)}")
        posts.extend(found)

    if not posts:
        print()
        print("Ничего не собралось. Проверьте интернет и попробуйте ещё раз.")
        return

    out = desktop() / f"Отчёт АФМ {date.today():%d.%m.%Y}.xlsx"
    build_workbook(posts, region_book, out)

    print()
    print(f"Готово: {out}")
    print("Файл сохранён на Рабочий стол и сейчас откроется.")
    open_file(out)


def main() -> None:
    print("=" * 58)
    print("  Отчёт по соцсетям АФМ")
    print("=" * 58)
    print()

    use_system_certificates()
    certificate = use_local_certificate()
    if certificate:
        print(f"Использую сертификат организации: {certificate.name}")
        print()

    config = json.loads((base_dir() / "config" / "sources.json").read_text(encoding="utf-8"))
    region_book = RegionBook.load(base_dir() / "config" / "regions.json")

    if ask_mode() == "2":
        run_refill(region_book)
    else:
        run_collect(config["sources"], region_book)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print()
        print("Что-то пошло не так:")
        traceback.print_exc()
    finally:
        print()
        input("Нажмите Enter, чтобы закрыть окно...")
