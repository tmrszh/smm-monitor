"""Настройка проверки сертификатов.

В корпоративных сетях (как в АФМ) трафик идёт через шлюз, который подменяет
сертификаты сайтов своим. Сам Python о таком сертификате не знает и обрывает
соединение с «certificate verify failed», хотя браузер на той же машине
работает нормально — он-то сверяется с хранилищем Windows, куда корпоративный
корневой сертификат уже добавлен.

Поэтому и мы сверяемся с системным хранилищем, а не с собственным списком.
"""

from __future__ import annotations

import os
import ssl
import sys
from pathlib import Path

CERTIFICATE_HELP = (
    "Не удалось проверить сертификат сайта.\n"
    "    Так бывает в рабочей сети, где трафик идёт через шлюз организации.\n"
    "    Попросите, пожалуйста, системного администратора добавить корневой\n"
    "    сертификат организации в хранилище Windows (он обычно уже там) или\n"
    "    прислать его файлом — программа умеет с ним работать, см. инструкцию."
)


def use_system_certificates() -> bool:
    """Сверять сертификаты с хранилищем операционной системы.

    Возвращает False, если библиотека недоступна — тогда остаётся обычная
    проверка по встроенному списку.
    """
    try:
        import truststore

        truststore.inject_into_ssl()
        return True
    except Exception:
        return False


def is_certificate_error(error: BaseException) -> bool:
    """Это именно проблема с сертификатом, а не просто нет интернета?"""
    text = str(error).lower()
    return "certificate" in text or "certificate_verify_failed" in text


def system_ca_bundle(folder: Path) -> str | None:
    """Файл со всеми доверенными корневыми сертификатами этого компьютера.

    Нужен библиотекам, которые не умеют смотреть в хранилище Windows сами
    (вход в инстаграм идёт через curl со своим списком сертификатов). Туда
    попадают: обычный общий список, сертификаты из хранилища Windows (в том
    числе корпоративный) и файл организации, если его положили рядом с
    программой. Проверка сертификатов при этом остаётся включённой.
    """
    parts: list[str] = []
    try:
        import certifi

        parts.append(Path(certifi.where()).read_text(encoding="ascii", errors="ignore"))
    except Exception:
        pass
    if sys.platform.startswith("win"):
        for store in ("ROOT", "CA"):
            try:
                for cert, encoding, _trust in ssl.enum_certificates(store):  # type: ignore[attr-defined]
                    if encoding == "x509_asn":
                        parts.append(ssl.DER_cert_to_PEM_cert(cert))
            except Exception:
                continue
    for variable in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"):
        extra = os.environ.get(variable)
        if extra and Path(extra).is_file():
            try:
                parts.append(Path(extra).read_text(encoding="ascii", errors="ignore"))
            except Exception:
                pass
    if not parts:
        return None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "ca-bundle.pem"
        path.write_text("\n".join(parts), encoding="ascii", errors="ignore")
        return str(path)
    except Exception:
        return None
