"""Реестр модулей дашборда.

Каждый модуль — кнопка в меню + обработчик открытия. Добавить модуль =
одна строка register(...) в core/modules.py; ядро при этом не трогаем.
"""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from telegram import Update
from telegram.ext import ContextTypes

# Тип обработчика открытия модуля (вызывается при нажатии кнопки в меню).
OpenHandler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


@dataclass
class Module:
    key: str        # уникальный id, попадает в callback_data
    title_key: str  # i18n-ключ подписи кнопки в меню (см. core/i18n.py)
    on_open: OpenHandler
    admin_only: bool = False  # кнопку видит и открыть может только админ
    essential: bool = False   # нельзя выключить из админ-панели (сама панель)


MODULES: list[Module] = []


def register(module: Module) -> None:
    """Регистрирует модуль в дашборде (защита от дублей по key)."""
    if any(m.key == module.key for m in MODULES):
        raise ValueError(f"Модуль с key={module.key!r} уже зарегистрирован")
    MODULES.append(module)


def get_module(key: str) -> Module | None:
    return next((m for m in MODULES if m.key == key), None)
