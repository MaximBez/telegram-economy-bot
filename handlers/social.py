"""Социальное: ограбление, переводы, банк, топы + справка /помощь."""
import random

from aiogram import Router
from aiogram.types import Message

import db
import guards
from config import is_admin
from db_costs import (
    BANK_ACCRUAL_CAP_HOURS,
    BANK_MIN_DEPOSIT,
    BANK_RATE_PER_HOUR,
    ROB_BASE_CHANCE,
    ROB_COOLDOWN,
    ROB_FINE_MAX,
    ROB_FINE_MIN,
    ROB_FINE_RATE,
    ROB_STEAL_MIN,
    ROB_STEAL_RATE,
    ROB_STRENGTH_BONUS,
    ROB_TARGET_MIN_BALANCE,
    TRANSFER_MIN,
)
from filters import Cmd, args_of
from formatters import esc, fmt, fmt_time, parse_amount

router = Router(name="social")

HELP_TEXT = (
    "📖 <b>Команды бота</b>\n\n"

    "🧭 <b>Основное</b>\n"
    "/start — регистрация и меню\n"
    "/баланс — деньги и банк\n"
    "/профиль — полная статистика\n"
    "/склад — материалы, активы, зелья\n"
    "/топ — топ богачей (топ слова — топ ловцов)\n\n"

    "🏢 <b>Объекты</b>\n"
    "/объекты — список и накопленный доход\n"
    "купить <название> [кол-во] — купить объект\n"
    "продать <название> [кол-во] — продать за 50%\n"
    "собрать — забрать доход со всех объектов\n\n"

    "⛏ <b>Шахта</b>\n"
    "/шахта — уровень, энергия, улучшение\n"
    "копать — добыча денег и материалов\n"
    "улучшить шахту — апгрейд (нужны материалы)\n\n"

    "🛒 <b>Магазин и рынок</b>\n"
    "/магазин — материалы с тирами 1–5\n"
    "/рынок — котировки (обновление раз в 5 мин)\n"
    "купить <товар> [тир] [кол-во] — покупка\n"
    "продать <товар> [тир] [кол-во|всё] — продажа\n\n"

    "🧪 <b>Зелья</b>\n"
    "/зелья — рецепты и запасы\n"
    "сварить <зелье> [1–20] — варка\n"
    "пить <зелье> — употребить\n\n"

    "🎁 <b>Сундуки</b>\n"
    "/сундук — список сундуков\n"
    "сундук <название|номер> [1–50] — открыть\n\n"

    "🎲 <b>Игры</b>\n"
    "монетка <ставка> — орёл или решка\n"
    "кубик <ставка> — бросок против бота\n"
    "казино <ставка> — слоты (джекпоты ×11/×33/×77)\n"
    "рулетка <ставка> <красное|чёрное|зеро>\n\n"

    "🕵️ <b>Улица</b>\n"
    "грабить (reply или @user) — кулдаун 3 часа\n"
    "перевести (reply или @user) <сумма>\n"
    "банк [положить|снять] <сумма> — +3% в час\n\n"

    "🔢 <b>Форматы сумм</b>: 10к, 2.5млн, 3трлн, 1квнт, 2e18, 50%, всё"
)


@router.message(Cmd("помощь", "help", "команды"))
async def help_cmd(message: Message, user: dict):
    await message.reply(HELP_TEXT)


# ==================== ОГРАБЛЕНИЕ ====================

@router.message(Cmd("грабить", "rob"))
async def rob(message: Message, user: dict):
    args = args_of(message)
    token = args[0] if args else None
    target = await guards.resolve_target(message, token)
    if target is None:
        await message.reply(
            "❌ Кого грабить? Ответь (reply) на сообщение жертвы или укажи @username/ID."
        )
        return
    uid = user["user_id"]
    tid = target["user_id"]
    if tid == uid:
        await message.reply("🤨 Грабить самого себя — это уже философия.")
        return
    if is_admin(tid):
        await message.reply("👮 Админов грабить нельзя.")
        return
    if target["banned"]:
        await message.reply("🚫 Эта цель забанена.")
        return

    remaining = await db.cooldown_remaining(uid, "rob")
    if remaining > 0:
        await message.reply(f"⏳ Ты недавно грабил. Следующий заход через {fmt_time(remaining)}.")
        return

    async with guards.user_lock(uid):
        remaining = await db.cooldown_remaining(uid, "rob")  # двойная проверка под локом
        if remaining > 0:
            await message.reply(f"⏳ Ты недавно грабил. Ещё {fmt_time(remaining)}.")
            return
        trow = await db.get_user(tid)
        if trow is None:
            await message.reply("❌ Цель ещё не регистрировалась в боте.")
            return
        if await db.has_effect(tid, "shield"):
            await db.set_cooldown(uid, "rob", ROB_COOLDOWN)
            await message.reply(
                f"🛡 У {esc(trow['full_name'])} щит! Попытка провалилась без штрафа, "
                f"но кулдаун 3 ч пошёл."
            )
            return
        if trow["balance"] < ROB_TARGET_MIN_BALANCE:
            await message.reply("💰 У цели слишком мало денег — жаль на него время.")
            return

        chance = ROB_BASE_CHANCE
        if await db.has_effect(uid, "rob"):
            chance += ROB_STRENGTH_BONUS
        await db.set_cooldown(uid, "rob", ROB_COOLDOWN)
        success = random.random() < chance

        if success:
            steal = max(ROB_STEAL_MIN, trow["balance"] * ROB_STEAL_RATE)
            steal = min(steal, trow["balance"])
            if not await guards.transfer_money(tid, uid, steal):
                await message.reply("💸 Цель успела спрятать деньги. Попытка не удалась.")
                return
            await db.bump_rob(uid, True)
            await message.reply(
                f"🕵️ <b>Успех!</b> Ты ограбил {esc(trow['full_name'])} на "
                f"<b>+{fmt(steal)}</b>!\n"
                f"⏳ Следующее ограбление через 3 ч."
            )
        else:
            fine = user["balance"] * ROB_FINE_RATE
            fine = min(max(fine, ROB_FINE_MIN), ROB_FINE_MAX)
            fine = min(fine, user["balance"])
            await guards.spend(uid, fine)
            compensation = fine * 0.5
            if compensation > 0:
                await guards.add_money(tid, compensation)
            await db.bump_rob(uid, False)
            await message.reply(
                f"🚨 <b>Тебя поймали за руку!</b> Штраф: <b>-{fmt(fine)}</b>, "
                f"{esc(trow['full_name'])} получил {fmt(compensation)} компенсации.\n"
                f"⏳ Следующее ограбление через 3 ч."
            )


# ==================== ПЕРЕВОДЫ ====================

@router.message(Cmd("перевести", "перевод", "transfer", "pay"))
async def transfer(message: Message, user: dict):
    args = args_of(message)
    reply = message.reply_to_message
    if reply is not None and reply.from_user is not None and not reply.from_user.is_bot:
        target = await guards.resolve_target(message, None)
        amount_raw = args[0] if args else None
    else:
        target = await guards.resolve_target(message, args[0] if args else None)
        amount_raw = args[1] if len(args) > 1 else None
    if target is None:
        await message.reply(
            "❌ Кому переводить? Ответь (reply) на сообщение игрока или укажи @username/ID "
            "и сумму: <code>перевести @user 10к</code>"
        )
        return
    uid = user["user_id"]
    tid = target["user_id"]
    if tid == uid:
        await message.reply("🤨 Перевод самому себе бессмыслен.")
        return
    amount = parse_amount(amount_raw, ref=user["balance"]) if amount_raw else None
    if amount is None or amount < TRANSFER_MIN:
        await message.reply(f"❌ Минимальная сумма перевода: {fmt(TRANSFER_MIN)}.")
        return
    if amount > user["balance"]:
        await message.reply(f"❌ Не хватает денег: у тебя {fmt(user['balance'])}.")
        return
    if target["banned"]:
        await message.reply("🚫 Получатель забанен.")
        return
    if await guards.transfer_money(uid, tid, amount):
        trow = await db.get_user(tid)
        await message.reply(
            f"💸 <b>{esc(user['full_name'])}</b> → <b>{esc(target['full_name'])}</b>: "
            f"<b>{fmt(amount)}</b>\n"
            f"💰 Твой баланс: {fmt(await _balance(uid))}"
        )
        try:
            await message.bot.send_message(
                tid,
                f"💸 Тебе перевели <b>{fmt(amount)}</b> от "
                f"{esc(user['full_name'])}!\n"
                f"💰 Баланс: {fmt(trow['balance'] if trow else 0)}",
            )
        except Exception:
            pass
    else:
        await message.reply("❌ Перевод не прошёл (баланс изменился). Попробуй ещё раз.")


async def _balance(uid: int) -> float:
    row = await db.get_user(uid)
    return row["balance"] if row else 0.0


# ==================== БАНК ====================

@router.message(Cmd("банк", "bank"))
async def bank(message: Message, user: dict):
    uid = user["user_id"]
    args = args_of(message)
    row = await db.bank_refresh(uid)
    if row is None:
        return
    if not args:
        hour_income = row["bank"] * BANK_RATE_PER_HOUR
        await message.reply(
            "🏦 <b>Банк</b> — +3% в час\n\n"
            f"💰 Наличные: {fmt(row['balance'])}\n"
            f"🏦 На счету: <b>{fmt(row['bank'])}</b>\n"
            f"📈 Начисление: ~{fmt(hour_income)}/ч\n\n"
            "➡️ <code>банк положить 1млн</code> | <code>банк положить всё</code>\n"
            "➡️ <code>банк снять 500к</code> | <code>банк снять всё</code>"
        )
        return
    sub = args[0].lower()
    if sub in ("положить", "deposit", "пополнить"):
        raw = args[1] if len(args) > 1 else None
        amount = parse_amount(raw, ref=row["balance"]) if raw else None
        if amount is None or amount < BANK_MIN_DEPOSIT:
            await message.reply(f"❌ Минимальный вклад: {fmt(BANK_MIN_DEPOSIT)}.")
            return
        if amount > row["balance"]:
            await message.reply(f"❌ Не хватает наличных: у тебя {fmt(row['balance'])}.")
            return
        new_bank = await guards.bank_deposit(uid, amount)
        if new_bank is None:
            await message.reply("❌ Не удалось (баланс изменился). Попробуй ещё раз.")
            return
        await message.reply(
            f"🏦 Внесено: <b>{fmt(amount)}</b> под {int(BANK_RATE_PER_HOUR * 100)}%/ч\n"
            f"🏦 На счету: {fmt(new_bank)} | 💰 Наличные: {fmt(row['balance'] - amount)}"
        )
    elif sub in ("снять", "withdraw"):
        raw = args[1] if len(args) > 1 else None
        amount = parse_amount(raw, ref=row["bank"]) if raw else None
        if amount is None or amount <= 0:
            await message.reply("❌ Сколько снять? <code>банк снять 100к</code> или <code>банк снять всё</code>")
            return
        amount = min(amount, row["bank"])
        if amount <= 0:
            await message.reply("🏦 Счёт пуст.")
            return
        new_bank = await guards.bank_withdraw(uid, amount)
        if new_bank is None:
            await message.reply("❌ Не удалось (счёт изменился). Попробуй ещё раз.")
            return
        await message.reply(
            f"🏦 Снято: <b>{fmt(amount)}</b>\n"
            f"🏦 Остаток: {fmt(new_bank)}"
        )
    else:
        await message.reply("❌ Подкоманды: положить / снять.")


# ==================== ТОПЫ ====================

@router.message(Cmd("топ", "top"))
async def top(message: Message, user: dict):
    args = args_of(message)
    medals = ("🥇", "🥈", "🥉")
    if args and args[0].lower() in ("слов", "слова", "словам", "words"):
        rows = await db.top_words()
        title = "🔤 <b>Топ ловцов слов</b>"
        lines = []
        for i, r in enumerate(rows):
            m = medals[i] if i < 3 else f"{i + 1}."
            lines.append(f"{m} {esc(r['full_name'])} — {r['word_wins']} слов")
    else:
        rows = await db.top_rich()
        title = "💰 <b>Топ богачей</b>"
        lines = []
        for i, r in enumerate(rows):
            m = medals[i] if i < 3 else f"{i + 1}."
            total = r["balance"] + r["bank"]
            lines.append(f"{m} {esc(r['full_name'])} — {fmt(total)}")
    if not lines:
        await message.reply("📭 Пока некого показывать — будь первым!")
        return
    await message.reply(title + "\n\n" + "\n".join(lines))
