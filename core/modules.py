"""Регистрация модулей дашборда. Новый модуль = одна строка register(...).

Пока все три модуля — заглушки; реальная логика придёт в своих шагах плана
(Шкаф — шаг 3, Напоминания — шаг 4, Календарь — шаг 5).
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


register(Module(key="shelves", title="🗄 Шкаф памяти", on_open=_placeholder("Шкаф памяти")))
register(Module(key="reminders", title="⏰ Напоминания", on_open=_placeholder("Напоминания")))
register(Module(key="calendar", title="📅 Календарь", on_open=_placeholder("Календарь")))
