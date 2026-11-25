"""Ловец слов: анаграмма появляется в чате, первый угадавший забирает приз.

ВАЖНО: этот роутер включается строго последним — он ловит все сообщения,
не подошедшие ни к одной команде.
"""
import random
import time

from aiogram import Router
from aiogram.types import Message

import db
import guards
from db_costs import WORDS, WORD_CHANCE, WORD_MIN_GAP, WORD_ROUND_TIME
from formatters import esc, fmt, fmt_time

router = Router(name="wordcatch")


async def start_round(chat_id: int, message: Message) -> None:
    word, reward = random.choice(WORDS)
    letters = list(word)
    anagram = word[1:] + word[0]  # запасной вариант (ротация всегда != оригинала)
    for _ in range(25):
        random.shuffle(letters)
        shuffled = "".join(letters)
        if shuffled != word:
            anagram = shuffled
            break
    await db.start_round(chat_id, word, reward, WORD_ROUND_TIME)
    await message.reply(
        "🔤 <b>ЛОВЕЦ СЛОВ!</b>\n"
        "Первым напиши слово из анаграммы:\n\n"
        f"🧩 <b>{esc(anagram.upper())}</b>\n\n"
        f"🎁 Приз: <b>{fmt(reward)}</b> | ⏳ {fmt_time(WORD_ROUND_TIME)}"
    )


async def force_start_round(message: Message) -> None:
    """Запуск раунда по команде /админ слово."""
    await start_round(message.chat.id, message)


@router.message()
async def catch_all(message: Message, user: dict):
    await db.bump_messages(user["user_id"])

    text = (message.text or "").strip()
    if not text:
        return
    low = text.lower()
    chat_id = message.chat.id
    now = time.time()

    rnd = await db.get_round(chat_id)
    if rnd is not None and rnd["active"]:
        if now >= rnd["until"]:
            await db.end_round(chat_id)
            return
        if low == rnd["word"].lower():
            reward = rnd["reward"]
            await db.end_round(chat_id)
            new_bal = await guards.add_money(user["user_id"], reward)
            await db.bump_word_win(user["user_id"], reward)
            await message.reply(
                f"🎉 <b>{esc(user['full_name'])}</b> первым разгадал слово "
                f"«{rnd['word'].upper()}» и забрал <b>+{fmt(reward)}</b>!\n"
                f"💰 Баланс: {fmt(new_bal)}"
            )
        return

    # Не спамим незнакомыми командами в личке
    if low.startswith("/"):
        if message.chat.type == "private":
            await message.reply(
                "🤔 Не знаю такую команду. Все команды: /помощь"
            )
        return

    # Случайный запуск нового раунда (не чаще раза в 10 минут)
    last_end = rnd["last_end"] if rnd is not None else 0.0
    if random.random() < WORD_CHANCE and now - last_end >= WORD_MIN_GAP:
        await start_round(chat_id, message)
