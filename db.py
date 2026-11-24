"""SQLite-слой: aiosqlite + WAL, один общий коннект.

Дисциплина: одиночные записи идут через _run() (сразу commit),
многошаговые транзакции (BEGIN IMMEDIATE ... COMMIT) открывает только
guards.py под глобальным asyncio.Lock — гонок и «transaction within
transaction» не бывает.
"""
import json
import random
import time

import aiosqlite

from config import DB_PATH
from db_costs import (
    BANK_ACCRUAL_CAP_HOURS,
    BANK_RATE_PER_HOUR,
    MARKET_ITEMS,
    MARKET_PRICE_MAX,
    MARKET_PRICE_MIN,
    MARKET_UPDATE_SEC,
    MINE_ENERGY_MAX,
    MINE_ENERGY_REGEN_SEC,
)

_conn: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY,
    full_name     TEXT    NOT NULL DEFAULT '',
    username      TEXT    NOT NULL DEFAULT '',
    balance       REAL    NOT NULL DEFAULT 0,
    bank          REAL    NOT NULL DEFAULT 0,
    bank_updated  REAL    NOT NULL DEFAULT 0,
    objects       TEXT    NOT NULL DEFAULT '{}',
    materials     TEXT    NOT NULL DEFAULT '{}',
    holdings      TEXT    NOT NULL DEFAULT '{}',
    potions       TEXT    NOT NULL DEFAULT '{}',
    mine_level    INTEGER NOT NULL DEFAULT 1,
    energy        REAL    NOT NULL DEFAULT 100,
    energy_ts     REAL    NOT NULL DEFAULT 0,
    games_won     INTEGER NOT NULL DEFAULT 0,
    games_lost    INTEGER NOT NULL DEFAULT 0,
    rob_ok        INTEGER NOT NULL DEFAULT 0,
    rob_fail      INTEGER NOT NULL DEFAULT 0,
    word_wins     INTEGER NOT NULL DEFAULT 0,
    messages      INTEGER NOT NULL DEFAULT 0,
    total_earned  REAL    NOT NULL DEFAULT 0,
    banned        INTEGER NOT NULL DEFAULT 0,
    created_at    REAL    NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cooldowns (
    user_id INTEGER NOT NULL,
    action  TEXT    NOT NULL,
    until   REAL    NOT NULL,
    PRIMARY KEY (user_id, action)
);
CREATE TABLE IF NOT EXISTS effects (
    user_id INTEGER NOT NULL,
    effect  TEXT    NOT NULL,
    until   REAL    NOT NULL,
    PRIMARY KEY (user_id, effect)
);
CREATE TABLE IF NOT EXISTS market (
    item     TEXT PRIMARY KEY,
    price    REAL NOT NULL,
    prev     REAL NOT NULL,
    updated  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS word_rounds (
    chat_id  INTEGER PRIMARY KEY,
    word     TEXT NOT NULL,
    reward   REAL NOT NULL,
    until    REAL NOT NULL,
    active   INTEGER NOT NULL DEFAULT 0,
    last_end REAL NOT NULL DEFAULT 0
);
"""

JSON_FIELDS = ("objects", "materials", "holdings", "potions")


async def init() -> None:
    global _conn
    _conn = await aiosqlite.connect(DB_PATH)
    _conn.row_factory = aiosqlite.Row
    await _conn.execute("PRAGMA journal_mode=WAL")
    await _conn.execute("PRAGMA synchronous=NORMAL")
    await _conn.execute("PRAGMA busy_timeout=5000")
    await _conn.commit()
    await _conn.executescript(SCHEMA)


async def close() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None


# ---------- низкоуровневые помощники ----------

async def _run(sql: str, params: tuple = ()) -> None:
    """Одиночная запись с немедленным commit."""
    await _conn.execute(sql, params)
    await _conn.commit()


async def _exec(sql: str, params: tuple = ()):
    """Выполнить без commit (для транзакций в guards.py)."""
    return await _conn.execute(sql, params)


async def _one(sql: str, params: tuple = ()):
    cur = await _conn.execute(sql, params)
    row = await cur.fetchone()
    await cur.close()
    return row


async def _all(sql: str, params: tuple = ()):
    cur = await _conn.execute(sql, params)
    rows = await cur.fetchall()
    await cur.close()
    return rows


def _d(row) -> dict | None:
    return {k: row[k] for k in row.keys()} if row is not None else None


# ---------- пользователи ----------

async def ensure_user(user_id: int, full_name: str, username: str) -> None:
    await _run(
        "INSERT INTO users (user_id, full_name, username, created_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET full_name = excluded.full_name, "
        "username = excluded.username",
        (user_id, full_name or "", (username or "").lower(), time.time()),
    )


async def update_names(user_id: int, full_name: str, username: str) -> None:
    await _run(
        "UPDATE users SET full_name = ?, username = ? WHERE user_id = ?",
        (full_name or "", (username or "").lower(), user_id),
    )


async def get_user(user_id: int) -> dict | None:
    return _d(await _one("SELECT * FROM users WHERE user_id = ?", (user_id,)))


async def find_by_username(username: str) -> dict | None:
    return _d(await _one(
        "SELECT * FROM users WHERE username = ? ORDER BY user_id LIMIT 1",
        ((username or "").lower(),),
    ))


async def set_balance(user_id: int, value: float) -> None:
    from config import MAX_BALANCE
    v = max(0.0, min(float(value), MAX_BALANCE))
    await _run("UPDATE users SET balance = ? WHERE user_id = ?", (v, user_id))


async def add_earned(user_id: int, amount: float) -> None:
    await _run("UPDATE users SET total_earned = total_earned + ? WHERE user_id = ?",
               (max(0.0, float(amount)), user_id))


async def bump_messages(user_id: int) -> None:
    await _run("UPDATE users SET messages = messages + 1 WHERE user_id = ?", (user_id,))


async def bump_games(user_id: int, won: bool) -> None:
    if won:
        await _run("UPDATE users SET games_won = games_won + 1 WHERE user_id = ?", (user_id,))
    else:
        await _run("UPDATE users SET games_lost = games_lost + 1 WHERE user_id = ?", (user_id,))


async def bump_rob(user_id: int, success: bool) -> None:
    if success:
        await _run("UPDATE users SET rob_ok = rob_ok + 1 WHERE user_id = ?", (user_id,))
    else:
        await _run("UPDATE users SET rob_fail = rob_fail + 1 WHERE user_id = ?", (user_id,))


async def bump_word_win(user_id: int, reward: float) -> None:
    await _run(
        "UPDATE users SET word_wins = word_wins + 1, total_earned = total_earned + ? "
        "WHERE user_id = ?",
        (max(0.0, float(reward)), user_id),
    )


async def set_mine_level(user_id: int, level: int) -> None:
    await _run("UPDATE users SET mine_level = ? WHERE user_id = ?", (int(level), user_id))


async def set_ban(user_id: int, banned: bool) -> None:
    await _run("UPDATE users SET banned = ? WHERE user_id = ?", (1 if banned else 0, user_id))


async def reset_user(user_id: int) -> None:
    await _run("DELETE FROM users WHERE user_id = ?", (user_id,))
    await _run("DELETE FROM cooldowns WHERE user_id = ?", (user_id,))
    await _run("DELETE FROM effects WHERE user_id = ?", (user_id,))


async def all_user_ids() -> list[int]:
    rows = await _all("SELECT user_id FROM users")
    return [r["user_id"] for r in rows]


# ---------- JSON-поля инвентаря ----------

def get_dict(user: dict, field: str) -> dict:
    """Разобрать JSON-поле профиля (objects/materials/holdings/potions)."""
    if field not in JSON_FIELDS:
        raise ValueError(f"bad json field: {field}")
    raw = user.get(field, "{}")
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


async def set_json_field(user_id: int, field: str, data: dict, commit: bool = True) -> None:
    """Записать JSON-поле. commit=False — внутри внешней транзакции (guards.py)."""
    if field not in JSON_FIELDS:
        raise ValueError(f"bad json field: {field}")
    sql = f"UPDATE users SET {field} = ? WHERE user_id = ?"
    params = (json.dumps(data, ensure_ascii=False), user_id)
    if commit:
        await _run(sql, params)
    else:
        await _exec(sql, params)


async def add_materials(user_id: int, gains: dict) -> None:
    """Начислить материалы: {'железо_2': 3, ...}."""
    if not gains:
        return
    row = await get_user(user_id)
    if row is None:
        return
    mats = get_dict(row, "materials")
    for key, qty in gains.items():
        mats[key] = mats.get(key, 0) + qty
    await set_json_field(user_id, "materials", mats)


# ---------- кулдауны ----------

async def cooldown_remaining(user_id: int, action: str) -> float:
    row = await _one("SELECT until FROM cooldowns WHERE user_id = ? AND action = ?",
                     (user_id, action))
    if row is None:
        return 0.0
    return max(0.0, row["until"] - time.time())


async def set_cooldown(user_id: int, action: str, duration: float) -> None:
    await _run(
        "INSERT INTO cooldowns (user_id, action, until) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, action) DO UPDATE SET until = excluded.until",
        (user_id, action, time.time() + duration),
    )


async def clear_all_cooldowns(user_id: int) -> None:
    await _run("DELETE FROM cooldowns WHERE user_id = ?", (user_id,))


# ---------- эффекты (зелья) ----------

async def set_effect(user_id: int, effect: str, duration: float) -> float:
    until = time.time() + duration
    await _run(
        "INSERT INTO effects (user_id, effect, until) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, effect) DO UPDATE SET until = excluded.until",
        (user_id, effect, until),
    )
    return until


async def has_effect(user_id: int, effect: str) -> bool:
    row = await _one("SELECT until FROM effects WHERE user_id = ? AND effect = ?",
                     (user_id, effect))
    return row is not None and row["until"] > time.time()


async def active_effects(user_id: int) -> list[dict]:
    rows = await _all("SELECT effect, until FROM effects WHERE user_id = ? AND until > ?",
                      (user_id, time.time()))
    return [_d(r) for r in rows]


async def clear_all_effects(user_id: int) -> None:
    await _run("DELETE FROM effects WHERE user_id = ?", (user_id,))


# ---------- энергия шахты ----------

async def refresh_energy(user_id: int) -> tuple[dict | None, float]:
    """Лениво восстановить энергию и вернуть (профиль, энергия)."""
    row = await get_user(user_id)
    if row is None:
        return None, 0.0
    now = time.time()
    gained = max(0.0, (now - row["energy_ts"]) / MINE_ENERGY_REGEN_SEC)
    energy = min(MINE_ENERGY_MAX, max(0.0, row["energy"]) + gained)
    if abs(energy - row["energy"]) > 1e-9:
        await _run("UPDATE users SET energy = ?, energy_ts = ? WHERE user_id = ?",
                   (energy, now, user_id))
        row["energy"] = energy
    return row, energy


async def dig_energy(user_id: int) -> None:
    """Списать энергию за копку (после refresh_energy)."""
    from db_costs import MINE_DIG_COST
    await _run(
        "UPDATE users SET energy = max(0, energy - ?), energy_ts = ? WHERE user_id = ?",
        (MINE_DIG_COST, time.time(), user_id),
    )


async def refill_energy(user_id: int) -> None:
    await _run("UPDATE users SET energy = ?, energy_ts = ? WHERE user_id = ?",
               (MINE_ENERGY_MAX, time.time(), user_id))


# ---------- банк ----------

async def bank_refresh(user_id: int) -> dict | None:
    """Лениво начислить проценты (3%/час, копятся максимум за сутки) и вернуть профиль."""
    row = await get_user(user_id)
    if row is None:
        return None
    now = time.time()
    bank = row["bank"]
    updated = row["bank_updated"]
    if bank > 0 and updated > 0:
        elapsed = now - updated
        if elapsed >= 60:
            effective = min(elapsed, BANK_ACCRUAL_CAP_HOURS * 3600)
            interest = bank * BANK_RATE_PER_HOUR * effective / 3600.0
            from config import MAX_BALANCE
            bank = min(bank + interest, MAX_BALANCE)
            await _run("UPDATE users SET bank = ?, bank_updated = ? WHERE user_id = ?",
                       (bank, now, user_id))
            row["bank"] = bank
    elif updated == 0:
        await _run("UPDATE users SET bank_updated = ? WHERE user_id = ?", (now, user_id))
        row["bank_updated"] = now
    return row


# ---------- рынок ----------

async def get_prices() -> tuple[dict, dict]:
    """Ленивое обновление котировок случайным блужданием.

    Возвращает (цены, прошлые_цены): {'биткоин': 61000.0}, ...
    """
    now = time.time()
    rows = {r["item"]: r for r in await _all("SELECT * FROM market")}
    prices: dict = {}
    prevs: dict = {}
    for item_id, _name, _emoji, base, vol in MARKET_ITEMS:
        row = rows.get(item_id)
        if row is None:
            await _run(
                "INSERT INTO market (item, price, prev, updated) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(item) DO NOTHING",
                (item_id, base, base, now),
            )
            prices[item_id] = base
            prevs[item_id] = base
            continue
        price = row["price"]
        prevs[item_id] = row["prev"]
        if now - row["updated"] >= MARKET_UPDATE_SEC:
            steps = min(20, int((now - row["updated"]) // MARKET_UPDATE_SEC))
            for _ in range(steps):
                price *= 1.0 + random.uniform(-vol, vol)
            price = max(base * MARKET_PRICE_MIN, min(price, base * MARKET_PRICE_MAX))
            await _run("UPDATE market SET price = ?, prev = ?, updated = ? WHERE item = ?",
                       (price, row["price"], now, item_id))
            prevs[item_id] = row["price"]
        prices[item_id] = price
    return prices, prevs


# ---------- ловец слов ----------

async def get_round(chat_id: int) -> dict | None:
    return _d(await _one("SELECT * FROM word_rounds WHERE chat_id = ?", (chat_id,)))


async def start_round(chat_id: int, word: str, reward: float, duration: float) -> None:
    await _run(
        "INSERT INTO word_rounds (chat_id, word, reward, until, active, last_end) "
        "VALUES (?, ?, ?, ?, 1, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET word = excluded.word, reward = excluded.reward, "
        "until = excluded.until, active = 1",
        (chat_id, word, reward, time.time() + duration, time.time()),
    )


async def end_round(chat_id: int) -> None:
    await _run(
        "UPDATE word_rounds SET active = 0, word = '', last_end = ? WHERE chat_id = ?",
        (time.time(), chat_id),
    )


# ---------- статистика и топы ----------

async def global_stats() -> dict:
    row = await _one(
        "SELECT COUNT(*) AS users, "
        "COALESCE(SUM(balance), 0) AS balances, "
        "COALESCE(SUM(bank), 0) AS banks, "
        "COALESCE(SUM(messages), 0) AS messages, "
        "COALESCE(SUM(word_wins), 0) AS words, "
        "COALESCE(SUM(banned), 0) AS banned "
        "FROM users"
    )
    return _d(row)


async def top_rich(limit: int = 10) -> list[dict]:
    rows = await _all(
        "SELECT full_name, username, balance, bank FROM users "
        "WHERE banned = 0 AND (balance + bank) > 0 "
        "ORDER BY (balance + bank) DESC LIMIT ?",
        (limit,),
    )
    return [_d(r) for r in rows]


async def top_words(limit: int = 10) -> list[dict]:
    rows = await _all(
        "SELECT full_name, username, word_wins FROM users "
        "WHERE word_wins > 0 ORDER BY word_wins DESC LIMIT ?",
        (limit,),
    )
    return [_d(r) for r in rows]
