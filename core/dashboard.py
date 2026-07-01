"""Дашборд: строит инлайн-меню из реестра модулей и маршрутизирует нажатия."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from core.registry import MODULES, get_module

# Префикс callback_data всех кнопок дашборда: "dash:<key>".
CALLBACK_PREFIX = "dash:"
HOME_KEY = "__home__"  # возврат в главное меню

DASHBOARD_TEXT = "Главное меню — выбери модуль:"


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


def build_dashboard_markup() -> InlineKeyboardMarkup:
    """Кнопки меню по одному модулю в ряд (из реестра)."""
    rows = [
        [InlineKeyboardButton(m.title, callback_data=f"{CALLBACK_PREFIX}{m.key}")]
        for m in MODULES
    ]
    return InlineKeyboardMarkup(rows)


def home_markup() -> InlineKeyboardMarkup:
    """Кнопка «назад в меню» для экранов модулей."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Меню", callback_data=f"{CALLBACK_PREFIX}{HOME_KEY}")]]
    )


async def show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает меню: новым сообщением (на /start) или редактируя текущее (из callback)."""
    if update.callback_query:
        await edit_safely(
            update.callback_query, DASHBOARD_TEXT, reply_markup=build_dashboard_markup()
        )
    else:
        await update.message.reply_text(
            DASHBOARD_TEXT, reply_markup=build_dashboard_markup()
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
        await answer_safely(query, "Неизвестный модуль", show_alert=True)
        return

    await module.on_open(update, context)


def register_core(app: Application) -> None:
    """Подключает callback-роутер дашборда к приложению."""
    app.add_handler(CallbackQueryHandler(dashboard_callback, pattern=f"^{CALLBACK_PREFIX}"))
