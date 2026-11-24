"""Кастомные фильтры команд: матчат и /слэш-форму, и обычное слово."""
from aiogram.filters import Filter
from aiogram.types import Message


class Cmd(Filter):
    """Матчит первое слово сообщения как команду.

    Срабатывает и на '/баланс 10', и на 'баланс 10', и на '/баланс@mybot 10'.
    Регистр не важен.
    """

    def __init__(self, *names: str):
        self.names = {n.lower() for n in names}

    async def __call__(self, message: Message) -> bool:
        text = (message.text or "").strip().lower()
        if not text:
            return False
        first = text.split(maxsplit=1)[0]
        if "@" in first:
            first = first.split("@", 1)[0]
        if first.startswith("/"):
            first = first[1:]
        return first in self.names


def args_of(message: Message) -> list[str]:
    """Аргументы после первого слова: 'купить железо 2 10' -> ['железо', '2', '10']."""
    text = (message.text or "").strip()
    if not text:
        return []
    return text.split()[1:]
