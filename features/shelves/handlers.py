"""Модуль «Шкаф памяти»: полки + заметки (полный CRUD).

Навигация — инлайн-кнопки; ввод текста (название полки, текст заметки) —
через ConversationHandler. callback_data:
  shelf:list | shelf:new | shelf:open:<id> | shelf:del:<id> | shelf:delyes:<id>
  note:new:<shelfId> | note:open:<id> | note:edit:<id> | note:del:<id>
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from core.dashboard import HOME_KEY, CALLBACK_PREFIX
from core.registry import Module, register
from features.shelves import repo

# Состояния диалога ввода
SHELF_NAME, NOTE_TEXT, NOTE_EDIT = range(3)

# Лимиты (improvements #07)
MAX_TITLE = 255
MAX_NOTE = 4000

_HOME_CB = f"{CALLBACK_PREFIX}{HOME_KEY}"  # «⬅️ Меню» -> дашборд


def _arg(data: str) -> int:
    """Последний сегмент callback_data как int (id)."""
    return int(data.rsplit(":", 1)[1])


def _preview(text: str, n: int = 40) -> str:
    first = (text.strip().splitlines() or ["(пусто)"])[0]
    return first[:n] + ("…" if len(first) > n else "")


# ----- рендеринг экранов -> (text, markup) -----

async def _render_shelf_list(tg_id: int):
    shelves = await repo.list_shelves(tg_id)
    rows = [
        [InlineKeyboardButton(s.title, callback_data=f"shelf:open:{s.id}")]
        for s in shelves
    ]
    rows.append([InlineKeyboardButton("➕ Новая полка", callback_data="shelf:new")])
    rows.append([InlineKeyboardButton("⬅️ Меню", callback_data=_HOME_CB)])
    text = "🗄 Шкаф памяти\n\n" + ("Выбери полку:" if shelves else "Полок пока нет.")
    return text, InlineKeyboardMarkup(rows)


async def _render_shelf(tg_id: int, shelf_id: int):
    shelf = await repo.get_shelf(tg_id, shelf_id)
    if shelf is None:
        return "Полка не найдена.", InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ К полкам", callback_data="shelf:list")]]
        )
    notes = await repo.list_notes(tg_id, shelf_id)
    rows = [
        [InlineKeyboardButton(f"📝 {_preview(n.text)}", callback_data=f"note:open:{n.id}")]
        for n in notes
    ]
    rows.append([InlineKeyboardButton("➕ Новая заметка", callback_data=f"note:new:{shelf_id}")])
    rows.append([InlineKeyboardButton("🗑 Удалить полку", callback_data=f"shelf:del:{shelf_id}")])
    rows.append([InlineKeyboardButton("⬅️ К полкам", callback_data="shelf:list")])
    text = f"🗄 {shelf.title}\n\n" + ("Заметки:" if notes else "Заметок пока нет.")
    return text, InlineKeyboardMarkup(rows)


async def _render_note(tg_id: int, note_id: int):
    note = await repo.get_note(tg_id, note_id)
    if note is None:
        return "Заметка не найдена.", InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ К полкам", callback_data="shelf:list")]]
        )
    rows = [
        [
            InlineKeyboardButton("✏️ Редактировать", callback_data=f"note:edit:{note.id}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"note:del:{note.id}"),
        ],
        [InlineKeyboardButton("⬅️ К полке", callback_data=f"shelf:open:{note.shelf_id}")],
    ]
    return f"📝 Заметка:\n\n{note.text}", InlineKeyboardMarkup(rows)


async def _edit(update: Update, text: str, markup: InlineKeyboardMarkup) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text, reply_markup=markup)


# ----- навигация (callback-кнопки) -----

async def open_shelves(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Список полок. Используется как on_open модуля и по shelf:list."""
    text, markup = await _render_shelf_list(update.effective_user.id)
    await _edit(update, text, markup)


async def open_shelf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, markup = await _render_shelf(update.effective_user.id, _arg(update.callback_query.data))
    await _edit(update, text, markup)


async def open_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, markup = await _render_note(update.effective_user.id, _arg(update.callback_query.data))
    await _edit(update, text, markup)


async def confirm_del_shelf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    shelf_id = _arg(update.callback_query.data)
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f"shelf:delyes:{shelf_id}")],
            [InlineKeyboardButton("⬅️ Отмена", callback_data=f"shelf:open:{shelf_id}")],
        ]
    )
    await _edit(update, "Удалить полку вместе со всеми её заметками?", markup)


async def do_del_shelf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await repo.delete_shelf(update.effective_user.id, _arg(update.callback_query.data))
    text, markup = await _render_shelf_list(update.effective_user.id)
    await _edit(update, text, markup)


async def do_del_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    shelf_id = await repo.delete_note(update.effective_user.id, _arg(update.callback_query.data))
    if shelf_id is None:
        text, markup = await _render_shelf_list(update.effective_user.id)
    else:
        text, markup = await _render_shelf(update.effective_user.id, shelf_id)
    await _edit(update, text, markup)


# ----- диалог ввода текста -----

async def new_shelf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Введите название новой полки:")
    return SHELF_NAME


async def recv_shelf_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    title = update.message.text.strip()
    if not title:
        await update.message.reply_text("Название пустое. Введите ещё раз:")
        return SHELF_NAME
    if len(title) > MAX_TITLE:
        await update.message.reply_text(f"Слишком длинно (макс {MAX_TITLE}). Введите короче:")
        return SHELF_NAME
    await repo.create_shelf(update.effective_user.id, title)
    text, markup = await _render_shelf_list(update.effective_user.id)
    await update.message.reply_text(text, reply_markup=markup)
    return ConversationHandler.END


async def new_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["shelf_id"] = _arg(update.callback_query.data)
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Введите текст заметки:")
    return NOTE_TEXT


async def recv_note_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    shelf_id = context.user_data.get("shelf_id")
    text = update.message.text
    if len(text) > MAX_NOTE:
        await update.message.reply_text(f"Слишком длинно (макс {MAX_NOTE}). Введите короче:")
        return NOTE_TEXT
    await repo.create_note(update.effective_user.id, shelf_id, text)
    context.user_data.pop("shelf_id", None)
    body, markup = await _render_shelf(update.effective_user.id, shelf_id)
    await update.message.reply_text(body, reply_markup=markup)
    return ConversationHandler.END


async def edit_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["note_id"] = _arg(update.callback_query.data)
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Введите новый текст заметки:")
    return NOTE_EDIT


async def recv_note_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    note_id = context.user_data.get("note_id")
    text = update.message.text
    if len(text) > MAX_NOTE:
        await update.message.reply_text(f"Слишком длинно (макс {MAX_NOTE}). Введите короче:")
        return NOTE_EDIT
    await repo.update_note(update.effective_user.id, note_id, text)
    context.user_data.pop("note_id", None)
    body, markup = await _render_note(update.effective_user.id, note_id)
    await update.message.reply_text(body, reply_markup=markup)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("shelf_id", None)
    context.user_data.pop("note_id", None)
    text, markup = await _render_shelf_list(update.effective_user.id)
    await update.message.reply_text(text, reply_markup=markup)
    return ConversationHandler.END


_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(new_shelf, pattern=r"^shelf:new$"),
        CallbackQueryHandler(new_note, pattern=r"^note:new:\d+$"),
        CallbackQueryHandler(edit_note, pattern=r"^note:edit:\d+$"),
    ],
    states={
        SHELF_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_shelf_name)],
        NOTE_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_note_text)],
        NOTE_EDIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_note_edit)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_message=False,
)


def setup(app: Application) -> None:
    """Регистрирует модуль в дашборде и подключает его handlers."""
    register(Module(key="shelves", title="🗄 Шкаф памяти", on_open=open_shelves))
    app.add_handler(_conversation)
    app.add_handler(CallbackQueryHandler(open_shelves, pattern=r"^shelf:list$"))
    app.add_handler(CallbackQueryHandler(open_shelf, pattern=r"^shelf:open:\d+$"))
    app.add_handler(CallbackQueryHandler(confirm_del_shelf, pattern=r"^shelf:del:\d+$"))
    app.add_handler(CallbackQueryHandler(do_del_shelf, pattern=r"^shelf:delyes:\d+$"))
    app.add_handler(CallbackQueryHandler(open_note, pattern=r"^note:open:\d+$"))
    app.add_handler(CallbackQueryHandler(do_del_note, pattern=r"^note:del:\d+$"))
