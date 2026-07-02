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

from core.dashboard import HOME_KEY, CALLBACK_PREFIX, edit_safely
from core.i18n import t, user_lang
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


def _preview(lang: str, text: str, n: int = 40) -> str:
    first = (text.strip().splitlines() or [t(lang, "note.empty_preview")])[0]
    return first[:n] + ("…" if len(first) > n else "")


# ----- рендеринг экранов -> (text, markup) -----

async def _render_shelf_list(tg_id: int, lang: str):
    shelves = await repo.list_shelves(tg_id)
    rows = [
        [InlineKeyboardButton(s.title, callback_data=f"shelf:open:{s.id}")]
        for s in shelves
    ]
    rows.append([InlineKeyboardButton(t(lang, "shelf.new_btn"), callback_data="shelf:new")])
    rows.append([InlineKeyboardButton(t(lang, "common.menu_btn"), callback_data=_HOME_CB)])
    text = t(lang, "module.shelves") + "\n\n" + t(
        lang, "shelf.choose" if shelves else "shelf.empty"
    )
    return text, InlineKeyboardMarkup(rows)


async def _render_shelf(tg_id: int, shelf_id: int, lang: str):
    shelf = await repo.get_shelf(tg_id, shelf_id)
    if shelf is None:
        return t(lang, "shelf.not_found"), InlineKeyboardMarkup(
            [[InlineKeyboardButton(t(lang, "shelf.back_to_shelves"), callback_data="shelf:list")]]
        )
    notes = await repo.list_notes(tg_id, shelf_id)
    rows = [
        [InlineKeyboardButton(f"📝 {_preview(lang, n.text)}", callback_data=f"note:open:{n.id}")]
        for n in notes
    ]
    rows.append(
        [InlineKeyboardButton(t(lang, "note.new_btn"), callback_data=f"note:new:{shelf_id}")]
    )
    rows.append(
        [InlineKeyboardButton(t(lang, "shelf.delete_btn"), callback_data=f"shelf:del:{shelf_id}")]
    )
    rows.append(
        [InlineKeyboardButton(t(lang, "shelf.back_to_shelves"), callback_data="shelf:list")]
    )
    text = f"🗄 {shelf.title}\n\n" + t(lang, "shelf.notes" if notes else "shelf.no_notes")
    return text, InlineKeyboardMarkup(rows)


async def _render_note(tg_id: int, note_id: int, lang: str):
    note = await repo.get_note(tg_id, note_id)
    if note is None:
        return t(lang, "note.not_found"), InlineKeyboardMarkup(
            [[InlineKeyboardButton(t(lang, "shelf.back_to_shelves"), callback_data="shelf:list")]]
        )
    rows = [
        [
            InlineKeyboardButton(t(lang, "note.edit_btn"), callback_data=f"note:edit:{note.id}"),
            InlineKeyboardButton(t(lang, "note.delete_btn"), callback_data=f"note:del:{note.id}"),
        ],
        [
            InlineKeyboardButton(
                t(lang, "note.back_to_shelf"), callback_data=f"shelf:open:{note.shelf_id}"
            )
        ],
    ]
    return f"{t(lang, 'note.title')}\n\n{note.text}", InlineKeyboardMarkup(rows)


async def _edit(update: Update, text: str, markup: InlineKeyboardMarkup) -> None:
    await edit_safely(update.callback_query, text, reply_markup=markup)


# ----- навигация (callback-кнопки) -----

async def open_shelves(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Список полок. Используется как on_open модуля и по shelf:list."""
    lang = await user_lang(update, context)
    text, markup = await _render_shelf_list(update.effective_user.id, lang)
    await _edit(update, text, markup)


async def open_shelf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    text, markup = await _render_shelf(
        update.effective_user.id, _arg(update.callback_query.data), lang
    )
    await _edit(update, text, markup)


async def open_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    text, markup = await _render_note(
        update.effective_user.id, _arg(update.callback_query.data), lang
    )
    await _edit(update, text, markup)


async def confirm_del_shelf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    shelf_id = _arg(update.callback_query.data)
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t(lang, "common.yes_delete"), callback_data=f"shelf:delyes:{shelf_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    t(lang, "common.cancel_btn"), callback_data=f"shelf:open:{shelf_id}"
                )
            ],
        ]
    )
    await _edit(update, t(lang, "shelf.confirm_del"), markup)


async def do_del_shelf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    await repo.delete_shelf(update.effective_user.id, _arg(update.callback_query.data))
    text, markup = await _render_shelf_list(update.effective_user.id, lang)
    await _edit(update, text, markup)


async def do_del_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    shelf_id = await repo.delete_note(update.effective_user.id, _arg(update.callback_query.data))
    if shelf_id is None:
        text, markup = await _render_shelf_list(update.effective_user.id, lang)
    else:
        text, markup = await _render_shelf(update.effective_user.id, shelf_id, lang)
    await _edit(update, text, markup)


# ----- диалог ввода текста -----

async def new_shelf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    await edit_safely(update.callback_query, t(lang, "shelf.enter_name"))
    return SHELF_NAME


async def recv_shelf_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    title = update.message.text.strip()
    if not title:
        await update.message.reply_text(t(lang, "shelf.name_empty"))
        return SHELF_NAME
    if len(title) > MAX_TITLE:
        await update.message.reply_text(t(lang, "common.too_long", max=MAX_TITLE))
        return SHELF_NAME
    await repo.create_shelf(update.effective_user.id, title)
    text, markup = await _render_shelf_list(update.effective_user.id, lang)
    await update.message.reply_text(text, reply_markup=markup)
    return ConversationHandler.END


async def new_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    context.user_data["shelf_id"] = _arg(update.callback_query.data)
    await edit_safely(update.callback_query, t(lang, "note.enter_text"))
    return NOTE_TEXT


async def recv_note_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    shelf_id = context.user_data.get("shelf_id")
    text = update.message.text
    if len(text) > MAX_NOTE:
        await update.message.reply_text(t(lang, "common.too_long", max=MAX_NOTE))
        return NOTE_TEXT
    await repo.create_note(update.effective_user.id, shelf_id, text)
    context.user_data.pop("shelf_id", None)
    body, markup = await _render_shelf(update.effective_user.id, shelf_id, lang)
    await update.message.reply_text(body, reply_markup=markup)
    return ConversationHandler.END


async def edit_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    context.user_data["note_id"] = _arg(update.callback_query.data)
    await edit_safely(update.callback_query, t(lang, "note.enter_new_text"))
    return NOTE_EDIT


async def recv_note_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    note_id = context.user_data.get("note_id")
    text = update.message.text
    if len(text) > MAX_NOTE:
        await update.message.reply_text(t(lang, "common.too_long", max=MAX_NOTE))
        return NOTE_EDIT
    await repo.update_note(update.effective_user.id, note_id, text)
    context.user_data.pop("note_id", None)
    body, markup = await _render_note(update.effective_user.id, note_id, lang)
    await update.message.reply_text(body, reply_markup=markup)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    context.user_data.pop("shelf_id", None)
    context.user_data.pop("note_id", None)
    text, markup = await _render_shelf_list(update.effective_user.id, lang)
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
    register(Module(key="shelves", title_key="module.shelves", on_open=open_shelves))
    app.add_handler(_conversation)
    app.add_handler(CallbackQueryHandler(open_shelves, pattern=r"^shelf:list$"))
    app.add_handler(CallbackQueryHandler(open_shelf, pattern=r"^shelf:open:\d+$"))
    app.add_handler(CallbackQueryHandler(confirm_del_shelf, pattern=r"^shelf:del:\d+$"))
    app.add_handler(CallbackQueryHandler(do_del_shelf, pattern=r"^shelf:delyes:\d+$"))
    app.add_handler(CallbackQueryHandler(open_note, pattern=r"^note:open:\d+$"))
    app.add_handler(CallbackQueryHandler(do_del_note, pattern=r"^note:del:\d+$"))
