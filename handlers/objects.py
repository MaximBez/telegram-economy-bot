"""Объекты (бизнесы): список, покупка, продажа, сбор дохода."""
import time

from aiogram import Router
from aiogram.types import Message

import db
import guards
from config import MAX_BALANCE
from db_costs import (
    OBJECTS,
    OBJECT_ACCUM_CAP_SEC,
    OBJECT_GROWTH,
    MAX_OBJECTS_PER_BUY,
    match_entry,
    max_affordable_objects,
    object_price,
    object_sell_price,
)
from filters import Cmd, args_of
from formatters import esc, fmt, parse_qty

router = Router(name="objects")

_OBJ_BY_ID = {o[0]: o for o in OBJECTS}
_OBJECT_WORDS = ("объект", "объекты", "бизнес", "бизнесы")

USAGE_BUY = "➡️ Купить: <code>купить кафе 3</code> или <code>купить объект 1 5</code>"
USAGE_SELL = "➡️ Продать: <code>продать кафе 2</code> (50% цены последнего купленного)"


def _match_object(query: str):
    q = (query or "").strip().lower()
    if q.isdigit():
        idx = int(q)
        if 1 <= idx <= len(OBJECTS):
            return OBJECTS[idx - 1]
        return None
    entry, _variants = match_entry(q, OBJECTS)
    return entry


async def _is_object_buy(message: Message) -> bool:
    args = args_of(message)
    if not args:
        return False
    a0 = args[0].lower()
    return a0 in _OBJECT_WORDS or _match_object(a0) is not None


async def _is_object_sell(message: Message) -> bool:
    args = args_of(message)
    if not args:
        return False
    a0 = args[0].lower()
    return a0 in _OBJECT_WORDS or a0 == "объекта" or _match_object(a0) is not None


@router.message(Cmd("объекты", "objects"))
async def list_objects(message: Message, user: dict):
    owned_data = db.get_dict(user, "objects")
    now = time.time()
    total_income = 0.0
    owned_lines = []
    avail_lines = []
    for obj_id, name, emoji, base_price, income in OBJECTS:
        slot = owned_data.get(obj_id)
        count = int(slot.get("count", 0)) if isinstance(slot, dict) else 0
        price = object_price(base_price, count)
        if count > 0:
            last = float(slot.get("last", now))
            pending = min(max(0.0, now - last), OBJECT_ACCUM_CAP_SEC) / 3600.0 * income * count
            total_income += income * count
            owned_lines.append(
                f"{emoji} {esc(name)} ×{count} — {fmt(income * count)}/ч (ждёт: {fmt(pending)})"
            )
        avail_lines.append(f"  {emoji} {esc(name)} — {fmt(price)} → {fmt(income)}/ч")
    text = (
        "🏢 <b>Твои объекты</b>\n"
        + ("\n".join(owned_lines) if owned_lines else "  (пока ничего — купи первый!)")
        + f"\n\n💵 Суммарный доход: <b>{fmt(total_income)}/ч</b>\n"
        + "⏳ Доход копится до 24 часов, забирать: <code>собрать</code>\n\n"
        "🛒 <b>Доступные объекты</b> (цена следующего):\n"
        + "\n".join(avail_lines)
        + "\n\n" + USAGE_BUY
    )
    await message.reply(text)


@router.message(Cmd("купить"), _is_object_buy)
async def buy_object(message: Message, user: dict):
    args = args_of(message)
    rest = args[1:] if args and args[0].lower() in _OBJECT_WORDS else args
    if not rest:
        await message.reply(USAGE_BUY)
        return
    entry = _match_object(rest[0])
    if entry is None:
        await message.reply("❌ Объект не найден. Посмотри список: <code>объекты</code>")
        return
    obj_id, name, emoji, base_price, income = entry
    owned_data = db.get_dict(user, "objects")
    slot = owned_data.get(obj_id) if isinstance(owned_data.get(obj_id), dict) else {}
    count = int(slot.get("count", 0))
    balance = user["balance"]
    qty_raw = rest[1] if len(rest) > 1 else "1"

    if qty_raw.lower() in ("всё", "все", "all"):
        qty = max_affordable_objects(base_price, count, balance)
        if qty <= 0:
            await message.reply(
                f"❌ Не хватает денег даже на 1 «{esc(name)}» "
                f"({fmt(object_price(base_price, count))})."
            )
            return
    else:
        qty = parse_qty(qty_raw)
        if qty is None:
            await message.reply("❌ Количество — целое число: <code>купить кафе 5</code>")
            return
        qty = min(qty, MAX_OBJECTS_PER_BUY)

    total = 0
    price = object_price(base_price, count)
    for _ in range(qty):
        total += price
        price = int(price * OBJECT_GROWTH)
        if total >= MAX_BALANCE:
            total = MAX_BALANCE
            break
    if balance < total:
        max_n = max_affordable_objects(base_price, count, balance)
        await message.reply(
            f"❌ Нужно <b>{fmt(total)}</b>, у тебя {fmt(balance)}.\n"
            f"На твои деньги можно купить: {max_n} шт."
        )
        return
    if not await guards.spend(user["user_id"], total):
        await message.reply("❌ Не удалось списать деньги (баланс изменился). Попробуй ещё раз.")
        return

    slot["count"] = count + qty
    slot.setdefault("last", time.time())
    owned_data[obj_id] = slot
    await db.set_json_field(user["user_id"], "objects", owned_data)

    new_count = count + qty
    await message.reply(
        f"{emoji} Куплено: <b>{esc(name)}</b> ×{qty} за {fmt(total)}\n"
        f"📦 Всего у тебя: {new_count} | доход: {fmt(income * new_count)}/ч\n"
        f"💰 Следующий стоит: {fmt(object_price(base_price, new_count))}"
    )


@router.message(Cmd("продать"), _is_object_sell)
async def sell_object(message: Message, user: dict):
    args = args_of(message)
    rest = args[1:] if args and args[0].lower() in (_OBJECT_WORDS + ("объекта",)) else args
    if not rest:
        await message.reply(USAGE_SELL)
        return
    entry = _match_object(rest[0])
    if entry is None:
        await message.reply("❌ Объект не найден. Список: <code>объекты</code>")
        return
    obj_id, name, emoji, base_price, _income = entry
    owned_data = db.get_dict(user, "objects")
    slot = owned_data.get(obj_id) if isinstance(owned_data.get(obj_id), dict) else {}
    count = int(slot.get("count", 0))
    if count <= 0:
        await message.reply(f"❌ У тебя нет «{esc(name)}».")
        return
    qty_raw = rest[1] if len(rest) > 1 else "1"
    if qty_raw.lower() in ("всё", "все", "all"):
        qty = count
    else:
        qty = parse_qty(qty_raw)
        if qty is None:
            await message.reply("❌ Количество — целое число: <code>продать кафе 2</code>")
            return
        qty = min(qty, count)

    proceeds = 0
    for i in range(qty):
        proceeds += object_sell_price(base_price, count - i)
    new_count = count - qty
    if new_count > 0:
        slot["count"] = new_count
        owned_data[obj_id] = slot
    else:
        owned_data.pop(obj_id, None)
    await db.set_json_field(user["user_id"], "objects", owned_data)
    new_bal = await guards.add_money(user["user_id"], proceeds)
    await message.reply(
        f"{emoji} Продано: <b>{esc(name)}</b> ×{qty} за <b>+{fmt(proceeds)}</b>\n"
        f"📦 Осталось: {new_count} | Баланс: {fmt(new_bal)}"
    )


@router.message(Cmd("собрать", "collect"))
async def collect(message: Message, user: dict):
    now = time.time()
    owned_data = db.get_dict(user, "objects")
    if not owned_data:
        await message.reply("🏢 У тебя нет объектов. Купи первый — <code>объекты</code>")
        return
    total = 0.0
    lines = []
    cleaned = {}
    for obj_id, slot in owned_data.items():
        entry = _OBJ_BY_ID.get(obj_id)
        if entry is None or not isinstance(slot, dict):
            continue
        cleaned[obj_id] = slot
        _oid, name, emoji, _base, income = entry
        count = int(slot.get("count", 0))
        last = float(slot.get("last", now))
        elapsed = min(max(0.0, now - last), OBJECT_ACCUM_CAP_SEC)
        money = income * count * elapsed / 3600.0
        if money <= 0:
            continue
        total += money
        slot["last"] = now
        lines.append(f"{emoji} {esc(name)} ×{count} — +{fmt(money)}")
    if total <= 0:
        await message.reply("💤 Доход ещё не накопился. Заходи чуть позже!")
        return
    await db.set_json_field(user["user_id"], "objects", cleaned)
    new_bal = await guards.add_money(user["user_id"], total)
    await db.add_earned(user["user_id"], total)
    extra = f"\n…и ещё {len(lines) - 15} объектов" if len(lines) > 15 else ""
    await message.reply(
        "💼 <b>Сбор дохода</b>\n"
        + "\n".join(lines[:15]) + extra
        + f"\n\n💰 Итого: <b>+{fmt(total)}</b>\n"
        f"Баланс: {fmt(new_bal)}"
    )
