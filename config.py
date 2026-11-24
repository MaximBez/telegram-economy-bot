"""Конфигурация бота.

Все настройки читаются из файла .env, который лежит рядом с main.py.
Формат .env:

    BOT_TOKEN=токен_от_BotFather
    ADMIN_IDS=8630082761
    DB_PATH=economy.db
"""
import os
from pathlib import Path

# Абсолютный потолок баланса: защищает float от переполнения (inf/NaN).
MAX_BALANCE = 1e300


def _load_env() -> None:
    """Мини-загрузчик .env без внешних зависимостей.

    Переменные, уже заданные в окружении, не перезаписываются.
    """
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_env()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
DB_PATH: str = os.getenv("DB_PATH", "economy.db").strip() or "economy.db"


def _parse_admin_ids(raw: str) -> list[int]:
    ids: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.lstrip("-").isdigit():
            ids.append(int(chunk))
    return ids


ADMIN_IDS: list[int] = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


if not BOT_TOKEN:
    raise SystemExit(
        "\n[BOT] BOT_TOKEN не найден!\n"
        "Создайте файл .env рядом с main.py:\n\n"
        "    BOT_TOKEN=1234567890:AA...  (токен от @BotFather)\n"
        "    ADMIN_IDS=ваш_telegram_id\n"
    )
