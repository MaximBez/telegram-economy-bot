"""Сундуки: пять уровней удачи, джекпоты, множественное открытие."""
import random

from aiogram import Router
from aiogram.types import Message

import db
import guards
from db_costs import (
    CHESTS,
    CHEST_OPEN_MAX,
    MATERIALS,
    POTIONS,
    material_label,
    match_dict,
)
from filters import Cmd, args_of
from formatters import esc, fmt, parse_qty

router = Router(name="chests")

_POT_BY_ID = {p[0]: (p[1], p[2]) for p in POTIONS}


def _open_one(cfg: dict) -> dict:
    """Разыграть содержимое одного сундука."""
    r = random.random()
    res = {"money": 0.0, "jackpot": False, "mats": {}, "potions": {}}
    jp = cfg["jackpot_chance"]
    mc = cfg["money_chance"]
    mac = cfg["mats_chance"]
    pc = cfg["potion_chance"]
    if r < jp:
        res["money"] = random.uniform(*cfg["money"]) * cfg["jackpot_mult"]
        res["jackpot"] = True
    elif r < jp + mc:
        res["money"] = random.uniform(*cfg["money"])
    elif r < jp + mc + mac:
        qty = random.randint(*cfg["mats_qty"])
        tier = random.randint(*cfg["tiers"])
        mid, *_rest = random.choice(MATERIALS)
        res["mats"][f"{mid}_{tier}"] = qty
    elif r < jp + mc + mac + pc:
        res["potions"][random.choice(cfg["potions"])] = 1
    else:
        res["money"] = random.uniform(*cfg["money"]) * 0.5  # утешительный приз
    return res


def _match_chest(query: str):
    q = (query or "").strip().lower()
    if q.isdigit():
        idx = int(q)
        if 1 <= idx <= len(CHESTS):
            return CHESTS[idx - 1]
        return None
    entry, _ = match_dict(q, CHESTS)
    return entry


@router.message(Cmd("сундук", "сундуки", "chest"))
async def chests(message: Message, user: dict):
    args = args_of(message)
    if not args:
        lines = [
            f"{i + 1}. {c['emoji']} <b>{esc(c['name'])}</b> — {fmt(c['price'])}"
            f" (джекпот ×{c['jackpot_mult']} с шансом {int(c['jackpot_chance'] * 100)}%)"
            for i, c in enumerate(CHESTS)
        ]
        await message.reply(
            "🎁 <b>Сундуки</b>\n\n"
            + "\n".join(lines)
            + "\n\n➡️ Открыть: <code>сундук редкий 5</code> (до 50 за раз)\n"
            "Внутри: деньги, материалы, зелья и ДЖЕКПОТЫ."
        )
        return
    cfg = _match_chest(args[0])
    if cfg is None:
        await message.reply(
            "❌ Сундуки: " + ", ".join(f"{c['emoji']} {c['id']}" for c in CHESTS)
        )
        return
    qty = 1
    if len(args) > 1:
        raw = args[1].lower()
        if raw in ("всё", "все", "all"):
            row0 = await db.get_user(user["user_id"])
            qty = max(0, min(CHEST_OPEN_MAX, int(row0["balance"] // cfg["price"])))
            if qty < 1:
                await message.reply(
                    f"❌ На «всё» хватает только на {int(row0['balance'] // cfg['price'])} шт — "
                    f"минимум нужен 1 ({fmt(cfg['price'])})."
                )
                return
        else:
            qty = parse_qty(args[1])
            if qty is None or qty < 1:
                await message.reply("❌ Количество — целое число 1–50.")
                return
    qty = min(qty, CHEST_OPEN_MAX)

    total_cost = cfg["price"] * qty
    if user["balance"] < total_cost:
        await message.reply(
            f"❌ Нужно <b>{fmt(total_cost)}</b> ({cfg['emoji']} ×{qty}), "
            f"у тебя {fmt(user['balance'])}."
        )
        return
    if not await guards.spend(user["user_id"], total_cost):
        await message.reply("❌ Баланс изменился, попробуй ещё раз.")
        return

    money_total = 0.0
    jackpots = 0
    mats_total: dict = {}
    potions_total: dict = {}
    results = [_open_one(cfg) for _ in range(qty)]
    for res in results:
        money_total += res["money"]
        if res["jackpot"]:
            jackpots += 1
        for k, v in res["mats"].items():
            mats_total[k] = mats_total.get(k, 0) + v
        for k, v in res["potions"].items():
            potions_total[k] = potions_total.get(k, 0) + v

    new_bal = await guards.add_money(user["user_id"], money_total)
    if mats_total:
        await db.add_materials(user["user_id"], mats_total)
    if potions_total:
        row = await db.get_user(user["user_id"])
        owned = db.get_dict(row, "potions")
        for k, v in potions_total.items():
            owned[k] = owned.get(k, 0) + v
        await db.set_json_field(user["user_id"], "potions", owned)
    await db.add_earned(user["user_id"], money_total)

    parts = [f"{cfg['emoji']} <b>{esc(cfg['name'])}</b> ×{qty} за {fmt(total_cost)}"]
    if money_total > 0:
        jp_note = f" 💥×{jackpots} ДЖЕКПОТ" if jackpots else ""
        parts.append(f"💰 Деньги: <b>+{fmt(money_total)}</b>{jp_note}")
    if mats_total:
        parts.append("📦 Материалы: " + ", ".join(f"{material_label(k)} ×{v}" for k, v in mats_total.items()))
    if potions_total:
        parts.append("🧪 Зелья: " + ", ".join(
            f"{_POT_BY_ID[k][1]} {esc(_POT_BY_ID[k][0])} ×{v}"
            for k, v in potions_total.items() if k in _POT_BY_ID
        ))
    if money_total <= 0 and not mats_total and not potions_total:
        parts.append("🕳 Пусто... бывает и так.")
    parts.append(f"💰 Баланс: {fmt(new_bal)}")
    await message.reply("\n".join(parts))
