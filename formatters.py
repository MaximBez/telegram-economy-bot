"""Форматирование больших чисел и времени, парсинг сумм, экранирование HTML."""
import re
from html import escape

from config import MAX_BALANCE

# Большие единицы: от старшей к младшей.
_UNITS = (
    (1e33, "дец"), (1e30, "нон"), (1e27, "окт"), (1e24, "септ"),
    (1e21, "скст"), (1e18, "квнт"), (1e15, "квдр"), (1e12, "трлн"),
    (1e9, "млрд"), (1e6, "млн"), (1e3, "тыс"),
)

# Русские и латинские суффиксы для парсинга сумм.
_SUFFIX_MULT = {
    "дециллион": 1e33, "дец": 1e33,
    "нониллион": 1e30, "нон": 1e30,
    "октиллион": 1e27, "окт": 1e27,
    "септиллион": 1e24, "септ": 1e24,
    "секстиллион": 1e21, "скст": 1e21, "секст": 1e21,
    "квинтиллион": 1e18, "квинт": 1e18, "квнт": 1e18,
    "квадриллион": 1e15, "квадр": 1e15, "квдр": 1e15,
    "триллион": 1e12, "трлн": 1e12, "трл": 1e12, "т": 1e12,
    "миллиард": 1e9, "млрд": 1e9, "млр": 1e9, "б": 1e9, "b": 1e9,
    "миллион": 1e6, "млн": 1e6, "мл": 1e6, "m": 1e6, "м": 1e6,
    "тысяч": 1e3, "тысяча": 1e3, "тыс": 1e3, "тс": 1e3, "к": 1e3, "k": 1e3,
}
_SUFFIX_ORDERED = sorted(_SUFFIX_MULT.items(), key=lambda kv: -len(kv[0]))

_WORDS_ALL = ("всё", "все", "all", "весь", "всю", "макс", "max")


def fmt(value) -> str:
    """1234567 -> '1.23 млн'; 950 -> '950'; 1.5e20 -> '150 квнт'."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "0"
    if n != n:  # NaN
        return "0"
    if n == float("inf"):
        return "∞"
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n >= 1e36:
        mantissa, exponent = f"{n:.3e}".split("e")
        mantissa = mantissa.rstrip("0").rstrip(".")
        exponent = exponent.lstrip("+")
        return f"{sign}{mantissa}e{exponent}"
    for unit, name in _UNITS:
        if n >= unit:
            x = n / unit
            if x >= 100:
                s = f"{x:.0f}"
            elif x >= 10:
                s = f"{x:.1f}"
            else:
                s = f"{x:.2f}"
            s = s.rstrip("0").rstrip(".")
            return f"{sign}{s} {name}"
    if n == int(n):
        return f"{sign}{int(n):,}".replace(",", " ")
    return f"{sign}{n:.2f}".rstrip("0").rstrip(".")


def fmt_time(seconds) -> str:
    """7260 -> '2 ч 1 мин'; 45 -> '45 сек'."""
    s = int(seconds)
    if s <= 0:
        return "0 сек"
    days, s = divmod(s, 86400)
    hours, s = divmod(s, 3600)
    minutes, secs = divmod(s, 60)
    parts = []
    if days:
        parts.append(f"{days} д")
    if hours:
        parts.append(f"{hours} ч")
    if minutes:
        parts.append(f"{minutes} мин")
    if secs and not days and not hours:
        parts.append(f"{secs} сек")
    return " ".join(parts) if parts else "0 сек"


def esc(text) -> str:
    """Экранирование HTML (имена пользователей и т.п.)."""
    return escape(str(text or ""))


def parse_amount(raw: str, ref: float | None = None) -> float | None:
    """Парсинг суммы.

    '10к' -> 10_000 | '2.5млн' -> 2.5e6 | '3трлн' -> 3e12 | '2e18' -> 2e18
    '50%' -> 50% от ref | 'всё'/'all' -> ref | '1234' -> 1234.0
    Возвращает None, если разобрать не удалось.
    """
    s = (raw or "").strip().lower().replace(",", ".").replace(" ", "")
    s = s.replace("\u00a0", "").replace("\u202f", "")
    if not s:
        return None
    if ref is not None and s in _WORDS_ALL:
        return ref
    if ref is not None and s.endswith("%"):
        try:
            pct = float(s[:-1])
        except ValueError:
            return None
        if pct < 0:
            return None
        return min(ref * pct / 100.0, MAX_BALANCE)
    v: float | None
    try:
        v = float(s)  # 1234, 1.5, 2e18
    except ValueError:
        v = None
    if v is None:
        m = re.fullmatch(r"(\d+(?:\.\d+)?)([a-zа-яё]+)", s)
        if not m:
            return None
        mult = None
        suffix = m.group(2)
        for suf, mlt in _SUFFIX_ORDERED:
            if suffix == suf:
                mult = mlt
                break
        if mult is None:
            return None
        v = float(m.group(1)) * mult
    if v != v or v < 0:
        return None
    if v == float("inf"):
        v = MAX_BALANCE
    return min(v, MAX_BALANCE)


def parse_qty(raw: str) -> int | None:
    """Целое количество >= 1 ('всё' не подходит)."""
    v = parse_amount(raw)
    if v is None or v < 1 or v != int(v):
        return None
    return int(v)
