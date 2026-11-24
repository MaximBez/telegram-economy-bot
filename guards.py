"""Защита от гонок и накруток: per-user asyncio.Lock, атомарные транзакции.

Все денежные операции проходят через BEGIN IMMEDIATE под глобальным
asyncio.Lock — двойные клики и параллельные переводы не ломают баланс.
"""
import asyncio

from aiogram.types import Message

import db
from config import MAX_BALANCE

# Лок на каждый профиль: защита от двойного клика (копать, пить, грабить...).
_USER_LOCKS: dict[int, asyncio.Lock] = {}
# Глобальный лок: сериализует многошаговые транзакции BEGIN IMMEDIATE.
_DB_LOCK = asyncio.Lock()


def user_lock(user_id: int) -> asyncio.Lock:
    lock = _USER_LOCKS.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _USER_LOCKS[user_id] = lock
    return lock


def clamp(x) -> float:
    """Число в [0, MAX_BALANCE], без NaN/inf."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0.0
    if x != x or x == float("-inf"):
        return 0.0
    if x == float("inf"):
        return MAX_BALANCE
    return max(0.0, min(x, MAX_BALANCE))


async def _begin() -> None:
    await db._exec("BEGIN IMMEDIATE")


async def _rollback() -> None:
    try:
        await db._exec("ROLLBACK")
    except Exception:
        pass


async def spend(user_id: int, amount: float) -> bool:
    """Атомарно списать деньги. False — не хватает или не удалось."""
    amount = clamp(amount)
    if amount <= 0:
        return False
    async with _DB_LOCK:
        await _begin()
        try:
            row = await db.get_user(user_id)
            if row is None or row["balance"] < amount:
                await _rollback()
                return False
            await db._exec("UPDATE users SET balance = balance - ? WHERE user_id = ?",
                           (amount, user_id))
            await db._exec("COMMIT")
            return True
        except Exception:
            await _rollback()
            raise


async def add_money(user_id: int, amount: float) -> float:
    """Атомарно начислить деньги (с потолком MAX_BALANCE). Возвращает новый баланс."""
    amount = clamp(amount)
    async with _DB_LOCK:
        await _begin()
        try:
            row = await db.get_user(user_id)
            if row is None:
                await _rollback()
                return 0.0
            new_bal = clamp(row["balance"] + amount)
            await db._exec("UPDATE users SET balance = ? WHERE user_id = ?",
                           (new_bal, user_id))
            await db._exec("COMMIT")
            return new_bal
        except Exception:
            await _rollback()
            raise


async def transfer_money(from_id: int, to_id: int, amount: float) -> bool:
    """Атомарный перевод между двумя профилями."""
    amount = clamp(amount)
    if amount <= 0 or from_id == to_id:
        return False
    async with _DB_LOCK:
        await _begin()
        try:
            src = await db.get_user(from_id)
            dst = await db.get_user(to_id)
            if src is None or dst is None or src["balance"] < amount:
                await _rollback()
                return False
            await db._exec("UPDATE users SET balance = balance - ? WHERE user_id = ?",
                           (amount, from_id))
            await db._exec(
                "UPDATE users SET balance = min(balance + ?, ?) WHERE user_id = ?",
                (amount, MAX_BALANCE, to_id),
            )
            await db._exec("COMMIT")
            return True
        except Exception:
            await _rollback()
            raise


async def settle_bet(user_id: int, bet: float, payout: float) -> float | None:
    """Атомарно списать ставку и выплатить payout.

    Возвращает новый баланс или None, если денег на ставку не хватило.
    """
    bet = clamp(bet)
    payout = max(0.0, clamp(payout))
    if bet <= 0:
        return None
    async with _DB_LOCK:
        await _begin()
        try:
            row = await db.get_user(user_id)
            if row is None or row["balance"] < bet:
                await _rollback()
                return None
            new_bal = clamp(row["balance"] - bet + payout)
            await db._exec("UPDATE users SET balance = ? WHERE user_id = ?",
                           (new_bal, user_id))
            await db._exec("COMMIT")
            return new_bal
        except Exception:
            await _rollback()
            raise


async def consume_resources(user_id: int, money_amount: float, mats: dict) -> bool:
    """Атомарно списать деньги И материалы (рецепты зелий, улучшения).

    Если чего-то не хватает — ничего не списывается.
    """
    money_amount = clamp(money_amount)
    mats = {k: float(v) for k, v in (mats or {}).items()}
    async with _DB_LOCK:
        await _begin()
        try:
            row = await db.get_user(user_id)
            if row is None or row["balance"] < money_amount:
                await _rollback()
                return False
            have = db.get_dict(row, "materials")
            for key, qty in mats.items():
                if have.get(key, 0) < qty:
                    await _rollback()
                    return False
            if money_amount > 0:
                await db._exec("UPDATE users SET balance = balance - ? WHERE user_id = ?",
                               (money_amount, user_id))
            for key, qty in mats.items():
                left = have[key] - qty
                if left > 0:
                    have[key] = left
                else:
                    have.pop(key, None)
            await db.set_json_field(user_id, "materials", have, commit=False)
            await db._exec("COMMIT")
            return True
        except Exception:
            await _rollback()
            raise


async def bank_deposit(user_id: int, amount: float) -> float | None:
    """Атомарно положить в банк. Возвращает новый банк или None."""
    amount = clamp(amount)
    if amount <= 0:
        return None
    async with _DB_LOCK:
        await _begin()
        try:
            row = await db.get_user(user_id)
            if row is None or row["balance"] < amount:
                await _rollback()
                return None
            new_bank = clamp(row["bank"] + amount)
            await db._exec("UPDATE users SET balance = balance - ?, bank = ?, "
                           "bank_updated = ? WHERE user_id = ?",
                           (amount, new_bank, await _now(), user_id))
            await db._exec("COMMIT")
            return new_bank
        except Exception:
            await _rollback()
            raise


async def bank_withdraw(user_id: int, amount: float) -> float | None:
    """Атомарно снять из банка. Возвращает новый банк или None."""
    amount = clamp(amount)
    if amount <= 0:
        return None
    async with _DB_LOCK:
        await _begin()
        try:
            row = await db.get_user(user_id)
            if row is None or row["bank"] < amount:
                await _rollback()
                return None
            new_bank = row["bank"] - amount
            await db._exec(
                "UPDATE users SET bank = ?, balance = min(balance + ?, ?), "
                "bank_updated = ? WHERE user_id = ?",
                (new_bank, amount, MAX_BALANCE, await _now(), user_id),
            )
            await db._exec("COMMIT")
            return new_bank
        except Exception:
            await _rollback()
            raise


async def _now() -> float:
    import time
    return time.time()


async def resolve_target(message: Message, token: str | None) -> dict | None:
    """Найти цель: reply-сообщение, @username или числовой ID."""
    reply = message.reply_to_message
    if reply is not None and reply.from_user is not None and not reply.from_user.is_bot:
        u = reply.from_user
        await db.ensure_user(u.id, u.full_name, u.username)
        return await db.get_user(u.id)
    if token:
        tok = token.strip().lstrip("@")
        if tok.isdigit():
            return await db.get_user(int(tok))
        if tok:
            return await db.find_by_username(tok.lower())
    return None
