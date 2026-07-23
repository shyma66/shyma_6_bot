"""Настройки + согласие на обработку данных (Datenschutz).

Жёсткое согласие: без нажатия «Согласен» меню не открывается. Экран согласия
показывает политику + [✅ Согласен / ❌ Отказ / 🌐 Язык]. После согласия в меню
появляется ⚙️ Настройки: язык, политика, удалить все мои данные.

callback_data:
  consent:agree | consent:decline
  set:home | set:lang | set:setlang:<code> | set:policy | set:del | set:delyes
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from core.dashboard import CALLBACK_PREFIX, HOME_KEY, answer_safely, edit_safely
from core.i18n import LANG_TITLES, LANGS, t, user_lang
from core.registry import Module, register
from DataBase.database import erase_user, has_consent, set_consent, set_user_language

_HOME_CB = f"{CALLBACK_PREFIX}{HOME_KEY}"


async def is_consented(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Дал ли пользователь согласие (кэш диалога -> БД)."""
    if context is not None and context.user_data.get("consent"):
        return True
    ok = await has_consent(update.effective_user.id)
    if ok and context is not None:
        context.user_data["consent"] = True
    return ok


# ----- экран согласия (гейт) -----

def _consent_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "consent.agree"), callback_data="consent:agree")],
            [InlineKeyboardButton(t(lang, "consent.decline"), callback_data="consent:decline")],
            [InlineKeyboardButton(t(lang, "module.language"), callback_data="set:lang")],
        ]
    )


def _policy_body(lang: str) -> str:
    return t(lang, "policy.text")


async def show_consent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Экран согласия: политика + кнопки. Работает и на /start (message), и из callback."""
    lang = await user_lang(update, context)
    body = _policy_body(lang) + "\n\n" + t(lang, "consent.ask")
    if update.callback_query:
        await edit_safely(update.callback_query, body[:4000], reply_markup=_consent_kb(lang))
    else:
        await update.message.reply_text(body[:4000], reply_markup=_consent_kb(lang))


async def consent_agree(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    await set_consent(u.id, u.username)
    context.user_data["consent"] = True
    from core.dashboard import show_dashboard
    await show_dashboard(update, context)


async def consent_decline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    await edit_safely(
        update.callback_query,
        t(lang, "consent.declined") + "\n\n" + t(lang, "consent.ask"),
        reply_markup=_consent_kb(lang),
    )


# ----- меню настроек -----

def _settings_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "module.language"), callback_data="set:lang")],
            [InlineKeyboardButton(t(lang, "set.policy_btn"), callback_data="set:policy")],
            [InlineKeyboardButton(t(lang, "set.delete_btn"), callback_data="set:del")],
            [InlineKeyboardButton(t(lang, "common.home_btn"), callback_data=_HOME_CB)],
        ]
    )


async def open_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """on_open модуля ⚙️ Настройки (из меню)."""
    lang = await user_lang(update, context)
    await edit_safely(update.callback_query, t(lang, "set.title"), reply_markup=_settings_kb(lang))


# ----- язык (внутри настроек / на экране согласия) -----

async def open_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    rows = [
        [
            InlineKeyboardButton(
                ("✅ " if code == lang else "") + LANG_TITLES[code],
                callback_data=f"set:setlang:{code}",
            )
        ]
        for code in LANGS
    ]
    back = "set:home" if await is_consented(update, context) else "consent:show"
    rows.append([InlineKeyboardButton(t(lang, "common.back_btn"), callback_data=back)])
    await edit_safely(update.callback_query, t(lang, "lang.title"), reply_markup=InlineKeyboardMarkup(rows))


async def set_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    code = update.callback_query.data.rsplit(":", 1)[1]
    if code in LANGS:
        await set_user_language(update.effective_user.id, code)
        context.user_data["lang"] = code
    # вернуться туда, откуда пришли: в настройки (согласившимся) или к согласию
    if await is_consented(update, context):
        await open_settings(update, context)
    else:
        await show_consent(update, context)


async def consent_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_consent(update, context)


# ----- политика (перечитать) -----

async def show_policy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "common.back_btn"), callback_data="set:home")],
            [InlineKeyboardButton(t(lang, "common.home_btn"), callback_data=_HOME_CB)],
        ]
    )
    await edit_safely(update.callback_query, _policy_body(lang)[:4000], reply_markup=kb)


# ----- удаление всех данных -----

async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "set.delete_yes"), callback_data="set:delyes")],
            [InlineKeyboardButton(t(lang, "common.cancel_btn"), callback_data="set:home")],
        ]
    )
    await edit_safely(update.callback_query, t(lang, "set.delete_confirm"), reply_markup=kb)


async def do_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    await erase_user(update.effective_user.id)
    context.user_data.clear()  # сбросить кэш согласия/языка
    context.user_data["lang"] = lang  # язык оставим для этого сообщения
    await edit_safely(update.callback_query, t(lang, "set.deleted"), reply_markup=None)


def setup(app: Application) -> None:
    register(Module(key="settings", title_key="module.settings", on_open=open_settings))
    # согласие
    app.add_handler(CallbackQueryHandler(consent_agree, pattern=r"^consent:agree$"))
    app.add_handler(CallbackQueryHandler(consent_decline, pattern=r"^consent:decline$"))
    app.add_handler(CallbackQueryHandler(consent_show, pattern=r"^consent:show$"))
    # настройки
    app.add_handler(CallbackQueryHandler(open_settings, pattern=r"^set:home$"))
    app.add_handler(CallbackQueryHandler(open_language, pattern=r"^set:lang$"))
    app.add_handler(CallbackQueryHandler(set_lang, pattern=r"^set:setlang:(ru|en|de|uk)$"))
    app.add_handler(CallbackQueryHandler(show_policy, pattern=r"^set:policy$"))
    app.add_handler(CallbackQueryHandler(confirm_delete, pattern=r"^set:del$"))
    app.add_handler(CallbackQueryHandler(do_delete, pattern=r"^set:delyes$"))
