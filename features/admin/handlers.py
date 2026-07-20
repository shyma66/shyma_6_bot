"""Админ-панель: включение/выключение модулей и журнал последних ошибок.

Видна только владельцу (ADMIN_ID в окружении). Каждый обработчик проверяет
права сам: callback_data подделывается — отсутствие кнопки в меню не защита.

callback_data:
  adm:home | adm:toggle:<module_key> | adm:errors | adm:clear
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from core.admin import (
    admin_configured,
    clear_errors,
    is_admin,
    is_disabled,
    recent_errors,
    set_disabled,
)
from core.dashboard import CALLBACK_PREFIX, HOME_KEY, answer_safely, edit_safely
from core.i18n import t, user_lang
from core.registry import MODULES, Module, register

_HOME_CB = f"{CALLBACK_PREFIX}{HOME_KEY}"


async def _deny(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Чужой в админке: тот же ответ, что и на несуществующий модуль — не
    подтверждаем даже факт существования панели."""
    lang = await user_lang(update, context)
    await answer_safely(update.callback_query, t(lang, "menu.unknown_module"), show_alert=True)


def _toggleable() -> list[Module]:
    """Модули, которые можно выключать: без админских и без самой панели."""
    return [m for m in MODULES if not m.admin_only and not m.essential]


def _panel(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    rows = [
        [
            InlineKeyboardButton(
                f"{'🔧' if is_disabled(m.key) else '✅'} {t(lang, m.title_key)}",
                callback_data=f"adm:toggle:{m.key}",
            )
        ]
        for m in _toggleable()
    ]
    errors = recent_errors()
    rows.append(
        [
            InlineKeyboardButton(
                t(lang, "adm.errors_btn", n=len(errors)), callback_data="adm:errors"
            )
        ]
    )
    rows.append([InlineKeyboardButton(t(lang, "common.menu_btn"), callback_data=_HOME_CB)])
    return t(lang, "adm.title"), InlineKeyboardMarkup(rows)


async def open_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await _deny(update, context)
        return
    lang = await user_lang(update, context)
    text, markup = _panel(lang)
    await edit_safely(update.callback_query, text, reply_markup=markup)


async def toggle_module(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await _deny(update, context)
        return
    key = update.callback_query.data.rsplit(":", 1)[1]
    if key not in {m.key for m in _toggleable()}:
        await _deny(update, context)
        return
    await set_disabled(key, not is_disabled(key))
    lang = await user_lang(update, context)
    text, markup = _panel(lang)
    await edit_safely(update.callback_query, text, reply_markup=markup)


async def show_errors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await _deny(update, context)
        return
    lang = await user_lang(update, context)
    errors = recent_errors()
    if not errors:
        body = t(lang, "adm.no_errors")
    else:
        lines = [
            f"• {r.at.strftime('%d.%m %H:%M')} UTC — {r.where}\n  {r.text}" for r in errors
        ]
        body = t(lang, "adm.errors_title", n=len(errors)) + "\n\n" + "\n".join(lines)
    rows = [
        [InlineKeyboardButton(t(lang, "adm.clear_btn"), callback_data="adm:clear")],
        [InlineKeyboardButton(t(lang, "adm.back_btn"), callback_data="adm:home")],
    ]
    await edit_safely(update.callback_query, body[:4000], reply_markup=InlineKeyboardMarkup(rows))


async def clear_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await _deny(update, context)
        return
    clear_errors()
    await show_errors(update, context)


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает собственный Telegram ID — им заполняется ADMIN_ID в окружении."""
    lang = await user_lang(update, context)
    uid = update.effective_user.id
    body = t(lang, "adm.whoami", id=uid)
    if is_admin(uid):
        body += "\n" + t(lang, "adm.whoami_admin")
    elif not admin_configured():
        body += "\n" + t(lang, "adm.whoami_unset")
    await update.message.reply_text(body)


def setup(app: Application) -> None:
    register(
        Module(
            key="admin",
            title_key="module.admin",
            on_open=open_panel,
            admin_only=True,
            essential=True,
        )
    )
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CallbackQueryHandler(open_panel, pattern=r"^adm:home$"))
    app.add_handler(CallbackQueryHandler(toggle_module, pattern=r"^adm:toggle:[a-z_]+$"))
    app.add_handler(CallbackQueryHandler(show_errors, pattern=r"^adm:errors$"))
    app.add_handler(CallbackQueryHandler(clear_log, pattern=r"^adm:clear$"))
