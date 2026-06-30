"""Регистрация модулей-заглушек дашборда.

Реальные модули подключаются своим setup(app) из bot_start (например, «Шкаф» —
features/shelves/handlers.setup). Здесь остаются только ещё не сделанные модули:
Напоминания — шаг 4, Календарь — шаг 5.
"""
from telegram import Update
from telegram.ext import ContextTypes

from core.dashboard import home_markup
from core.registry import Module, register


def _placeholder(title: str):
    """Временный обработчик: показывает «в разработке» + кнопку возврата в меню."""

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            f"Модуль «{title}» — в разработке 🚧", reply_markup=home_markup()
        )

    return handler


register(Module(key="reminders", title="⏰ Напоминания", on_open=_placeholder("Напоминания")))
register(Module(key="calendar", title="📅 Календарь", on_open=_placeholder("Календарь")))
