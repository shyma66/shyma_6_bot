"""Регистрация модулей-заглушек дашборда.

Реальные модули подключаются своим setup(app) из bot_start (например, «Шкаф» и
«Напоминания»). Здесь остаётся только ещё не сделанный модуль: Календарь — шаг 5.
"""
from telegram import Update
from telegram.ext import ContextTypes

from core.dashboard import edit_safely, home_markup
from core.registry import Module, register


def _placeholder(title: str):
    """Временный обработчик: показывает «в разработке» + кнопку возврата в меню."""

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await edit_safely(
            update.callback_query,
            f"Модуль «{title}» — в разработке 🚧",
            reply_markup=home_markup(),
        )

    return handler


register(Module(key="calendar", title="📅 Календарь", on_open=_placeholder("Календарь")))
