"""Дашборд: строит инлайн-меню из реестра модулей и маршрутизирует нажатия.

Все подписи языкозависимы (core/i18n.py); здесь же живёт экран «🌐 Язык»
(кнопка модуля регистрируется в core/modules.py, чтобы стоять в конце меню).
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from core.i18n import LANG_TITLES, LANGS, t, user_lang
from core.registry import MODULES, get_module
from DataBase.database import set_user_language

# Префикс callback_data всех кнопок дашборда: "dash:<key>".
CALLBACK_PREFIX = "dash:"
HOME_KEY = "__home__"  # возврат в главное меню


async def answer_safely(query, *args, **kwargs) -> None:
    """query.answer() без падения, если callback устарел.

    На Render free инстанс засыпает; при холодном старте callback может протухнуть,
    и answer() бросит ошибку. Глотаем её, чтобы последующий edit всё равно выполнился.
    """
    try:
        await query.answer(*args, **kwargs)
    except Exception:  # noqa: BLE001
        pass


async def edit_safely(query, text: str, reply_markup=None) -> None:
    """Отвечает на callback и редактирует сообщение, не падая на устаревшем callback
    и на «message is not modified»."""
    await answer_safely(query)
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


def build_dashboard_markup(lang: str) -> InlineKeyboardMarkup:
    """Кнопки меню по одному модулю в ряд (из реестра), подписи на языке юзера."""
    rows = [
        [InlineKeyboardButton(t(lang, m.title_key), callback_data=f"{CALLBACK_PREFIX}{m.key}")]
        for m in MODULES
    ]
    return InlineKeyboardMarkup(rows)


def home_markup(lang: str) -> InlineKeyboardMarkup:
    """Кнопка «назад в меню» для экранов модулей."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t(lang, "common.menu_btn"), callback_data=f"{CALLBACK_PREFIX}{HOME_KEY}")]]
    )


async def show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает меню: новым сообщением (на /start) или редактируя текущее (из callback)."""
    lang = await user_lang(update, context)
    if update.callback_query:
        await edit_safely(
            update.callback_query,
            t(lang, "menu.title"),
            reply_markup=build_dashboard_markup(lang),
        )
    else:
        await update.message.reply_text(
            t(lang, "menu.title"), reply_markup=build_dashboard_markup(lang)
        )


async def dashboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Маршрутизирует нажатие кнопки меню к обработчику нужного модуля."""
    query = update.callback_query
    key = query.data[len(CALLBACK_PREFIX):]

    if key == HOME_KEY:
        await show_dashboard(update, context)
        return

    module = get_module(key)
    if module is None:
        lang = await user_lang(update, context)
        await answer_safely(query, t(lang, "menu.unknown_module"), show_alert=True)
        return

    await module.on_open(update, context)


# ----- экран «🌐 Язык» -----

async def language_screen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    rows = [
        [
            InlineKeyboardButton(
                ("✅ " if code == lang else "") + LANG_TITLES[code],
                callback_data=f"lang:set:{code}",
            )
        ]
        for code in LANGS
    ]
    rows.append(
        [InlineKeyboardButton(t(lang, "common.menu_btn"), callback_data=f"{CALLBACK_PREFIX}{HOME_KEY}")]
    )
    await edit_safely(
        update.callback_query, t(lang, "lang.title"), reply_markup=InlineKeyboardMarkup(rows)
    )


async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    code = update.callback_query.data.rsplit(":", 1)[1]
    if code in LANGS:
        await set_user_language(update.effective_user.id, code)
        context.user_data["lang"] = code
    await show_dashboard(update, context)


def register_core(app: Application) -> None:
    """Подключает callback-роутер дашборда и переключатель языка к приложению."""
    app.add_handler(CallbackQueryHandler(dashboard_callback, pattern=f"^{CALLBACK_PREFIX}"))
    app.add_handler(CallbackQueryHandler(set_language, pattern=r"^lang:set:(ru|en|de)$"))
