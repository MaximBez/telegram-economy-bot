"""Зелья: рецепты, варка (до 20 за раз), употребление."""
from aiogram import Router
from aiogram.types import Message

import db
import guards
from config import MAX_BALANCE
from db_costs import (
    POTIONS,
    POTION_CRAFT_MAX,
    POTION_RICH_MAX,
    POTION_RICH_MIN,
    material_label,
)
from filters import Cmd, args_of
from formatters import esc, fmt, fmt_time, parse_qty

router = Router(name="potions")

_POT_BY_ID = {p[0]: p for p in POTIONS}


def _match_potion(query: str):
    q = (query or "").strip().lower()
    if q.isdigit():
        idx = int(q)
        if 1 <= idx <= len(POTIONS):
            return POTIONS[idx - 1]
        return None
    for pot in POTIONS:
        if q == pot[0] or q == pot[1].lower():
            return pot
    for pot in POTIONS:  # уникальный префикс
        hits = [p for p in POTIONS if p[1].lower().startswith(q) and len(q) >= 3]
        if len(hits) == 1:
            return hits[0]
        break
    return None


def _recipe_text(pot) -> str:
    _pid, name, emoji, money, mats, _effect, duration, desc = pot
    mat_text = ", ".join(f"{material_label(k)} ×{v}" for k, v in mats.items())
    if duration > 0:
        eff_text = f"{desc} (длится {fmt_time(duration)})"
    else:
        eff_text = desc
    return f"{emoji} <b>{esc(name)}</b> — {fmt(money)} + {mat_text}\n   ✨ {eff_text}"


@router.message(Cmd("зелья", "potions", "зелье"))
async def potions_list(message: Message, user: dict):
    row = await db.get_user(user["user_id"])
    owned = db.get_dict(row, "potions")
    lines = []
    for pot in POTIONS:
        have = int(owned.get(pot[0], 0))
        suffix = f" — <i>в запасе: {have} шт</i>" if have else ""
        lines.append(_recipe_text(pot) + suffix)
    await message.reply(
        "🧪 <b>Алхимия</b>\n\n"
        + "\n\n".join(lines)
        + "\n\n➡️ Сварить: <code>сварить удача 3</code> (максимум 20 за раз)\n"
        "➡️ Выпить: <code>пить удача</code>"
    )


@router.message(Cmd("сварить", "craft"))
async def craft(message: Message, user: dict):
    args = args_of(message)
    if not args:
        await message.reply("❌ Какое зелье сварить? Смотри рецепты: <code>зелья</code>")
        return
    pot = _match_potion(args[0])
    if pot is None:
        await message.reply(
            "❌ Такого зелья нет. Доступны: "
            + ", ".join(f"{p[2]} {p[0]}" for p in POTIONS)
        )
        return
    pid, name, emoji, money, mats, _effect, _duration, _desc = pot
    qty = 1
    if len(args) > 1:
        raw = args[1].lower()
        if raw in ("всё", "все", "all"):
            # максимум по деньгам и материалам
            qty = POTION_CRAFT_MAX
            row0 = await db.get_user(user["user_id"])
            have_m = db.get_dict(row0, "materials")
            for k, v in mats.items():
                qty = min(qty, int(have_m.get(k, 0) // v) if v else 0)
            qty = min(qty, int(row0["balance"] // money) if money else POTION_CRAFT_MAX)
            if qty < 1:
                await message.reply("❌ На «всё» не хватает ресурсов даже на 1 зелье.")
                return
        else:
            qty = parse_qty(args[1])
            if qty is None or qty < 1:
                await message.reply("❌ Количество — целое число от 1 до 20.")
                return
    qty = min(qty, POTION_CRAFT_MAX)

    total_money = money * qty
    total_mats = {k: v * qty for k, v in mats.items()}
    if not await guards.consume_resources(user["user_id"], total_money, total_mats):
        row = await db.get_user(user["user_id"])
        have_m = db.get_dict(row, "materials")
        lines = [f"  💰 {fmt(total_money)} {'✅' if row['balance'] >= total_money else '❌'}"]
        for k, v in total_mats.items():
            have_qty = have_m.get(k, 0)
            lines.append(f"  {material_label(k)}: {int(have_qty)}/{v} {'✅' if have_qty >= v else '❌'}")
        await message.reply(
            f"❌ Не хватает ресурсов на {qty} шт «{esc(name)}»:\n" + "\n".join(lines)
        )
        return
    row = await db.get_user(user["user_id"])
    potions = db.get_dict(row, "potions")
    potions[pid] = potions.get(pid, 0) + qty
    await db.set_json_field(user["user_id"], "potions", potions)
    await message.reply(
        f"{emoji} Сварено: <b>{esc(name)}</b> ×{qty} за {fmt(total_money)} + материалы\n"
        f"🧪 В запасе: {potions[pid]} шт | Пить: <code>пить {pid}</code>"
    )


@router.message(Cmd("пить", "drink"))
async def drink(message: Message, user: dict):
    args = args_of(message)
    if not args:
        await message.reply("❌ Что пить? Смотри запасы: <code>зелья</code>")
        return
    pot = _match_potion(args[0])
    if pot is None:
        await message.reply(
            "❌ Такого зелья нет. Доступны: "
            + ", ".join(f"{p[2]} {p[0]}" for p in POTIONS)
        )
        return
    pid, name, emoji, _money, _mats, effect, duration, desc = pot
    uid = user["user_id"]
    async with guards.user_lock(uid):
        row = await db.get_user(uid)
        potions = db.get_dict(row, "potions")
        if potions.get(pid, 0) < 1:
            await message.reply(f"❌ У тебя нет {emoji} «{esc(name)}». Свари: <code>сварить {pid}</code>")
            return
        potions[pid] -= 1
        if potions[pid] <= 0:
            potions.pop(pid, None)
        await db.set_json_field(uid, "potions", potions)

        if effect == "instant":
            gain = row["balance"] * 0.15
            gain = min(max(gain, POTION_RICH_MIN), POTION_RICH_MAX)
            gain = min(gain, MAX_BALANCE)
            new_bal = await guards.add_money(uid, gain)
            await db.add_earned(uid, gain)
            await message.reply(
                f"{emoji} Эликсир выпит! Мгновенная прибыль: <b>+{fmt(gain)}</b>\n"
                f"💰 Баланс: {fmt(new_bal)}"
            )
        elif effect == "time":
            await db.clear_all_cooldowns(uid)
            await db.refill_energy(uid)
            await message.reply(
                f"{emoji} Время подчинилось тебе! Все кулдауны сброшены, "
                f"энергия шахты полная (⚡)."
            )
        else:
            until = await db.set_effect(uid, effect, duration)
            from datetime import datetime
            hh = datetime.fromtimestamp(until).strftime("%H:%M")
            await message.reply(
                f"{emoji} Выпито: <b>{esc(name)}</b> — {desc}\n"
                f"⏳ Действует до {hh} (через {fmt_time(duration)})"
            )
