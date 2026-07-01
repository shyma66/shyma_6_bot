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

from core.dashboard import CALLBACK_PREFIX, HOME_KEY, edit_safely
from core.registry import Module, register
from features.reminders import repo, schedule

# Состояния диалога
R_WHEN, R_TEXT, R_EDIT_TEXT, R_EDIT_WHEN = range(4)

MAX_TEXT = 4000
_HOME_CB = f"{CALLBACK_PREFIX}{HOME_KEY}"

_KIND_TITLES = {
    schedule.ONCE: "Разовое",
    schedule.DAILY: "Ежедневно",
    schedule.WEEKLY: "Еженедельно",
    schedule.MONTHLY: "Ежемесячно",
    schedule.INTERVAL: "Интервал",
}
_KIND_ORDER = (
    schedule.ONCE,
    schedule.DAILY,
    schedule.WEEKLY,
    schedule.MONTHLY,
    schedule.INTERVAL,
)


def _arg(data: str) -> int:
    return int(data.rsplit(":", 1)[1])


def _preview(text: str, n: int = 30) -> str:
    first = (text.strip().splitlines() or ["(пусто)"])[0]
    return first[:n] + ("…" if len(first) > n else "")


def _when_hint(kind: str) -> str:
    if kind in (schedule.ONCE, schedule.WEEKLY, schedule.MONTHLY):
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


# Быстрые пресеты времени (code -> подпись). Вычисление -> schedule.preset_fire.
PRESETS = [
    ("in1h", "⏱ Через 1 час"),
    ("in3h", "⏱ Через 3 часа"),
    ("eve", "🌙 Сегодня вечером"),
    ("tom_morning", "☀️ Завтра утром"),
    ("tom_eve", "🌆 Завтра вечером"),
    ("weekend", "📅 В выходные"),
]


def _render_presets():
    rows = [
        [InlineKeyboardButton(label, callback_data=f"rem:preset:{code}")]
        for code, label in PRESETS
    ]
    rows.append([InlineKeyboardButton("⚙️ Точное время / повтор", callback_data="rem:kinds")])
    rows.append([InlineKeyboardButton("⬅️ Отмена", callback_data="rem:list")])
    return "Когда напомнить?", InlineKeyboardMarkup(rows)


def _render_kinds():
    rows = [
        [InlineKeyboardButton(_KIND_TITLES[k], callback_data=f"rem:kind:{k}")]
        for k in _KIND_ORDER
    ]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="rem:new")])
    return "Выбери тип напоминания:", InlineKeyboardMarkup(rows)


def _cancel_kb() -> InlineKeyboardMarkup:
    """Кнопка отмены на шагах ввода (отказаться от выбранной опции)."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Отмена", callback_data="rem:cancel")]]
    )


def snooze_markup(rid: int) -> InlineKeyboardMarkup:
    """Кнопки отложить под пришедшим напоминанием."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("💤 +10 мин", callback_data=f"snooze:{rid}:10"),
                InlineKeyboardButton("💤 +1 час", callback_data=f"snooze:{rid}:60"),
            ],
            [InlineKeyboardButton("💤 Завтра 09:00", callback_data=f"snooze:{rid}:tom")],
        ]
    )


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
            InlineKeyboardButton("🕐 Время", callback_data=f"rem:edittime:{r.id}"),
        ],
        [
            InlineKeyboardButton(toggle_label, callback_data=f"rem:toggle:{r.id}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"rem:del:{r.id}"),
        ],
        [InlineKeyboardButton("⬅️ К списку", callback_data="rem:list")],
    ]
    return text, InlineKeyboardMarkup(rows)


async def _edit(update: Update, text: str, markup: InlineKeyboardMarkup) -> None:
    await edit_safely(update.callback_query, text, reply_markup=markup)


# ----- навигация -----

async def open_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, markup = await _render_list(update.effective_user.id)
    await _edit(update, text, markup)


async def new_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, markup = _render_presets()
    await _edit(update, text, markup)


async def new_kinds(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, markup = _render_kinds()
    await _edit(update, text, markup)


async def snooze_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, rid, code = update.callback_query.data.split(":")
    fire = schedule.snooze_target(code)
    ok = await repo.snooze(update.effective_user.id, int(rid), fire)
    msg = (
        f"💤 Отложено до {schedule.format_fire(fire)}"
        if ok
        else "Не удалось отложить (напоминание не найдено)."
    )
    await _edit(update, msg, None)


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

async def choose_preset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.callback_query.data.rsplit(":", 1)[1]
    try:
        fire = schedule.preset_fire(code)
    except schedule.ParseError:
        await edit_safely(update.callback_query, "Неизвестный пресет.")
        return ConversationHandler.END
    context.user_data["rem_kind"] = schedule.ONCE
    context.user_data["rem_fire"] = fire
    context.user_data["rem_interval"] = None
    await edit_safely(
        update.callback_query,
        f"⏰ {schedule.format_fire(fire)}\n\nТеперь введи текст напоминания:",
        reply_markup=_cancel_kb(),
    )
    return R_TEXT


async def choose_kind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    kind = update.callback_query.data.rsplit(":", 1)[1]
    context.user_data["rem_kind"] = kind
    await edit_safely(update.callback_query, _when_hint(kind), reply_markup=_cancel_kb())
    return R_WHEN


async def recv_when(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    kind = context.user_data.get("rem_kind", schedule.ONCE)
    try:
        fire, interval = schedule.parse_when(kind, update.message.text)
    except schedule.ParseError as e:
        await update.message.reply_text(f"⚠️ {e}\nПопробуй ещё раз:", reply_markup=_cancel_kb())
        return R_WHEN
    context.user_data["rem_fire"] = fire
    context.user_data["rem_interval"] = interval
    await update.message.reply_text("Теперь введи текст напоминания:", reply_markup=_cancel_kb())
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
    await edit_safely(
        update.callback_query, "Введи новый текст напоминания:", reply_markup=_cancel_kb()
    )
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


async def edit_time_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Правка даты/времени: переспрашиваем «когда» в формате текущего типа повтора."""
    rid = _arg(update.callback_query.data)
    r = await repo.get_reminder(update.effective_user.id, rid)
    if r is None:
        await edit_safely(update.callback_query, "Напоминание не найдено.")
        return ConversationHandler.END
    context.user_data["rem_id"] = rid
    context.user_data["rem_kind"] = r.repeat_kind
    hint = _when_hint(r.repeat_kind)
    await edit_safely(
        update.callback_query,
        f"🕐 Новое время ({_KIND_TITLES.get(r.repeat_kind, '')}).\n{hint}",
        reply_markup=_cancel_kb(),
    )
    return R_EDIT_WHEN


async def recv_edit_when(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    kind = context.user_data.get("rem_kind", schedule.ONCE)
    rid = context.user_data.get("rem_id")
    try:
        fire, interval = schedule.parse_when(kind, update.message.text)
    except schedule.ParseError as e:
        await update.message.reply_text(f"⚠️ {e}\nПопробуй ещё раз:", reply_markup=_cancel_kb())
        return R_EDIT_WHEN
    await repo.update_schedule(update.effective_user.id, rid, fire, kind, interval)
    _clear_draft(context)
    body, markup = await _render_reminder(update.effective_user.id, rid)
    await update.message.reply_text("✅ Время обновлено.\n\n" + body, reply_markup=markup)
    return ConversationHandler.END


def _clear_draft(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("rem_kind", "rem_fire", "rem_interval", "rem_id"):
        context.user_data.pop(k, None)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена по команде /cancel (текстовое сообщение)."""
    _clear_draft(context)
    text, markup = await _render_list(update.effective_user.id)
    await update.message.reply_text(text, reply_markup=markup)
    return ConversationHandler.END


async def cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена по кнопке «⬅️ Отмена» на шаге ввода — возвращает к списку."""
    _clear_draft(context)
    text, markup = await _render_list(update.effective_user.id)
    await _edit(update, text, markup)
    return ConversationHandler.END


_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(choose_preset, pattern=r"^rem:preset:[a-z0-9_]+$"),
        CallbackQueryHandler(
            choose_kind, pattern=r"^rem:kind:(once|daily|weekly|monthly|interval)$"
        ),
        CallbackQueryHandler(edit_text_entry, pattern=r"^rem:edittext:\d+$"),
        CallbackQueryHandler(edit_time_entry, pattern=r"^rem:edittime:\d+$"),
    ],
    states={
        R_WHEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_when)],
        R_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_text)],
        R_EDIT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_edit_text)],
        R_EDIT_WHEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_edit_when)],
    },
    fallbacks=[
        CommandHandler("cancel", cancel),
        CallbackQueryHandler(cancel_cb, pattern=r"^rem:cancel$"),
    ],
    per_message=False,
)


def setup(app: Application) -> None:
    register(Module(key="reminders", title="⏰ Напоминания", on_open=open_reminders))
    app.add_handler(_conversation)
    app.add_handler(CallbackQueryHandler(open_reminders, pattern=r"^rem:list$"))
    app.add_handler(CallbackQueryHandler(new_reminder, pattern=r"^rem:new$"))
    app.add_handler(CallbackQueryHandler(new_kinds, pattern=r"^rem:kinds$"))
    app.add_handler(CallbackQueryHandler(snooze_cb, pattern=r"^snooze:\d+:(\d+|tom)$"))
    # запасной обработчик отмены, если диалог уже завершён (устаревший промпт)
    app.add_handler(CallbackQueryHandler(open_reminders, pattern=r"^rem:cancel$"))
    app.add_handler(CallbackQueryHandler(open_reminder, pattern=r"^rem:open:\d+$"))
    app.add_handler(CallbackQueryHandler(toggle_reminder, pattern=r"^rem:toggle:\d+$"))
    app.add_handler(CallbackQueryHandler(confirm_del, pattern=r"^rem:del:\d+$"))
    app.add_handler(CallbackQueryHandler(do_del, pattern=r"^rem:delyes:\d+$"))
