"""Модуль «Напоминания»: список/создание/просмотр/правка текста/пауза/удаление.

Навигация — инлайн-кнопки; ввод (когда + текст) — через ConversationHandler.
callback_data:
  rem:list | rem:new | rem:kind:<kind> | rem:open:<id>
  rem:edittext:<id> | rem:toggle:<id> | rem:del:<id> | rem:delyes:<id>
  rem:fmt:<dt|time|interval>  — смена формата ввода прямо на шаге «когда»
  rem:intstart:<now|date>     — старт интервала: сейчас или с указанной даты
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

# Состояния диалога: шаги дата -> время (+ интервал) идут по отдельности.
R_DATE, R_TIME, R_INT_LEN, R_INT_START, R_TEXT, R_EDIT_TEXT = range(6)

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


# Типы повтора, которым нужен шаг «дата» (у daily — только время; interval — свой поток).
_NEEDS_DATE = (schedule.ONCE, schedule.WEEKLY, schedule.MONTHLY)

# Быстрые пресеты времени (ЧЧ:ММ) и интервала — подписи совпадают с ручным вводом.
_TIME_PRESETS = ("09:00", "12:00", "15:00", "18:00", "21:00")
_INT_PRESETS = ("10m", "30m", "1h", "3h", "12h", "1d")


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


def _date_kb(lang: str) -> InlineKeyboardMarkup:
    """Шаг 1 — дата: быстрые пресеты + ручной ввод. Ничего не проскакивает."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t(lang, "rem.date_today"), callback_data="rem:date:today"),
                InlineKeyboardButton(t(lang, "rem.date_tomorrow"), callback_data="rem:date:tomorrow"),
            ],
            [InlineKeyboardButton(t(lang, "rem.date_other"), callback_data="rem:date:other")],
            [InlineKeyboardButton(t(lang, "common.cancel_btn"), callback_data="rem:cancel")],
        ]
    )


def _time_kb(lang: str, with_back: bool) -> InlineKeyboardMarkup:
    """Шаг 2 — время: пресеты ЧЧ:ММ + ручной ввод (+ «назад к дате», если она была)."""
    rows = [
        [InlineKeyboardButton(p, callback_data=f"rem:time:{p.replace(':', '')}") for p in _TIME_PRESETS[:3]],
        [InlineKeyboardButton(p, callback_data=f"rem:time:{p.replace(':', '')}") for p in _TIME_PRESETS[3:]],
        [InlineKeyboardButton(t(lang, "rem.time_custom"), callback_data="rem:time:custom")],
    ]
    if with_back:
        rows.append([InlineKeyboardButton(t(lang, "rem.time_back"), callback_data="rem:time:back")])
    rows.append([InlineKeyboardButton(t(lang, "common.cancel_btn"), callback_data="rem:cancel")])
    return InlineKeyboardMarkup(rows)


def _int_len_kb(lang: str) -> InlineKeyboardMarkup:
    """Шаг интервала: пресеты длительности + ручной ввод."""
    rows = [
        [InlineKeyboardButton(p, callback_data=f"rem:int:{p}") for p in _INT_PRESETS[:3]],
        [InlineKeyboardButton(p, callback_data=f"rem:int:{p}") for p in _INT_PRESETS[3:]],
        [InlineKeyboardButton(t(lang, "common.cancel_btn"), callback_data="rem:cancel")],
    ]
    return InlineKeyboardMarkup(rows)


def _int_start_kb(lang: str) -> InlineKeyboardMarkup:
    """Интервал задан — от какого момента отсчитывать."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "rem.int_start_now"), callback_data="rem:intstart:now")],
            [InlineKeyboardButton(t(lang, "rem.int_start_date"), callback_data="rem:intstart:date")],
            [InlineKeyboardButton(t(lang, "common.cancel_btn"), callback_data="rem:cancel")],
        ]
    )


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
            [InlineKeyboardButton(t(lang, "rem.snooze.tom_same"), callback_data=f"snooze:{rid}:tom_same")],
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
        [
            InlineKeyboardButton(t(lang, "rem.to_list"), callback_data="rem:list"),
            InlineKeyboardButton(t(lang, "common.home_btn"), callback_data=_HOME_CB),
        ],
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
    if code == "tom_same":
        # завтра в то же время — берём исходное ЧЧ:ММ напоминания
        r = await repo.get_reminder(update.effective_user.id, int(rid))
        if r is None:
            await _edit(update, t(lang, "rem.snooze_failed"), None)
            return
        fire = schedule.snooze_tomorrow_same(r.next_fire_at)
    else:
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


async def _goto_first_step(update, context, lang, kind: str, *, via_callback: bool) -> int:
    """Открывает первый нужный шаг для типа: дата / время / интервал."""
    if kind == schedule.INTERVAL:
        body, kb, state = t(lang, "rem.step_int"), _int_len_kb(lang), R_INT_LEN
    elif kind == schedule.DAILY:
        body, kb, state = t(lang, "rem.step_time"), _time_kb(lang, with_back=False), R_TIME
    else:
        body, kb, state = t(lang, "rem.step_date"), _date_kb(lang), R_DATE
    if via_callback:
        await edit_safely(update.callback_query, body, reply_markup=kb)
    else:
        await update.message.reply_text(body, reply_markup=kb)
    return state


async def choose_kind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    kind = update.callback_query.data.rsplit(":", 1)[1]
    context.user_data["rem_kind"] = kind
    context.user_data.pop("rem_date", None)
    context.user_data.pop("rem_time", None)
    return await _goto_first_step(update, context, lang, kind, via_callback=True)


# --- шаг 1: дата ---

async def _show_date_step(update, context, lang, *, via_callback: bool, err: str = "") -> int:
    body = (err + "\n\n" if err else "") + t(lang, "rem.step_date")
    if via_callback:
        await edit_safely(update.callback_query, body, reply_markup=_date_kb(lang))
    else:
        await update.message.reply_text(body, reply_markup=_date_kb(lang))
    return R_DATE


async def date_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Кнопки «Сегодня» / «Завтра»."""
    lang = await user_lang(update, context)
    which = update.callback_query.data.rsplit(":", 1)[1]
    context.user_data["rem_date"] = (
        schedule.local_today() if which == "today" else schedule.local_tomorrow()
    )
    return await _show_time_step(update, context, lang, via_callback=True)


async def date_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Кнопка «Другая дата» — просим ввести ДД.ММ.ГГГГ."""
    lang = await user_lang(update, context)
    await edit_safely(update.callback_query, t(lang, "rem.date_manual"), reply_markup=_cancel_kb(lang))
    return R_DATE


async def recv_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    try:
        context.user_data["rem_date"] = schedule.parse_date(update.message.text)
    except schedule.ParseError as e:
        await update.message.reply_text(
            t(lang, "common.try_again", err=t(lang, e.key, **e.fmt)), reply_markup=_cancel_kb(lang)
        )
        return R_DATE
    return await _show_time_step(update, context, lang, via_callback=False)


# --- шаг 2: время ---

async def _show_time_step(update, context, lang, *, via_callback: bool) -> int:
    kind = context.user_data.get("rem_kind", schedule.ONCE)
    kb = _time_kb(lang, with_back=(kind in _NEEDS_DATE or kind == schedule.INTERVAL))
    if via_callback:
        await edit_safely(update.callback_query, t(lang, "rem.step_time"), reply_markup=kb)
    else:
        await update.message.reply_text(t(lang, "rem.step_time"), reply_markup=kb)
    return R_TIME


async def time_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пресет времени (ЧЧММ в callback)."""
    lang = await user_lang(update, context)
    hhmm = update.callback_query.data.rsplit(":", 1)[1]
    context.user_data["rem_time"] = (int(hhmm[:2]), int(hhmm[2:]))
    return await _finalize(update, context, lang, via_callback=True)


async def time_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    await edit_safely(update.callback_query, t(lang, "rem.time_manual"), reply_markup=_cancel_kb(lang))
    return R_TIME


async def time_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """«Назад к дате» — вернуться на шаг даты."""
    lang = await user_lang(update, context)
    return await _show_date_step(update, context, lang, via_callback=True)


async def recv_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    try:
        context.user_data["rem_time"] = schedule.parse_hm(update.message.text)
    except schedule.ParseError as e:
        await update.message.reply_text(
            t(lang, "common.try_again", err=t(lang, e.key, **e.fmt)), reply_markup=_cancel_kb(lang)
        )
        return R_TIME
    return await _finalize(update, context, lang, via_callback=False)


# --- шаг интервала: длительность -> момент старта ---

async def int_len_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    code = update.callback_query.data.rsplit(":", 1)[1]
    context.user_data["rem_interval"] = schedule.parse_interval(code)
    await edit_safely(update.callback_query, t(lang, "rem.int_start_q"), reply_markup=_int_start_kb(lang))
    return R_INT_START


async def recv_int_len(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    try:
        context.user_data["rem_interval"] = schedule.parse_interval(update.message.text)
    except schedule.ParseError as e:
        await update.message.reply_text(
            t(lang, "common.try_again", err=t(lang, e.key, **e.fmt)), reply_markup=_int_len_kb(lang)
        )
        return R_INT_LEN
    await update.message.reply_text(t(lang, "rem.int_start_q"), reply_markup=_int_start_kb(lang))
    return R_INT_START


async def int_start_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Интервал от текущего момента."""
    lang = await user_lang(update, context)
    seconds = context.user_data.get("rem_interval") or schedule.MIN_INTERVAL_SECONDS
    context.user_data["rem_fire"] = schedule.interval_start_now(seconds)
    return await _after_when(update, context, lang, via_callback=True)


async def int_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Интервал с указанной даты — идём в обычные шаги дата -> время."""
    lang = await user_lang(update, context)
    return await _show_date_step(update, context, lang, via_callback=True)


async def _finalize(update, context, lang, *, via_callback: bool) -> int:
    """Собирает next_fire_at из выбранных даты/времени по типу и продолжает."""
    kind = context.user_data.get("rem_kind", schedule.ONCE)
    hh, mm = context.user_data["rem_time"]
    if kind == schedule.DAILY:
        context.user_data["rem_fire"] = schedule.daily_fire(hh, mm)
    else:
        d = context.user_data["rem_date"]
        fire = schedule.combine_local_to_utc(d, hh, mm)
        if kind == schedule.ONCE and fire <= schedule.now_utc():
            # выбранный момент в прошлом -> вернуть на шаг даты с пояснением
            return await _show_date_step(
                update, context, lang, via_callback=via_callback, err=t(lang, "rem.err.past")
            )
        context.user_data["rem_fire"] = fire
    return await _after_when(update, context, lang, via_callback=via_callback)


async def _after_when(
    update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str, *, via_callback: bool
) -> int:
    """Общий хвост шага «когда»: создание -> спросить текст, правка -> сохранить."""
    fire = context.user_data["rem_fire"]
    rid = context.user_data.get("rem_id")

    async def show(body: str, markup: InlineKeyboardMarkup) -> None:
        if via_callback:
            await edit_safely(update.callback_query, body, reply_markup=markup)
        else:
            await update.message.reply_text(body, reply_markup=markup)

    if rid is None:
        await show(
            f"⏰ {schedule.format_fire(fire)}\n\n{t(lang, 'rem.enter_text')}", _cancel_kb(lang)
        )
        return R_TEXT

    await repo.update_schedule(
        update.effective_user.id,
        rid,
        fire,
        context.user_data.get("rem_kind", schedule.ONCE),
        context.user_data.get("rem_interval"),
    )
    _clear_draft(context)
    body, markup = await _render_reminder(update.effective_user.id, rid, lang)
    await show(t(lang, "rem.time_updated") + "\n\n" + body, markup)
    return ConversationHandler.END


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
    """Правка даты/времени: те же пошаговые экраны (дата -> время / интервал)."""
    lang = await user_lang(update, context)
    rid = _arg(update.callback_query.data)
    r = await repo.get_reminder(update.effective_user.id, rid)
    if r is None:
        await edit_safely(update.callback_query, t(lang, "rem.not_found"))
        return ConversationHandler.END
    context.user_data["rem_id"] = rid
    context.user_data["rem_kind"] = r.repeat_kind
    context.user_data.pop("rem_date", None)
    context.user_data.pop("rem_time", None)
    return await _goto_first_step(update, context, lang, r.repeat_kind, via_callback=True)


def _clear_draft(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ("rem_kind", "rem_fire", "rem_interval", "rem_id", "rem_date", "rem_time"):
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
        R_DATE: [
            CallbackQueryHandler(date_pick, pattern=r"^rem:date:(today|tomorrow)$"),
            CallbackQueryHandler(date_other, pattern=r"^rem:date:other$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, recv_date),
        ],
        R_TIME: [
            CallbackQueryHandler(time_pick, pattern=r"^rem:time:\d{4}$"),
            CallbackQueryHandler(time_custom, pattern=r"^rem:time:custom$"),
            CallbackQueryHandler(time_back, pattern=r"^rem:time:back$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, recv_time),
        ],
        R_INT_LEN: [
            CallbackQueryHandler(int_len_pick, pattern=r"^rem:int:[0-9]+[mhd]$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, recv_int_len),
        ],
        R_INT_START: [
            CallbackQueryHandler(int_start_now, pattern=r"^rem:intstart:now$"),
            CallbackQueryHandler(int_start_date, pattern=r"^rem:intstart:date$"),
        ],
        R_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_text)],
        R_EDIT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_edit_text)],
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
    app.add_handler(CallbackQueryHandler(snooze_cb, pattern=r"^snooze:\d+:(\d+|tom|tom_same)$"))
    # запасной обработчик отмены, если диалог уже завершён (устаревший промпт)
    app.add_handler(CallbackQueryHandler(open_reminders, pattern=r"^rem:cancel$"))
    app.add_handler(CallbackQueryHandler(open_reminder, pattern=r"^rem:open:\d+$"))
    app.add_handler(CallbackQueryHandler(toggle_reminder, pattern=r"^rem:toggle:\d+$"))
    app.add_handler(CallbackQueryHandler(confirm_del, pattern=r"^rem:del:\d+$"))
    app.add_handler(CallbackQueryHandler(do_del, pattern=r"^rem:delyes:\d+$"))
