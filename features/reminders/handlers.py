"""Модуль «Напоминания»: список/создание/просмотр/правка текста/пауза/удаление.

Навигация — инлайн-кнопки; ввод (когда + текст) — через ConversationHandler.
callback_data:
  rem:list | rem:new | rem:kind:<kind> | rem:open:<id>
  rem:edittext:<id> | rem:toggle:<id> | rem:del:<id> | rem:delyes:<id>
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

from core.dashboard import CALLBACK_PREFIX, HOME_KEY
from core.registry import Module, register
from features.reminders import repo, schedule

# Состояния диалога
R_WHEN, R_TEXT, R_EDIT_TEXT = range(3)

MAX_TEXT = 4000
_HOME_CB = f"{CALLBACK_PREFIX}{HOME_KEY}"

_KIND_TITLES = {
    schedule.ONCE: "Разовое",
    schedule.DAILY: "Ежедневно",
    schedule.WEEKLY: "Еженедельно",
    schedule.INTERVAL: "Интервал",
}


def _arg(data: str) -> int:
    return int(data.rsplit(":", 1)[1])


def _preview(text: str, n: int = 30) -> str:
    first = (text.strip().splitlines() or ["(пусто)"])[0]
    return first[:n] + ("…" if len(first) > n else "")


def _when_hint(kind: str) -> str:
    if kind in (schedule.ONCE, schedule.WEEKLY):
        return "Введи дату и время: ДД.ММ.ГГГГ ЧЧ:ММ (например 25.12.2026 09:30)"
    if kind == schedule.DAILY:
        return "Введи время: ЧЧ:ММ (например 09:30)"
    return "Введи интервал: 30m / 2h / 1d (м/ч/д)"


# ----- экраны -> (text, markup) -----

async def _render_list(tg_id: int):
    items = await repo.list_reminders(tg_id)
    rows = []
    for r in items:
        mark = "🔔" if r.active else "🔕"
        label = f"{mark} {schedule.format_fire(r.next_fire_at)} · {_preview(r.text)}"
        rows.append([InlineKeyboardButton(label, callback_data=f"rem:open:{r.id}")])
    rows.append([InlineKeyboardButton("➕ Новое напоминание", callback_data="rem:new")])
    rows.append([InlineKeyboardButton("⬅️ Меню", callback_data=_HOME_CB)])
    text = "⏰ Напоминания\n\n" + ("Список:" if items else "Пока пусто.")
    return text, InlineKeyboardMarkup(rows)


def _render_kinds():
    rows = [
        [InlineKeyboardButton(_KIND_TITLES[k], callback_data=f"rem:kind:{k}")]
        for k in (schedule.ONCE, schedule.DAILY, schedule.WEEKLY, schedule.INTERVAL)
    ]
    rows.append([InlineKeyboardButton("⬅️ Отмена", callback_data="rem:list")])
    return "Выбери тип напоминания:", InlineKeyboardMarkup(rows)


async def _render_reminder(tg_id: int, rid: int):
    r = await repo.get_reminder(tg_id, rid)
    if r is None:
        return "Напоминание не найдено.", InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ К списку", callback_data="rem:list")]]
        )
    status = "активно" if r.active else "на паузе"
    text = (
        f"⏰ Напоминание\n\n"
        f"Текст: {r.text}\n"
        f"Когда: {schedule.format_fire(r.next_fire_at)}\n"
        f"Повтор: {schedule.describe_repeat(r.repeat_kind, r.interval_seconds)}\n"
        f"Статус: {status}"
    )
    toggle_label = "⏸ Пауза" if r.active else "▶️ Возобновить"
    rows = [
        [
            InlineKeyboardButton("✏️ Текст", callback_data=f"rem:edittext:{r.id}"),
            InlineKeyboardButton(toggle_label, callback_data=f"rem:toggle:{r.id}"),
        ],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"rem:del:{r.id}")],
        [InlineKeyboardButton("⬅️ К списку", callback_data="rem:list")],
    ]
    return text, InlineKeyboardMarkup(rows)


async def _edit(update: Update, text: str, markup: InlineKeyboardMarkup) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text, reply_markup=markup)


# ----- навигация -----

async def open_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, markup = await _render_list(update.effective_user.id)
    await _edit(update, text, markup)


async def new_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, markup = _render_kinds()
    await _edit(update, text, markup)


async def open_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, markup = await _render_reminder(update.effective_user.id, _arg(update.callback_query.data))
    await _edit(update, text, markup)


async def toggle_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rid = _arg(update.callback_query.data)
    current = await repo.get_reminder(update.effective_user.id, rid)
    if current is not None:
        await repo.set_active(update.effective_user.id, rid, not current.active)
    text, markup = await _render_reminder(update.effective_user.id, rid)
    await _edit(update, text, markup)


async def confirm_del(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rid = _arg(update.callback_query.data)
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f"rem:delyes:{rid}")],
            [InlineKeyboardButton("⬅️ Отмена", callback_data=f"rem:open:{rid}")],
        ]
    )
    await _edit(update, "Удалить напоминание?", markup)


async def do_del(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await repo.delete_reminder(update.effective_user.id, _arg(update.callback_query.data))
    text, markup = await _render_list(update.effective_user.id)
    await _edit(update, text, markup)


# ----- диалог создания -----

async def choose_kind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    kind = update.callback_query.data.rsplit(":", 1)[1]
    context.user_data["rem_kind"] = kind
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(_when_hint(kind))
    return R_WHEN


async def recv_when(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    kind = context.user_data.get("rem_kind", schedule.ONCE)
    try:
        fire, interval = schedule.parse_when(kind, update.message.text)
    except schedule.ParseError as e:
        await update.message.reply_text(f"⚠️ {e}\nПопробуй ещё раз:")
        return R_WHEN
    context.user_data["rem_fire"] = fire
    context.user_data["rem_interval"] = interval
    await update.message.reply_text("Теперь введи текст напоминания:")
    return R_TEXT


async def recv_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if len(text) > MAX_TEXT:
        await update.message.reply_text(f"Слишком длинно (макс {MAX_TEXT}). Введи короче:")
        return R_TEXT
    await repo.create_reminder(
        update.effective_user.id,
        text,
        context.user_data.get("rem_fire"),
        context.user_data.get("rem_kind", schedule.ONCE),
        context.user_data.get("rem_interval"),
    )
    for k in ("rem_kind", "rem_fire", "rem_interval"):
        context.user_data.pop(k, None)
    body, markup = await _render_list(update.effective_user.id)
    await update.message.reply_text("✅ Напоминание создано.\n\n" + body, reply_markup=markup)
    return ConversationHandler.END


async def edit_text_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["rem_id"] = _arg(update.callback_query.data)
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Введи новый текст напоминания:")
    return R_EDIT_TEXT


async def recv_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if len(text) > MAX_TEXT:
        await update.message.reply_text(f"Слишком длинно (макс {MAX_TEXT}). Введи короче:")
        return R_EDIT_TEXT
    rid = context.user_data.pop("rem_id", None)
    await repo.update_text(update.effective_user.id, rid, text)
    body, markup = await _render_reminder(update.effective_user.id, rid)
    await update.message.reply_text(body, reply_markup=markup)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for k in ("rem_kind", "rem_fire", "rem_interval", "rem_id"):
        context.user_data.pop(k, None)
    text, markup = await _render_list(update.effective_user.id)
    await update.message.reply_text(text, reply_markup=markup)
    return ConversationHandler.END


_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(choose_kind, pattern=r"^rem:kind:(once|daily|weekly|interval)$"),
        CallbackQueryHandler(edit_text_entry, pattern=r"^rem:edittext:\d+$"),
    ],
    states={
        R_WHEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_when)],
        R_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_text)],
        R_EDIT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_edit_text)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_message=False,
)


def setup(app: Application) -> None:
    register(Module(key="reminders", title="⏰ Напоминания", on_open=open_reminders))
    app.add_handler(_conversation)
    app.add_handler(CallbackQueryHandler(open_reminders, pattern=r"^rem:list$"))
    app.add_handler(CallbackQueryHandler(new_reminder, pattern=r"^rem:new$"))
    app.add_handler(CallbackQueryHandler(open_reminder, pattern=r"^rem:open:\d+$"))
    app.add_handler(CallbackQueryHandler(toggle_reminder, pattern=r"^rem:toggle:\d+$"))
    app.add_handler(CallbackQueryHandler(confirm_del, pattern=r"^rem:del:\d+$"))
    app.add_handler(CallbackQueryHandler(do_del, pattern=r"^rem:delyes:\d+$"))
