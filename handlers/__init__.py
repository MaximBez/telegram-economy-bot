"""Сборка роутеров в строгом порядке.

Порядок обработки: админка → объекты → шахта → рынок → зелья → сундуки →
игры → соцальное/справка → профиль → ЛОВЕЦ СЛОВ (строго последний).
"""
from aiogram import Router

from . import (
    admin,
    chests,
    games,
    market,
    mines,
    objects,
    potions,
    profile,
    social,
    wordcatch,
)

_ORDER = (
    admin,
    objects,
    mines,
    market,
    potions,
    chests,
    games,
    social,
    profile,
    wordcatch,  # catch-all — всегда последним!
)


def build_router() -> Router:
    root = Router(name="root")
    for module in _ORDER:
        root.include_router(module.router)
    return root
