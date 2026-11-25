"""Админ-панель: выдача/списание денег, бан, сброс, статистика, рассылка, ловец слов."""
import asyncio
import logging

from aiogram import Router
from aiogram.types import Message

import db
import guards
from config import is_admin
from filters import Cmd, args_of
from formatters import esc, fmt, parse_amount

log = logging.getLogger("bot.admin")
router = Router(name="admin")

USAGE = (
    "👑 <b>Админ-команды</b>\n\n"
    "/админ выдать &lt;id|@user&gt; &lt;сумма&gt; — выдать деньги\n"
    "/админ забрать &lt;id|@user&gt; &lt;сумма&gt; — списать деньги\n"
    "/админ установить &lt;id|@user&gt; &lt;сумма&gt; — задать баланс\n"
    "/админ бан &lt;id|@user&gt; — заблокировать\n"
    "/админ разбан &lt;id|@user&gt; — разблокировать\n"
    "/админ сброс &lt;id|@user&gt; — полный сброс профиля\n"
    "/админ стата — статистика бота\n"
    "/админ слово — запустить Ловца слов в этом чате\n"
    "/админ рассылка &lt;текст&gt; — сообщение всем игрокам\n\n"
    "💡 Можно отвечать командой (reply) на сообщение игрока — цель возьмётся из него."
)


def _is_admin(message: Message) -> bool:
    return message.from_user is not None and is_admin(message.from_user.id)


@router.message(Cmd("админ", "admin"))
async def admin_panel(message: Message):
    if not _is_admin(message):
        return
    parts = args_of(message)
    sub = parts[0].lower() if parts else ""

    if not sub:
        await message.reply(USAGE)
        return

    # ---------- деньги ----------
    if sub in ("выдать", "give"):
        reply = message.reply_to_message
        if reply is not None and reply.from_user is not None and not reply.from_user.is_bot:
            target = await guards.resolve_target(message, None)
            amount_raw = parts[0] if parts else None
        else:
            target = await guards.resolve_target(message, parts[0] if parts else None)
            amount_raw = parts[1] if len(parts) > 1 else None
        amount = parse_amount(amount_raw) if amount_raw else None
        if target is None or amount is None or amount <= 0:
            await message.reply("❌ Формат: /админ выдать <id|@user> <сумма>")
            return
        new_bal = await guards.add_money(target["user_id"], amount)
        await message.reply(
            f"✅ {esc(target['full_name'])}: <b>+{fmt(amount)}</b> → баланс {fmt(new_bal)}"
        )
        return

    if sub in ("забрать", "take"):
        reply = message.reply_to_message
        if reply is not None and reply.from_user is not None and not reply.from_user.is_bot:
            target = await guards.resolve_target(message, None)
            amount_raw = parts[0] if parts else None
        else:
            target = await guards.resolve_target(message, parts[0] if parts else None)
            amount_raw = parts[1] if len(parts) > 1 else None
        amount = parse_amount(amount_raw) if amount_raw else None
        if target is None or amount is None or amount <= 0:
            await message.reply("❌ Формат: /админ забрать <id|@user> <сумма>")
            return
        current = target["balance"]
        removed = min(amount, current)
        await db.set_balance(target["user_id"], current - removed)
        await message.reply(f"✅ {esc(target['full_name'])}: <b>-{fmt(removed)}</b> → баланс {fmt(current - removed)}")
        return

    if sub in ("установить", "set", "setbal"):
        reply = message.reply_to_message
        if reply is not None and reply.from_user is not None and not reply.from_user.is_bot:
            target = await guards.resolve_target(message, None)
            amount_raw = parts[0] if parts else None
        else:
            target = await guards.resolve_target(message, parts[0] if parts else None)
            amount_raw = parts[1] if len(parts) > 1 else None
        amount = parse_amount(amount_raw) if amount_raw else None
        if target is None or amount is None or amount < 0:
            await message.reply("❌ Формат: /админ установить <id|@user> <сумма>")
            return
        await db.set_balance(target["user_id"], amount)
        await message.reply(f"✅ Баланс {esc(target['full_name'])} = <b>{fmt(amount)}</b>")
        return

    # ---------- бан / сброс ----------
    if sub in ("бан", "ban"):
        target = await guards.resolve_target(message, parts[0] if parts else None)
        if target is None:
            await message.reply("❌ Цель не найдена (id, @username или reply).")
            return
        await db.set_ban(target["user_id"], True)
        await message.reply(f"🔨 {esc(target['full_name'])} забанен.")
        return

    if sub in ("разбан", "unban"):
        target = await guards.resolve_target(message, parts[0] if parts else None)
        if target is None:
            await message.reply("❌ Цель не найдена.")
            return
        await db.set_ban(target["user_id"], False)
        await message.reply(f"🕊 {esc(target['full_name'])} разбанен.")
        return

    if sub in ("сброс", "reset"):
        target = await guards.resolve_target(message, parts[0] if parts else None)
        if target is None:
            await message.reply("❌ Цель не найдена.")
            return
        await db.reset_user(target["user_id"])
        await message.reply(f"🗑 Профиль {esc(target['full_name'])} полностью сброшен.")
        return

    # ---------- статистика ----------
    if sub in ("стата", "stats", "статистика"):
        st = await db.global_stats()
        await message.reply(
            "📊 <b>Статистика бота</b>\n\n"
            f"👥 Игроков: <b>{st['users']}</b> (забанено: {st['banned']})\n"
            f"💰 Деньги в руках: <b>{fmt(st['balances'])}</b>\n"
            f"🏦 В банках: <b>{fmt(st['banks'])}</b>\n"
            f"💬 Сообщений: <b>{st['messages']}</b>\n"
            f"🔤 Слов разгадано: <b>{st['words']}</b>"
        )
        return

    # ---------- ловец слов ----------
    if sub in ("слово", "word"):
        from .wordcatch import force_start_round
        await force_start_round(message)
        return

    # ---------- рассылка ----------
    if sub in ("рассылка", "bc", "broadcast"):
        raw = (message.text or "").split(maxsplit=2)
        if len(raw) < 3:
            await message.reply("❌ Формат: /админ рассылка <текст>")
            return
        text = esc(raw[2])
        ids = await db.all_user_ids()
        if not ids:
            await message.reply("👥 Игроков пока нет.")
            return
        status = await message.reply(f"📣 Рассылка запущена: {len(ids)} получателей...")
        sent = 0
        for uid in ids:
            try:
                await message.bot.send_message(uid, f"📣 {text}")
                sent += 1
            except Exception:
                pass
            await asyncio.sleep(0.05)
        await status.edit_text(f"📣 Рассылка завершена: доставлено {sent}/{len(ids)}.")
        return

    await message.reply(USAGE)
