"""Шахта: копать (энергия), улучшать без предела уровня, статус."""
import random

from aiogram import Router
from aiogram.types import Message

import db
import guards
from db_costs import (
    MATERIALS,
    MINE_DIG_COST,
    MINE_ENERGY_MAX,
    MINE_ENERGY_REGEN_SEC,
    material_label,
    mine_loot_range,
    mine_max_tier,
    mine_mats_rolls,
    mine_upgrade_cost,
    mine_upgrade_mats,
)
from filters import Cmd, args_of
from formatters import esc, fmt, fmt_time

router = Router(name="mines")


@router.message(Cmd("шахта", "mine"))
async def mine_status(message: Message, user: dict):
    row, energy = await db.refresh_energy(user["user_id"])
    if row is None:
        return
    level = row["mine_level"]
    lo, hi = mine_loot_range(level)
    money_cost = mine_upgrade_cost(level)
    mats_need = mine_upgrade_mats(level)
    mats_have = db.get_dict(row, "materials")

    need_lines = []
    can_upgrade = row["balance"] >= money_cost
    for key, qty in mats_need.items():
        have_qty = mats_have.get(key, 0)
        enough = have_qty >= qty
        can_upgrade = can_upgrade and enough
        need_lines.append(
            f"  {material_label(key)}: {int(have_qty)}/{qty} {'✅' if enough else '❌'}"
        )
    await message.reply(
        "⛏ <b>Шахта</b>\n\n"
        f"🪙 Уровень: <b>{level}</b>\n"
        f"⚡ Энергия: <b>{int(energy)}/{MINE_ENERGY_MAX}</b> "
        f"(1⚡ каждые {MINE_ENERGY_REGEN_SEC} сек)\n"
        f"🔨 Копка: {MINE_DIG_COST}⚡ → деньги {fmt(lo)}–{fmt(hi)} + материалы\n"
        f"💎 Тиры материалов: до Т{mine_max_tier(level)}\n\n"
        f"🔧 <b>Улучшение до {level + 1} ур.</b>\n"
        f"  💰 {fmt(money_cost)} {'✅' if row['balance'] >= money_cost else '❌'}\n"
        + "\n".join(need_lines)
        + "\n\n➡️ <code>копать</code> | <code>улучшить шахту</code>"
        + (" | <b>можно улучшать!</b>" if can_upgrade else "")
    )


@router.message(Cmd("копать", "dig"))
async def dig(message: Message, user: dict):
    uid = user["user_id"]
    async with guards.user_lock(uid):
        row, energy = await db.refresh_energy(uid)
        if row is None:
            return
        if energy < MINE_DIG_COST:
            wait = (MINE_DIG_COST - energy) * MINE_ENERGY_REGEN_SEC
            await message.reply(
                f"⚡ Мало энергии: {int(energy)}/{MINE_ENERGY_MAX}.\n"
                f"⏳ Нужная энергия появится через ~{fmt_time(wait)}."
            )
            return
        level = row["mine_level"]
        await db.dig_energy(uid)
        lo, hi = mine_loot_range(level)
        money = random.randint(lo, hi)
        boosted = await db.has_effect(uid, "mine")
        if boosted:
            money *= 2
        gains: dict = {}
        for _ in range(mine_mats_rolls(level)):
            mid, _name, _emoji, _base = random.choice(MATERIALS)
            tier = random.randint(1, mine_max_tier(level))
            key = f"{mid}_{tier}"
            gains[key] = gains.get(key, 0) + random.randint(1, 2)
        new_bal = await guards.add_money(uid, money)
        await db.add_materials(uid, gains)
        await db.add_earned(uid, money)
        gains_text = ", ".join(f"{material_label(k)} ×{v}" for k, v in gains.items())
        await message.reply(
            "⛏ <b>Копаем...</b>\n"
            f"💰 Находка: <b>+{fmt(money)}</b>{' (⏳ ×2 от зелья)' if boosted else ''}\n"
            f"📦 Материалы: {gains_text}\n"
            f"⚡ Энергия: {int(energy) - MINE_DIG_COST}/{MINE_ENERGY_MAX}\n"
            f"💰 Баланс: {fmt(new_bal)}"
        )


@router.message(Cmd("улучшить", "upgrade"))
async def upgrade(message: Message, user: dict):
    uid = user["user_id"]
    async with guards.user_lock(uid):
        row = await db.get_user(uid)
        if row is None:
            return
        level = row["mine_level"]
        money_cost = mine_upgrade_cost(level)
        mats_need = mine_upgrade_mats(level)
        if await guards.consume_resources(uid, money_cost, mats_need):
            await db.set_mine_level(uid, level + 1)
            lo, hi = mine_loot_range(level + 1)
            await message.reply(
                f"🔧 Шахта улучшена: <b>{level} → {level + 1} ур.</b>\n"
                f"💰 Потрачено: {fmt(money_cost)} + материалы\n"
                f"⛏ Новая находка: {fmt(lo)}–{fmt(hi)} за копку\n"
                f"💎 Тиры материалов: до Т{mine_max_tier(level + 1)}"
            )
        else:
            mats_have = db.get_dict(row, "materials")
            need_lines = []
            ok_money = row["balance"] >= money_cost
            need_lines.append(
                f"  💰 {fmt(money_cost)} {'✅' if ok_money else '❌ (есть ' + fmt(row['balance']) + ')'}"
            )
            for key, qty in mats_need.items():
                have_qty = mats_have.get(key, 0)
                need_lines.append(
                    f"  {material_label(key)}: {int(have_qty)}/{qty} {'✅' if have_qty >= qty else '❌'}"
                )
            await message.reply(
                f"❌ Не хватает на улучшение до {level + 1} ур.:\n"
                + "\n".join(need_lines)
                + "\n\nМатериалы копаются в шахте или покупаются в магазине."
            )
