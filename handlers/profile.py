"""Профиль: /start с меню-клавиатурой, баланс, полный профиль."""
import time
from datetime import datetime

from aiogram import Router
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

import db
from db_costs import (
    BANK_RATE_PER_HOUR,
    MINE_ENERGY_MAX,
    OBJECTS,
)
from filters import Cmd
from formatters import esc, fmt, fmt_time

router = Router(name="profile")

_EFFECT_LABELS = {
    "luck": "🍀 удача",
    "rob": "💪 сила",
    "mine": "⛏ шахтёр",
    "shield": "🛡 щит",
}

MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Баланс"), KeyboardButton(text="Профиль")],
        [KeyboardButton(text="Шахта"), KeyboardButton(text="Магазин")],
        [KeyboardButton(text="Объекты"), KeyboardButton(text="Собрать")],
        [KeyboardButton(text="Рынок"), KeyboardButton(text="Помощь")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выбери действие или напиши команду...",
)


@router.message(Cmd("старт", "start"))
async def start(message: Message, user: dict):
    name = esc(message.from_user.first_name if message.from_user else "игрок")
    await message.reply(
        f"👋 Привет, <b>{name}</b>!\n\n"
        "🤑 Добро пожаловать в <b>экономическую империю</b>!\n"
        "Здесь ты начинаешь с нуля: копишь миллионы в шахте, скупаешь объекты, "
        "торгуешь на рынке, варишь зелья и грабишь соседей.\n\n"
        "🚀 <b>С чего начать:</b>\n"
        "1️⃣ <code>копать</code> — первые деньги и материалы\n"
        "2️⃣ <code>купить киоск</code> — пассивный доход\n"
        "3️⃣ <code>объекты</code> и <code>помощь</code> — все команды\n\n"
        "💵 Стартовый капитал уже на балансе!",
        reply_markup=MENU,
    )
    row = await db.get_user(user["user_id"])
    if row is not None and row["balance"] <= 0:
        await db.set_balance(user["user_id"], 100_000)


@router.message(Cmd("баланс", "balance", "деньги"))
async def balance(message: Message, user: dict):
    row = await db.bank_refresh(user["user_id"])
    if row is None:
        return
    await message.reply(
        "💰 <b>Твои деньги</b>\n\n"
        f"💵 Наличные: <b>{fmt(row['balance'])}</b>\n"
        f"🏦 В банке: <b>{fmt(row['bank'])}</b> (+{int(BANK_RATE_PER_HOUR * 100)}%/ч)\n"
        f"🏆 Заработано всего: {fmt(row['total_earned'])}"
    )


@router.message(Cmd("профиль", "profile", "проф", "me"))
async def profile(message: Message, user: dict):
    uid = user["user_id"]
    row, energy = await db.refresh_energy(uid)
    if row is None:
        return
    row = await db.bank_refresh(uid)

    objects_data = db.get_dict(row, "objects")
    obj_count = 0
    obj_income = 0.0
    for slot in objects_data.values():
        if isinstance(slot, dict):
            obj_count += int(slot.get("count", 0))
    for obj_id, _n, _e, _p, income in OBJECTS:
        slot = objects_data.get(obj_id)
        if isinstance(slot, dict):
            obj_income += income * int(slot.get("count", 0))

    materials = db.get_dict(row, "materials")
    holdings = db.get_dict(row, "holdings")
    potions = db.get_dict(row, "potions")
    inv_n = sum(int(v) for v in materials.values()) \
        + sum(1 for _k, v in holdings.items() if v > 0) \
        + sum(int(v) for v in potions.values())

    effects = await db.active_effects(uid)
    now = time.time()
    eff_lines = [
        f"  {_EFFECT_LABELS.get(e['effect'], e['effect'])} — ещё {fmt_time(e['until'] - now)}"
        for e in effects
    ]

    reg = datetime.fromtimestamp(row["created_at"]).strftime("%d.%m.%Y") if row["created_at"] else "—"
    await message.reply(
        f"👤 <b>{esc(row['full_name'])}</b>"
        + (f" (@{esc(row['username'])})" if row["username"] else "")
        + "\n\n"
        f"💵 Баланс: <b>{fmt(row['balance'])}</b>\n"
        f"🏦 Банк: <b>{fmt(row['bank'])}</b> (+{int(BANK_RATE_PER_HOUR * 100)}%/ч)\n"
        f"⛏ Шахта: <b>{row['mine_level']} ур.</b> (⚡ {int(energy)}/{MINE_ENERGY_MAX})\n"
        f"🏢 Объекты: <b>{obj_count}</b> — доход {fmt(obj_income)}/ч\n"
        f"🎒 Инвентарь: {inv_n} шт.\n\n"
        "🎯 <b>Статистика</b>\n"
        f"🎲 Игры: {row['games_won']} побед / {row['games_lost']} поражений\n"
        f"🕵️ Ограбления: {row['rob_ok']} успешных / {row['rob_fail']} провалов\n"
        f"🔤 Слов разгадано: {row['word_wins']}\n"
        f"💬 Сообщений: {row['messages']}\n"
        f"🏆 Заработано всего: <b>{fmt(row['total_earned'])}</b>\n"
        + ("✨ <b>Эффекты</b>\n" + "\n".join(eff_lines) + "\n" if eff_lines else "")
        + f"\n📅 В игре с {reg}"
    )
