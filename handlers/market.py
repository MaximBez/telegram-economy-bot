"""Магазин материалов с тирами, крипто-рынок, склад."""
import math

from aiogram import Router
from aiogram.types import Message

import db
import guards
from config import MAX_BALANCE
from db_costs import (
    MARKET_ITEMS,
    MARKET_QTY_MIN,
    MATERIALS,
    MATERIAL_TIERS,
    POTIONS,
    SELL_RATE,
    material_label,
    material_price,
    match_entry,
)
from filters import Cmd, args_of
from formatters import esc, fmt, parse_amount, parse_qty

router = Router(name="market")

_WORDS_ALL = ("всё", "все", "all")


def _match_material(query: str):
    entry, _ = match_entry(query, MATERIALS)
    return entry


def _match_market(query: str):
    entry, _ = match_entry(query, MARKET_ITEMS)
    return entry


async def _is_item(message: Message) -> bool:
    """Материал или рыночный актив (объекты ловит роутер objects раньше)."""
    args = args_of(message)
    if not args:
        return False
    q = args[0].lower()
    return _match_material(q) is not None or _match_market(q) is not None


def _variants_text(entries) -> str:
    names = [f"{e[2]} {e[1]}" for e in entries[:8]]
    return "Уточни, что именно: " + ", ".join(names)


# ==================== МАГАЗИН ====================

@router.message(Cmd("магазин", "shop"))
async def shop(message: Message, user: dict):
    lines = []
    for mid, name, emoji, base in MATERIALS:
        lines.append(
            f"{emoji} <b>{esc(name)}</b> — Т1: {fmt(base)} … "
            f"Т{MATERIAL_TIERS}: {fmt(material_price(base, MATERIAL_TIERS))}"
        )
    await message.reply(
        "🛒 <b>Магазин материалов</b>\n"
        "Цена тира t = базовая × 12^(t−1). Материалы нужны для зелий и улучшения шахты.\n\n"
        + "\n".join(lines)
        + "\n\n➡️ Покупка: <code>купить железо 2 10</code> (тир 2, 10 шт)\n"
        "➡️ Продажа магазину за 60%: <code>продать железо всё</code>\n\n"
        "🌐 Живой рынок с котировками: <code>рынок</code>"
    )


# ==================== РЫНОК ====================

@router.message(Cmd("рынок", "market", "котировки"))
async def market_view(message: Message, user: dict):
    prices, prevs = await db.get_prices()
    lines = []
    for item_id, name, emoji, _base, _vol in MARKET_ITEMS:
        p = prices[item_id]
        prev = prevs.get(item_id, p)
        arrow = "📈" if p > prev else ("📉" if p < prev else "➖")
        pct = (p / prev - 1.0) * 100 if prev else 0.0
        lines.append(f"{emoji} <b>{esc(name)}</b> — {fmt(p)} {arrow} ({pct:+.1f}%)")
    await message.reply(
        "🌐 <b>Рынок</b> — котировки меняются каждые 5 минут\n\n"
        + "\n".join(lines)
        + "\n\n➡️ <code>купить биткоин 0.5</code> | <code>продать биткоин всё</code>\n"
        "💡 Классика: купил на спаде — продал на пике."
    )


# ==================== КУПИТЬ ====================

@router.message(Cmd("купить"), _is_item)
async def buy(message: Message, user: dict):
    args = args_of(message)
    item_q = args[0]
    nums = args[1:]

    # --- материалы с тирами ---
    mat = _match_material(item_q)
    if mat is not None:
        mid, name, emoji, base = mat
        tier, qty = 1, None
        if len(nums) >= 2:
            tier = parse_qty(nums[0])
            qty = parse_qty(nums[1])
            if tier is None or not (1 <= tier <= MATERIAL_TIERS):
                await message.reply(
                    f"❌ Тир материала — число 1–{MATERIAL_TIERS}: "
                    "<code>купить железо 2 10</code>"
                )
                return
        elif len(nums) == 1:
            qty = parse_qty(nums[0])
        if qty is None or qty < 1:
            await message.reply("❌ Количество — целое число ≥ 1.")
            return
        qty = min(qty, 1_000_000)
        price = material_price(base, tier)
        cost = price * qty
        if user["balance"] < cost:
            await message.reply(
                f"❌ Нужно <b>{fmt(cost)}</b> ({emoji} {esc(name)} Т{tier} ×{qty} "
                f"по {fmt(price)}), у тебя {fmt(user['balance'])}."
            )
            return
        if not await guards.spend(user["user_id"], cost):
            await message.reply("❌ Баланс изменился, попробуй ещё раз.")
            return
        await db.add_materials(user["user_id"], {f"{mid}_{tier}": qty})
        await message.reply(
            f"✅ Куплено: {material_label(f'{mid}_{tier}')} ×{qty} за {fmt(cost)}\n"
            f"💰 Баланс: {fmt(user['balance'] - cost)}"
        )
        return

    # --- рыночные активы ---
    item = _match_market(item_q)
    if item is None:
        return
    item_id, name, emoji, _base, _vol = item
    prices, _prevs = await db.get_prices()
    price = prices[item_id]
    balance = user["balance"]
    qty_raw = nums[0] if nums else None
    if qty_raw is None:
        await message.reply(
            f"❌ Сколько {esc(name)} купить? <code>купить {item_id} 2</code> или "
            "<code>купить " + item_id + " всё</code>"
        )
        return
    if qty_raw.lower() in _WORDS_ALL:
        if balance < price:
            await message.reply(f"❌ На 1 шт ({fmt(price)}) денег не хватает: у тебя {fmt(balance)}.")
            return
        qty = math.floor((balance / price) * 10000) / 10000.0
    else:
        qty = parse_amount(qty_raw)
    if qty is None or qty < MARKET_QTY_MIN:
        await message.reply(f"❌ Количество от {MARKET_QTY_MIN} (можно дробное: 0.5).")
        return
    qty = min(qty, MAX_BALANCE / max(price, 1e-9))
    cost = qty * price
    if cost > balance + 1e-9:
        max_qty = math.floor((balance / price) * 10000) / 10000.0
        await message.reply(
            f"❌ Нужно <b>{fmt(cost)}</b>, у тебя {fmt(balance)}.\n"
            f"Максимум на твои деньги: {max_qty} шт."
        )
        return
    if not await guards.spend(user["user_id"], cost):
        await message.reply("❌ Баланс изменился, попробуй ещё раз.")
        return
    row = await db.get_user(user["user_id"])
    holdings = db.get_dict(row, "holdings")
    holdings[item_id] = holdings.get(item_id, 0.0) + qty
    await db.set_json_field(user["user_id"], "holdings", holdings)
    await message.reply(
        f"✅ Куплено: {emoji} <b>{esc(name)}</b> ×{qty} по {fmt(price)} за {fmt(cost)}\n"
        f"💰 Баланс: {fmt(row['balance'] - cost)}\n"
        f"📦 В портфеле: {holdings[item_id]} шт. | Продать: <code>продать {item_id} всё</code>"
    )


# ==================== ПРОДАТЬ ====================

@router.message(Cmd("продать"), _is_item)
async def sell(message: Message, user: dict):
    args = args_of(message)
    item_q = args[0]
    nums = args[1:]

    # --- материалы ---
    mat = _match_material(item_q)
    if mat is not None:
        mid, name, emoji, base = mat
        row = await db.get_user(user["user_id"])
        mats = db.get_dict(row, "materials")
        # «продать железо всё» — все тиры сразу
        if nums and nums[0].lower() in _WORDS_ALL:
            total_gain = 0.0
            sold_lines = []
            for tier in range(1, MATERIAL_TIERS + 1):
                key = f"{mid}_{tier}"
                qty = int(mats.get(key, 0))
                if qty <= 0:
                    continue
                gain = qty * material_price(base, tier) * SELL_RATE
                total_gain += gain
                mats.pop(key, None)
                sold_lines.append(f"  {material_label(key)} ×{qty} → +{fmt(gain)}")
            if not sold_lines:
                await message.reply(f"❌ У тебя нет {emoji} {esc(name)} ни одного тира.")
                return
            await db.set_json_field(user["user_id"], "materials", mats)
            new_bal = await guards.add_money(user["user_id"], total_gain)
            await db.add_earned(user["user_id"], total_gain)
            await message.reply(
                f"✅ Продано магазину за 60%:\n" + "\n".join(sold_lines)
                + f"\n\n💰 Итого: <b>+{fmt(total_gain)}</b> | Баланс: {fmt(new_bal)}"
            )
            return
        tier, qty = 1, None
        if len(nums) >= 2:
            tier = parse_qty(nums[0])
            qty = parse_qty(nums[1])
            if tier is None or not (1 <= tier <= MATERIAL_TIERS):
                await message.reply(f"❌ Тир — число 1–{MATERIAL_TIERS}.")
                return
        elif len(nums) == 1:
            qty = parse_qty(nums[0])
        if qty is None or qty < 1:
            await message.reply("❌ Количество — целое число ≥ 1.")
            return
        key = f"{mid}_{tier}"
        have_qty = int(mats.get(key, 0))
        if have_qty <= 0:
            await message.reply(f"❌ У тебя нет {material_label(key)}.")
            return
        qty = min(qty, have_qty)
        gain = qty * material_price(base, tier) * SELL_RATE
        left = have_qty - qty
        if left > 0:
            mats[key] = left
        else:
            mats.pop(key, None)
        await db.set_json_field(user["user_id"], "materials", mats)
        new_bal = await guards.add_money(user["user_id"], gain)
        await db.add_earned(user["user_id"], gain)
        await message.reply(
            f"✅ Продано: {material_label(key)} ×{qty} → <b>+{fmt(gain)}</b> (60% цены)\n"
            f"💰 Баланс: {fmt(new_bal)}"
        )
        return

    # --- рыночные активы ---
    item = _match_market(item_q)
    if item is None:
        return
    item_id, name, emoji, _base, _vol = item
    row = await db.get_user(user["user_id"])
    holdings = db.get_dict(row, "holdings")
    held = holdings.get(item_id, 0.0)
    if held <= 0:
        await message.reply(f"❌ В портфеле нет {emoji} {esc(name)}. Купи: <code>купить {item_id} 1</code>")
        return
    qty_raw = nums[0] if nums else None
    if qty_raw is None:
        await message.reply(f"❌ Сколько продать? <code>продать {item_id} 0.5</code> или <code>продать {item_id} всё</code>")
        return
    if qty_raw.lower() in _WORDS_ALL:
        qty = held
    else:
        qty = parse_amount(qty_raw)
    if qty is None or qty <= 0:
        await message.reply("❌ Не понял количество.")
        return
    qty = min(qty, held)
    prices, _prevs = await db.get_prices()
    price = prices[item_id]
    gain = qty * price
    left = held - qty
    if left > 1e-9:
        holdings[item_id] = left
    else:
        holdings.pop(item_id, None)
    await db.set_json_field(user["user_id"], "holdings", holdings)
    new_bal = await guards.add_money(user["user_id"], gain)
    await db.add_earned(user["user_id"], gain)
    await message.reply(
        f"✅ Продано: {emoji} <b>{esc(name)}</b> ×{qty} по {fmt(price)} → <b>+{fmt(gain)}</b>\n"
        f"📦 Осталось в портфеле: {left if left > 1e-9 else 0} шт.\n"
        f"💰 Баланс: {fmt(new_bal)}"
    )


# ==================== СКЛАД ====================

@router.message(Cmd("склад", "inv", "inventory"))
async def inventory(message: Message, user: dict):
    row = await db.get_user(user["user_id"])
    if row is None:
        return
    mats = db.get_dict(row, "materials")
    holdings = db.get_dict(row, "holdings")
    potions = db.get_dict(row, "potions")

    mat_lines = [f"  {material_label(k)} ×{int(v)}" for k, v in sorted(mats.items()) if v > 0]
    hold_lines = []
    if holdings:
        prices, _ = await db.get_prices()
        for item_id, name, emoji, _b, _v in MARKET_ITEMS:
            qty = holdings.get(item_id, 0.0)
            if qty > 0:
                hold_lines.append(f"  {emoji} {esc(name)} ×{qty} (~{fmt(prices[item_id] * qty)})")
    pot_lines = []
    if potions:
        pot_by_id = {p[0]: p for p in POTIONS}
        for pid, qty in potions.items():
            if qty > 0 and pid in pot_by_id:
                pot_lines.append(f"  {pot_by_id[pid][2]} {esc(pot_by_id[pid][1])} ×{int(qty)}")

    text = "🎒 <b>Склад</b>\n\n"
    text += "🔧 <b>Материалы:</b>\n" + ("\n".join(mat_lines) if mat_lines else "  (пусто — копай в шахте)")
    text += "\n\n📊 <b>Портфель активов:</b>\n" + ("\n".join(hold_lines) if hold_lines else "  (пусто — смотри рынок)")
    text += "\n\n🧪 <b>Зелья:</b>\n" + ("\n".join(pot_lines) if pot_lines else "  (пусто — свари: зелья)")
    await message.reply(text)
