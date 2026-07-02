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
from core.i18n import t, user_lang
from core.registry import Module, register
from features.reminders import repo, schedule

# Состояния диалога
R_WHEN, R_TEXT, R_EDIT_TEXT, R_EDIT_WHEN = range(4)

MAX_TEXT = 4000
_HOME_CB = f"{CALLBACK_PREFIX}{HOME_KEY}"

_KIND_ORDER = (
    schedule.ONCE,
    schedule.DAILY,
    schedule.WEEKLY,
    schedule.MONTHLY,
    schedule.INTERVAL,
)


def _arg(data: str) -> int:
    return int(data.rsplit(":", 1)[1])


def _preview(lang: str, text: str, n: int = 30) -> str:
    first = (text.strip().splitlines() or [t(lang, "note.empty_preview")])[0]
    return first[:n] + ("…" if len(first) > n else "")


def _when_hint(lang: str, kind: str) -> str:
    if kind in (schedule.ONCE, schedule.WEEKLY, schedule.MONTHLY):
        return t(lang, "rem.hint.dt")
    if kind == schedule.DAILY:
        return t(lang, "rem.hint.time")
    return t(lang, "rem.hint.interval")


# ----- экраны -> (text, markup) -----

async def _render_list(tg_id: int, lang: str):
    items = await repo.list_reminders(tg_id)
    rows = []
    for r in items:
        mark = "🔔" if r.active else "🔕"
        label = f"{mark} {schedule.format_fire(r.next_fire_at)} · {_preview(lang, r.text)}"
        rows.append([InlineKeyboardButton(label, callback_data=f"rem:open:{r.id}")])
    rows.append([InlineKeyboardButton(t(lang, "rem.new_btn"), callback_data="rem:new")])
    rows.append([InlineKeyboardButton(t(lang, "common.menu_btn"), callback_data=_HOME_CB)])
    text = t(lang, "rem.title") + "\n\n" + t(lang, "rem.list_label" if items else "rem.empty")
    return text, InlineKeyboardMarkup(rows)


# Быстрые пресеты времени (коды). Подписи — i18n "rem.preset.<код>",
# вычисление -> schedule.preset_fire.
PRESET_CODES = ("in1h", "in3h", "eve", "tom_morning", "tom_eve", "weekend")


def _render_presets(lang: str):
    rows = [
        [InlineKeyboardButton(t(lang, f"rem.preset.{code}"), callback_data=f"rem:preset:{code}")]
        for code in PRESET_CODES
    ]
    rows.append([InlineKeyboardButton(t(lang, "rem.exact_btn"), callback_data="rem:kinds")])
    rows.append([InlineKeyboardButton(t(lang, "common.cancel_btn"), callback_data="rem:list")])
    return t(lang, "rem.when_q"), InlineKeyboardMarkup(rows)


def _render_kinds(lang: str):
    rows = [
        [InlineKeyboardButton(t(lang, f"rem.kind.{k}"), callback_data=f"rem:kind:{k}")]
        for k in _KIND_ORDER
    ]
    rows.append([InlineKeyboardButton(t(lang, "common.back_btn"), callback_data="rem:new")])
    return t(lang, "rem.choose_kind"), InlineKeyboardMarkup(rows)


def _cancel_kb(lang: str) -> InlineKeyboardMarkup:
    """Кнопка отмены на шагах ввода (отказаться от выбранной опции)."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t(lang, "common.cancel_btn"), callback_data="rem:cancel")]]
    )


def snooze_markup(rid: int, lang: str) -> InlineKeyboardMarkup:
    """Кнопки отложить под пришедшим напоминанием."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t(lang, "rem.snooze.10"), callback_data=f"snooze:{rid}:10"),
                InlineKeyboardButton(t(lang, "rem.snooze.60"), callback_data=f"snooze:{rid}:60"),
            ],
            [InlineKeyboardButton(t(lang, "rem.snooze.tom"), callback_data=f"snooze:{rid}:tom")],
        ]
    )


async def _render_reminder(tg_id: int, rid: int, lang: str):
    r = await repo.get_reminder(tg_id, rid)
    if r is None:
        return t(lang, "rem.not_found"), InlineKeyboardMarkup(
            [[InlineKeyboardButton(t(lang, "rem.to_list"), callback_data="rem:list")]]
        )
    text = t(
        lang,
        "rem.card",
        text=r.text,
        when=schedule.format_fire(r.next_fire_at),
        repeat=schedule.describe_repeat(lang, r.repeat_kind, r.interval_seconds),
        status=t(lang, "rem.status.active" if r.active else "rem.status.paused"),
    )
    toggle_label = t(lang, "rem.pause_btn" if r.active else "rem.resume_btn")
    rows = [
        [
            InlineKeyboardButton(t(lang, "rem.text_btn"), callback_data=f"rem:edittext:{r.id}"),
            InlineKeyboardButton(t(lang, "rem.time_btn"), callback_data=f"rem:edittime:{r.id}"),
        ],
        [
            InlineKeyboardButton(toggle_label, callback_data=f"rem:toggle:{r.id}"),
            InlineKeyboardButton(t(lang, "note.delete_btn"), callback_data=f"rem:del:{r.id}"),
        ],
        [InlineKeyboardButton(t(lang, "rem.to_list"), callback_data="rem:list")],
    ]
    return text, InlineKeyboardMarkup(rows)


async def _edit(update: Update, text: str, markup: InlineKeyboardMarkup) -> None:
    await edit_safely(update.callback_query, text, reply_markup=markup)


# ----- навигация -----

async def open_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    text, markup = await _render_list(update.effective_user.id, lang)
    await _edit(update, text, markup)


async def new_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    text, markup = _render_presets(lang)
    await _edit(update, text, markup)


async def new_kinds(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    text, markup = _render_kinds(lang)
    await _edit(update, text, markup)


async def snooze_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    _, rid, code = update.callback_query.data.split(":")
    fire = schedule.snooze_target(code)
    ok = await repo.snooze(update.effective_user.id, int(rid), fire)
    msg = (
        t(lang, "rem.snoozed_until", when=schedule.format_fire(fire))
        if ok
        else t(lang, "rem.snooze_failed")
    )
    await _edit(update, msg, None)


async def open_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    text, markup = await _render_reminder(
        update.effective_user.id, _arg(update.callback_query.data), lang
    )
    await _edit(update, text, markup)


async def toggle_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    rid = _arg(update.callback_query.data)
    current = await repo.get_reminder(update.effective_user.id, rid)
    if current is not None:
        await repo.set_active(update.effective_user.id, rid, not current.active)
    text, markup = await _render_reminder(update.effective_user.id, rid, lang)
    await _edit(update, text, markup)


async def confirm_del(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    rid = _arg(update.callback_query.data)
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "common.yes_delete"), callback_data=f"rem:delyes:{rid}")],
            [InlineKeyboardButton(t(lang, "common.cancel_btn"), callback_data=f"rem:open:{rid}")],
        ]
    )
    await _edit(update, t(lang, "rem.confirm_del"), markup)


async def do_del(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    await repo.delete_reminder(update.effective_user.id, _arg(update.callback_query.data))
    text, markup = await _render_list(update.effective_user.id, lang)
    await _edit(update, text, markup)


# ----- диалог создания -----

async def choose_preset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    code = update.callback_query.data.rsplit(":", 1)[1]
    try:
        fire = schedule.preset_fire(code)
    except schedule.ParseError as e:
        await edit_safely(update.callback_query, t(lang, e.key, **e.fmt))
        return ConversationHandler.END
    context.user_data["rem_kind"] = schedule.ONCE
    context.user_data["rem_fire"] = fire
    context.user_data["rem_interval"] = None
    await edit_safely(
        update.callback_query,
        f"⏰ {schedule.format_fire(fire)}\n\n{t(lang, 'rem.enter_text')}",
        reply_markup=_cancel_kb(lang),
    )
    return R_TEXT


async def choose_kind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    kind = update.callback_query.data.rsplit(":", 1)[1]
    context.user_data["rem_kind"] = kind
    await edit_safely(update.callback_query, _when_hint(lang, kind), reply_markup=_cancel_kb(lang))
    return R_WHEN


async def recv_when(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    kind = context.user_data.get("rem_kind", schedule.ONCE)
    try:
        fire, interval = schedule.parse_when(kind, update.message.text)
    except schedule.ParseError as e:
        await update.message.reply_text(
            t(lang, "common.try_again", err=t(lang, e.key, **e.fmt)),
            reply_markup=_cancel_kb(lang),
        )
        return R_WHEN
    context.user_data["rem_fire"] = fire
    context.user_data["rem_interval"] = interval
    await update.message.reply_text(t(lang, "rem.enter_text"), reply_markup=_cancel_kb(lang))
    return R_TEXT


async def recv_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    text = update.message.text
    if len(text) > MAX_TEXT:
        await update.message.reply_text(t(lang, "common.too_long", max=MAX_TEXT))
        return R_TEXT
    await repo.create_reminder(
        update.effective_user.id,
        text,
        context.user_data.get("rem_fire"),
        context.user_data.get("rem_kind", schedule.ONCE),
        context.user_data.get("rem_interval"),
    )
    _clear_draft(context)
    body, markup = await _render_list(update.effective_user.id, lang)
    await update.message.reply_text(
        t(lang, "rem.created") + "\n\n" + body, reply_markup=markup
    )
    return ConversationHandler.END


async def edit_text_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    context.user_data["rem_id"] = _arg(update.callback_query.data)
    await edit_safely(
        update.callback_query, t(lang, "rem.enter_new_text"), reply_markup=_cancel_kb(lang)
    )
    return R_EDIT_TEXT


async def recv_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    text = update.message.text
    if len(text) > MAX_TEXT:
        await update.message.reply_text(t(lang, "common.too_long", max=MAX_TEXT))
        return R_EDIT_TEXT
    rid = context.user_data.pop("rem_id", None)
    await repo.update_text(update.effective_user.id, rid, text)
    body, markup = await _render_reminder(update.effective_user.id, rid, lang)
    await update.message.reply_text(body, reply_markup=markup)
    return ConversationHandler.END


async def edit_time_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Правка даты/времени: переспрашиваем «когда» в формате текущего типа повтора."""
    lang = await user_lang(update, context)
    rid = _arg(update.callback_query.data)
    r = await repo.get_reminder(update.effective_user.id, rid)
    if r is None:
        await edit_safely(update.callback_query, t(lang, "rem.not_found"))
        return ConversationHandler.END
    context.user_data["rem_id"] = rid
    context.user_data["rem_kind"] = r.repeat_kind
    await edit_safely(
        update.callback_query,
        t(
            lang,
            "rem.new_time",
            kind=t(lang, f"rem.kind.{r.repeat_kind}"),
            hint=_when_hint(lang, r.repeat_kind),
        ),
        reply_markup=_cancel_kb(lang),
    )
    return R_EDIT_WHEN


async def recv_edit_when(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    kind = context.user_data.get("rem_kind", schedule.ONCE)
    rid = context.user_data.get("rem_id")
    try:
        fire, interval = schedule.parse_when(kind, update.message.text)
    except schedule.ParseError as e:
        await update.message.reply_text(
            t(lang, "common.try_again", err=t(lang, e.key, **e.fmt)),
            reply_markup=_cancel_kb(lang),
        )
        return R_EDIT_WHEN
    await repo.update_schedule(update.effective_user.id, rid, fire, kind, interval)
    _clear_draft(context)
    body, markup = await _render_reminder(update.effective_user.id, rid, lang)
    await update.message.reply_text(
        t(lang, "rem.time_updated") + "\n\n" + body, reply_markup=markup
    )
    return ConversationHandler.END


def _clear_draft(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("rem_kind", "rem_fire", "rem_interval", "rem_id"):
        context.user_data.pop(k, None)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена по команде /cancel (текстовое сообщение)."""
    lang = await user_lang(update, context)
    _clear_draft(context)
    text, markup = await _render_list(update.effective_user.id, lang)
    await update.message.reply_text(text, reply_markup=markup)
    return ConversationHandler.END


async def cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена по кнопке «⬅️ Отмена» на шаге ввода — возвращает к списку."""
    lang = await user_lang(update, context)
    _clear_draft(context)
    text, markup = await _render_list(update.effective_user.id, lang)
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
    register(Module(key="reminders", title_key="module.reminders", on_open=open_reminders))
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
