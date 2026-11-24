"""Все игровые константы и балансы экономики.

Правила баланса:
- Экономика щедрая: игрок спокойно доходит до триллионов и квадриллионов.
- Потолок баланса — 1e300 (MAX_BALANCE в config.py), ничего не переполняется.
- Объекты, шахта, материалы — без верхнего предела уровня/количества.
"""

# ==================== ОБЩЕЕ ====================
MIN_BET = 100
MAX_BET = 1e15

# ==================== ОБЪЕКТЫ (пассивный доход) ====================
# (id, название, emoji, базовая цена, доход в час)
OBJECTS = [
    ("kiosk", "Киоск", "🏪", 50_000, 3_000),
    ("cafe", "Кафе", "☕", 250_000, 16_000),
    ("carwash", "Автомойка", "🚗", 1_000_000, 65_000),
    ("bakery", "Пекарня", "🥐", 5_000_000, 330_000),
    ("gym", "Фитнес-клуб", "💪", 25_000_000, 1_700_000),
    ("salon", "Автосалон", "🏎", 150_000_000, 10_000_000),
    ("mall", "Торговый центр", "🏬", 1_000_000_000, 68_000_000),
    ("bizcenter", "Бизнес-центр", "🏢", 10_000_000_000, 700_000_000),
    ("cosmoport", "Космопорт", "🚀", 100_000_000_000, 7_000_000_000),
    ("itcorp", "IT-корпорация", "💻", 1e12, 7e10),
    ("qlab", "Квантовая лаборатория", "⚛️", 1e13, 7e11),
    ("galaxy", "Межгалактический концерн", "🌌", 1e14, 7e12),
    ("moon", "Лунная колония", "🌕", 1e15, 7e13),
    ("blackhole", "Генератор чёрных дыр", "🕳", 1e16, 7e14),
]
OBJECT_GROWTH = 1.12                 # каждый следующий экземпляр дороже на 12%
OBJECT_ACCUM_CAP_SEC = 24 * 3600     # доход копится максимум за 24 часа
OBJECT_SELL_RATE = 0.5               # продажа за 50% цены последнего купленного
MAX_OBJECTS_PER_BUY = 10_000


def object_price(base_price, owned: int) -> int:
    """Цена следующего экземпляра: базовая * 1.12^owned."""
    return int(base_price * (OBJECT_GROWTH ** owned))


def object_sell_price(base_price, owned: int) -> int:
    """Продажа одного экземпляра за 50% цены последнего купленного."""
    if owned <= 0:
        return 0
    return int(base_price * (OBJECT_GROWTH ** (owned - 1)) * OBJECT_SELL_RATE)


def max_affordable_objects(base_price, owned: int, budget: float) -> int:
    """Сколько экземпляров можно купить на budget с учётом роста цены."""
    total = 0.0
    price = float(base_price) * (OBJECT_GROWTH ** max(0, owned))
    n = 0
    while n < MAX_OBJECTS_PER_BUY and total + price <= budget:
        total += price
        price *= OBJECT_GROWTH
        n += 1
    return n


# ==================== МАТЕРИАЛЫ (5 тиров) ====================
# (id, название, emoji, базовая цена за тир 1)
MATERIALS = [
    ("железо", "Железо", "🔩", 150),
    ("медь", "Медь", "🥉", 900),
    ("серебро", "Серебро", "🥈", 7_000),
    ("платина", "Платина", "🥇", 60_000),
    ("кристалл", "Кристалл", "💎", 500_000),
]
MATERIAL_TIERS = 5
TIER_MULT = 12                       # цена тира t = базовая * 12^(t-1)
SELL_RATE = 0.6                      # магазин покупает материалы за 60% цены


def material_price(base_price, tier: int) -> int:
    return int(base_price * (TIER_MULT ** (tier - 1)))


def material_label(key: str) -> str:
    """'железо_2' -> '🔩 Железо Т2'."""
    try:
        mid, tier = key.rsplit("_", 1)
        tier = int(tier)
    except ValueError:
        return key
    for m_id, name, emoji, _base in MATERIALS:
        if m_id == mid:
            return f"{emoji} {name} Т{tier}"
    return key


# ==================== ЗЕЛЬЯ ====================
# (id, название, emoji, цена денег, материалы, эффект, длительность сек, описание)
POTIONS = [
    ("удача", "Зелье удачи", "🍀", 40_000,
     {"медь_2": 3, "железо_2": 3}, "luck", 1800,
     "+12% к шансам в играх на 30 мин"),
    ("сила", "Зелье силы", "💪", 25_000,
     {"железо_1": 6}, "rob", 7200,
     "+25% к успеху ограбления на 2 ч"),
    ("шахтёр", "Зелье шахтёра", "⛏", 60_000,
     {"железо_2": 4, "серебро_1": 2}, "mine", 3600,
     "Добыча в шахте ×2 на 1 ч"),
    ("щит", "Зелье щита", "🛡", 120_000,
     {"медь_1": 4, "серебро_1": 2}, "shield", 7200,
     "Защита от ограбления на 2 ч"),
    ("богатство", "Эликсир богатства", "💰", 8_000_000,
     {"платина_2": 2, "кристалл_1": 1}, "instant", 0,
     "Мгновенно +15% баланса (макс +2 млрд)"),
    ("время", "Эликсир времени", "⏳", 50_000_000,
     {"кристалл_2": 2}, "time", 0,
     "Сброс всех кулдаунов + полная энергия"),
]
POTION_CRAFT_MAX = 20
POTION_RICH_MIN = 1_000_000
POTION_RICH_MAX = 2e9

# ==================== СУНДУКИ ====================
# Шансы внутри каждого сундука дают в сумме ровно 1.0.
CHESTS = [
    {"id": "обычный", "name": "Обычный сундук", "emoji": "📦", "price": 25_000,
     "money_chance": 0.40, "money": (3_000, 40_000),
     "mats_chance": 0.35, "tiers": (1, 2), "mats_qty": (2, 4),
     "potion_chance": 0.15, "potions": ("удача", "сила", "шахтёр"),
     "jackpot_chance": 0.10, "jackpot_mult": 8},
    {"id": "редкий", "name": "Редкий сундук", "emoji": "🎁", "price": 400_000,
     "money_chance": 0.45, "money": (40_000, 500_000),
     "mats_chance": 0.30, "tiers": (2, 3), "mats_qty": (2, 3),
     "potion_chance": 0.20, "potions": ("удача", "сила", "шахтёр", "щит"),
     "jackpot_chance": 0.05, "jackpot_mult": 6},
    {"id": "легендарный", "name": "Легендарный сундук", "emoji": "💎", "price": 20_000_000,
     "money_chance": 0.50, "money": (2_000_000, 30_000_000),
     "mats_chance": 0.28, "tiers": (4, 5), "mats_qty": (2, 3),
     "potion_chance": 0.17, "potions": ("богатство", "щит", "время"),
     "jackpot_chance": 0.05, "jackpot_mult": 6},
    {"id": "мифический", "name": "Мифический сундук", "emoji": "🌟", "price": 1_500_000_000,
     "money_chance": 0.55, "money": (150_000_000, 3e9),
     "mats_chance": 0.22, "tiers": (5, 5), "mats_qty": (2, 4),
     "potion_chance": 0.20, "potions": ("богатство", "время"),
     "jackpot_chance": 0.03, "jackpot_mult": 8},
    {"id": "бесконечный", "name": "Бесконечный сундук", "emoji": "🌀", "price": 300_000_000_000,
     "money_chance": 0.60, "money": (30e9, 900e9),
     "mats_chance": 0.15, "tiers": (4, 5), "mats_qty": (3, 6),
     "potion_chance": 0.20, "potions": ("богатство", "время"),
     "jackpot_chance": 0.05, "jackpot_mult": 10},
]
CHEST_OPEN_MAX = 50

# ==================== РЫНОК (крипта/активы) ====================
# (id, название, emoji, базовая цена, волатильность за шаг)
MARKET_ITEMS = [
    ("биткоин", "Биткоин", "🪙", 60_000, 0.16),
    ("эфир", "Эфир", "🧿", 3_200, 0.20),
    ("золото", "Золото", "🥇", 6_500, 0.06),
    ("нефть", "Нефть", "🛢", 85, 0.12),
    ("акции", "Акции", "📈", 12_000, 0.09),
]
MARKET_UPDATE_SEC = 300
MARKET_PRICE_MIN = 0.15              # нижняя граница цены: ×0.15 от базовой
MARKET_PRICE_MAX = 60.0              # верхняя граница: ×60 от базовой
MARKET_QTY_MIN = 0.0001

# ==================== ШАХТА ====================
MINE_ENERGY_MAX = 100
MINE_ENERGY_REGEN_SEC = 90           # 1 энергия каждые 90 секунд
MINE_DIG_COST = 15                   # энергия за одну копку


def mine_upgrade_cost(level: int) -> int:
    """Деньги за улучшение шахты level -> level+1 (без предела)."""
    return int(50_000 * (level ** 2.1))


def mine_upgrade_mats(level: int) -> dict:
    """Материалы на улучшение: тир растёт с уровнем."""
    tier = min(5, 1 + level // 2)
    return {f"железо_{tier}": min(25, 3 + level)}


def mine_loot_range(level: int) -> tuple[int, int]:
    lo = int(400 * (level ** 1.35))
    hi = int(1200 * (level ** 1.35))
    return lo, max(lo, hi)


def mine_mats_rolls(level: int) -> int:
    return 1 if level < 3 else 2


def mine_max_tier(level: int) -> int:
    return min(5, 1 + level // 3)


# ==================== ИГРЫ ====================
SYMBOLS = ["🍒", "🍋", "🍇", "🔔", "💎", "7️⃣"]
PAYOUT3 = {"7️⃣": 77, "💎": 33, "🍒": 11, "🍋": 11, "🍇": 11, "🔔": 11}
PAIR_MULT = 1.4                      # две одинаковые катушки
LUCK_COIN_WIN = 0.56                 # шанс победы в монетке с зельем удачи
LUCK_SAVE = 0.10                     # шанс возврата ставки при проигрыше (казино/рулетка) с удачей
ROULETTE_RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

# ==================== ОГРАБЛЕНИЕ / ПЕРЕВОДЫ / БАНК ====================
ROB_COOLDOWN = 3 * 3600              # кулдаун ограбления — ровно 3 часа
ROB_BASE_CHANCE = 0.45
ROB_STRENGTH_BONUS = 0.25            # бонус зелья силы
ROB_STEAL_RATE = 0.15                # доля от баланса жертвы
ROB_STEAL_MIN = 1_000
ROB_FINE_RATE = 0.10                 # штраф при неудаче: 10% баланса грабителя
ROB_FINE_MIN = 500
ROB_FINE_MAX = 50_000_000
ROB_TARGET_MIN_BALANCE = 5_000       # не грабим совсем нищих
TRANSFER_MIN = 100
BANK_RATE_PER_HOUR = 0.03            # банк: +3% в час
BANK_ACCRUAL_CAP_HOURS = 24          # проценты копятся максимум за сутки
BANK_MIN_DEPOSIT = 1_000

# ==================== ЛОВЕЦ СЛОВ ====================
WORD_ROUND_TIME = 180                # длительность раунда, сек
WORD_MIN_GAP = 600                   # минимальная пауза между раундами, сек
WORD_CHANCE = 0.03                   # шанс запуска раунда на каждое сообщение
# (слово, приз)
WORDS = [
    ("банан", 20_000), ("мост", 20_000), ("корона", 20_000), ("заяц", 20_000),
    ("звезда", 20_000), ("камень", 20_000), ("лодка", 20_000), ("медведь", 20_000),
    ("окно", 20_000), ("река", 20_000), ("солнце", 20_000), ("тигр", 20_000),
    ("хлеб", 20_000), ("чашка", 20_000), ("ключ", 20_000), ("облако", 20_000),
    ("алмаз", 100_000), ("вокзал", 100_000), ("город", 100_000), ("джунгли", 100_000),
    ("долина", 100_000), ("капитан", 100_000), ("магнит", 100_000), ("остров", 100_000),
    ("пират", 100_000), ("ракета", 100_000), ("салют", 100_000), ("трактор", 100_000),
    ("фонарь", 100_000), ("яхта", 100_000), ("водопад", 100_000), ("костёр", 100_000),
    ("вселенная", 500_000), ("галактика", 500_000), ("дирижабль", 500_000),
    ("метеорит", 500_000), ("радиация", 500_000), ("телескоп", 500_000),
    ("ускоритель", 500_000), ("антиматерия", 500_000),
]

# ==================== ПОИСК ПО СПРАВОЧНИКАМ ====================
def match_entry(query: str, entries, id_idx: int = 0, name_idx: int = 1):
    """Поиск записи по id или названию (точное совпадение или уникальный префикс).

    Возвращает (запись | None, список_вариантов).
    """
    q = (query or "").strip().lower()
    if not q:
        return None, []
    exact = [e for e in entries
             if q == str(e[id_idx]).lower() or q == str(e[name_idx]).lower()]
    if exact:
        return exact[0], []
    if len(q) >= 3:
        partial = [e for e in entries
                   if str(e[name_idx]).lower().startswith(q)
                   or str(e[id_idx]).lower().startswith(q)]
        if len(partial) == 1:
            return partial[0], []
        if len(partial) > 1:
            return None, partial
    return None, []


def match_dict(query: str, items, key: str = "id", name_key: str = "name"):
    """То же самое для списка словарей (сундуки)."""
    q = (query or "").strip().lower()
    if not q:
        return None, []
    exact = [it for it in items
             if q == str(it.get(key, "")).lower() or q == str(it.get(name_key, "")).lower()]
    if exact:
        return exact[0], []
    if len(q) >= 3:
        partial = [it for it in items
                   if str(it.get(name_key, "")).lower().startswith(q)
                   or str(it.get(key, "")).lower().startswith(q)]
        if len(partial) == 1:
            return partial[0], []
        if len(partial) > 1:
            return None, partial
    return None, []
