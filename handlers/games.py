"""Игры: монетка, кубик, казино (слоты), рулетка. Зелье удачи повышает шансы."""
import random

from aiogram import Router
from aiogram.types import Message

import db
import guards
from db_costs import (
    LUCK_COIN_WIN,
    LUCK_SAVE,
    MAX_BET,
    MIN_BET,
    PAIR_MULT,
    PAYOUT3,
    ROULETTE_RED,
    SYMBOLS,
)
from filters import Cmd, args_of
from formatters import esc, fmt, parse_amount

router = Router(name="games")


def _take_bet(message: Message, user: dict) -> tuple[float | None, str]:
    args = args_of(message)
    if not args:
        return None, (
            "❌ Укажи ставку: <code>монетка 1000</code>\n"
            "Форматы: 10к, 2.5млн, 1трлн, 50%, всё"
        )
    bet = parse_amount(args[0], ref=user["balance"])
    if bet is None:
        return None, "❌ Не понял сумму. Примеры: 1000, 10к, 2.5млн, 50%, всё"
    if bet < MIN_BET:
        return None, f"❌ Минимальная ставка: {fmt(MIN_BET)}."
    if bet > MAX_BET:
        bet = MAX_BET
    if bet > user["balance"]:
        return None, f"❌ Не хватает денег: у тебя {fmt(user['balance'])}."
    return bet, ""


async def _finish(message: Message, user: dict, bet: float, payout: float, won: bool | None):
    """Выплата, статистика, вывод баланса."""
    new_bal = await guards.settle_bet(user["user_id"], bet, payout)
    if new_bal is None:
        await message.reply("❌ Не хватило денег на ставку (баланс изменился).")
        return None
    if won is True:
        await db.bump_games(user["user_id"], True)
        await db.add_earned(user["user_id"], payout - bet)
    elif won is False:
        await db.bump_games(user["user_id"], False)
    return new_bal


@router.message(Cmd("монетка", "coin", "coinflip"))
async def coin(message: Message, user: dict):
    bet, err = _take_bet(message, user)
    if bet is None:
        await message.reply(err)
        return
    luck = await db.has_effect(user["user_id"], "luck")
    win = random.random() < (LUCK_COIN_WIN if luck else 0.5)
    side = random.choice(("Орёл 🦅", "Решка 🪙"))
    payout = bet * 2 if win else 0.0
    new_bal = await _finish(message, user, bet, payout, win)
    if new_bal is None:
        return
    if win:
        await message.reply(
            f"🪙 {side} — <b>ты выиграл +{fmt(bet)}</b>!\n"
            f"💰 Баланс: {fmt(new_bal)}"
        )
    else:
        await message.reply(f"🪙 {side} — не повезло: <b>-{fmt(bet)}</b>\n💰 Баланс: {fmt(new_bal)}")


@router.message(Cmd("кубик", "dice"))
async def dice(message: Message, user: dict):
    bet, err = _take_bet(message, user)
    if bet is None:
        await message.reply(err)
        return
    luck = await db.has_effect(user["user_id"], "luck")
    me = random.randint(1, 6)
    bot_roll = random.randint(1, 6)
    if me > bot_roll:
        payout, won = bet * 2, True
        outcome = "🎉 Ты выиграл"
    elif me < bot_roll:
        payout, won = 0.0, False
        outcome = "😤 Ты проиграл"
    elif luck:
        payout, won = bet * 2, True  # удача: ничья — победа
        outcome = "🍀 Ничья, но удача на твоей стороне — победа!"
    else:
        payout, won = bet, None  # ничья — возврат ставки
        outcome = "🤝 Ничья — ставка возвращена"
    new_bal = await _finish(message, user, bet, payout, won)
    if new_bal is None:
        return
    delta = f"+{fmt(payout - bet)}" if payout > bet else (f"-{fmt(bet)}" if payout == 0 else "без изменений")
    await message.reply(
        f"🎲 Ты: <b>{me}</b> | Бот: <b>{bot_roll}</b>\n"
        f"{outcome} ({delta})\n"
        f"💰 Баланс: {fmt(new_bal)}"
    )


@router.message(Cmd("казино", "слоты", "slots"))
async def slots(message: Message, user: dict):
    bet, err = _take_bet(message, user)
    if bet is None:
        await message.reply(err)
        return
    luck = await db.has_effect(user["user_id"], "luck")
    reels = [random.choice(SYMBOLS) for _ in range(3)]
    display = "".join(reels)
    payout, won = 0.0, False
    special = ""
    if reels[0] == reels[1] == reels[2]:
        mult = PAYOUT3[reels[0]]
        payout = bet * mult
        won = True
        special = f"\n🔥 <b>ДЖЕКПОТ ×{mult}!</b>"
    elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        payout = bet * PAIR_MULT
        won = True
        special = f"\n✨ Пара — ×{PAIR_MULT}"
    elif luck and random.random() < LUCK_SAVE:
        payout = bet  # удача спасла ставку
        special = "\n🍀 Удача вернула ставку!"
    new_bal = await _finish(message, user, bet, payout, won)
    if new_bal is None:
        return
    if payout > bet:
        delta = f"💰 Выигрыш: <b>+{fmt(payout - bet)}</b>"
    elif payout == bet:
        delta = "💰 Ставка возвращена"
    else:
        delta = f"💸 Проигрыш: <b>-{fmt(bet)}</b>"
    await message.reply(
        f"🎰 [{display}]{special}\n{delta}\n💰 Баланс: {fmt(new_bal)}"
    )


@router.message(Cmd("рулетка", "roulette"))
async def roulette(message: Message, user: dict):
    args = args_of(message)
    bet, err = _take_bet(message, user)
    if bet is None:
        await message.reply(err)
        return
    if len(args) < 2:
        await message.reply(
            "❌ Укажи цвет: <code>рулетка 1000 красное</code> / чёрное / зеро "
            "(зеро платит ×36!)"
        )
        return
    color_raw = args[1].lower()
    if color_raw in ("красное", "красный", "красная", "red"):
        color, mult = "red", 2
    elif color_raw in ("чёрное", "черное", "чёрный", "черный", "black"):
        color, mult = "black", 2
    elif color_raw in ("зеро", "зелёное", "зеленое", "green", "zero"):
        color, mult = "zero", 36
    else:
        await message.reply("❌ Цвет: красное / чёрное / зеро.")
        return
    luck = await db.has_effect(user["user_id"], "luck")
    n = random.randint(0, 36)
    if n == 0:
        landed = "зеро"
    elif n in ROULETTE_RED:
        landed = "красное"
    else:
        landed = "чёрное"

    payout, won = 0.0, False
    special = ""
    if landed == color:
        payout = bet * mult
        won = True
    elif luck and random.random() < LUCK_SAVE:
        payout = bet
        special = "\n🍀 Удача вернула ставку!"
    new_bal = await _finish(message, user, bet, payout, won)
    if new_bal is None:
        return
    num_note = f"{n} ({landed})" if n != 0 else "0 (зеро)"
    if payout > bet:
        delta = f"💰 Выигрыш: <b>+{fmt(payout - bet)}</b>"
    elif payout == bet and payout > 0:
        delta = "💰 Ставка возвращена"
    else:
        delta = f"💸 Проигрыш: <b>-{fmt(bet)}</b>"
    await message.reply(
        f"🎡 Шарик остановился на: <b>{num_note}</b>{special}\n"
        f"{delta}\n💰 Баланс: {fmt(new_bal)}"
    )
