"""Точка входа: запуск Telegram-бота экономической империи.

Запуск: python main.py  (настройки — в файле .env рядом)
"""
import asyncio
import logging

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, Message, Update

import db
from config import ADMIN_IDS, BOT_TOKEN, is_admin
from handlers import build_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("bot")


class EnsureUserMiddleware(BaseMiddleware):
    """Создаёт профиль, обновляет имена и блокирует забаненных."""

    async def __call__(self, handler, event: Message, data: dict):
        u = event.from_user
        if u is None or u.is_bot:
            return
        row = await db.get_user(u.id)
        if row is None:
            await db.ensure_user(u.id, u.full_name, u.username)
            row = await db.get_user(u.id)
        else:
            uname = (u.username or "").lower()
            if row["full_name"] != (u.full_name or "") or row["username"] != uname:
                await db.update_names(u.id, u.full_name or "", uname)
                row = await db.get_user(u.id)
        if row["banned"] and not is_admin(u.id):
            return  # забаненных игнорируем молча
        data["user"] = row
        return await handler(event, data)


async def errors_catcher(event: Update, exception: Exception) -> bool:
    log.exception("Ошибка обработки апдейта: %s", exception)
    msg = getattr(event, "message", None)
    if msg is not None:
        try:
            await msg.answer("⚠️ Что-то сломалось, но мы уже чиним. Попробуй ещё раз!")
        except Exception:
            pass
    return True


COMMANDS = [
    BotCommand(command="start", description="Регистрация и меню"),
    BotCommand(command="balance", description="Баланс (или: баланс)"),
    BotCommand(command="profile", description="Профиль (или: профиль)"),
    BotCommand(command="objects", description="Объекты и доход (или: объекты)"),
    BotCommand(command="mine", description="Шахта (или: шахта)"),
    BotCommand(command="shop", description="Магазин материалов (или: магазин)"),
    BotCommand(command="market", description="Рынок (или: рынок)"),
    BotCommand(command="potions", description="Зелья (или: зелья)"),
    BotCommand(command="chest", description="Сундуки (или: сундук)"),
    BotCommand(command="bank", description="Банк +3%/ч (или: банк)"),
    BotCommand(command="top", description="Топ игроков (или: топ)"),
    BotCommand(command="help", description="Все команды (или: помощь)"),
]


async def main() -> None:
    await db.init()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.message.middleware(EnsureUserMiddleware())
    dp.include_router(build_router())
    dp.errors.register(errors_catcher)

    try:
        await bot.set_my_commands(COMMANDS)
    except Exception as e:
        log.warning("set_my_commands не прошёл: %s", e)

    log.info("Бот запущен. Админы: %s. Потолок баланса: 1e300.", ADMIN_IDS)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")
