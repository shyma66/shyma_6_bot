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

from core.dashboard import CALLBACK_PREFIX, HOME_KEY, answer_safely, edit_safely, show_dashboard
from core.i18n import t, user_lang
from core.registry import Module, register
from features.reminders import repo, schedule

# Состояния диалога: шаги дата -> время (+ интервал) идут по отдельности.
R_DATE, R_TIME, R_INT_UNIT, R_INT_GRID, R_INT_START, R_TEXT, R_EDIT_TEXT = range(7)

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


# ----- экраны -> (text, markup) -----

async def _render_list(tg_id: int, lang: str):
    items = await repo.list_reminders(tg_id)
    rows = []
    for r in items:
        mark = "🔔" if r.active else "🔕"
        label = f"{mark} {schedule.format_fire(r.next_fire_at)} · {_preview(lang, r.text)}"
        rows.append([InlineKeyboardButton(label, callback_data=f"rem:open:{r.id}")])
    rows.append([InlineKeyboardButton(t(lang, "rem.new_btn"), callback_data="rem:new")])
    if items:
        rows.append([InlineKeyboardButton(t(lang, "rem.select_btn"), callback_data="rem:edit")])
    rows.append([InlineKeyboardButton(t(lang, "common.menu_btn"), callback_data=_HOME_CB)])
    text = t(lang, "rem.title") + "\n\n" + t(lang, "rem.list_label" if items else "rem.empty")
    return text, InlineKeyboardMarkup(rows)


async def _render_select(tg_id: int, lang: str, selected: set[int]):
    """Режим выбора: галочки на напоминаниях + удалить выбранные/все."""
    items = await repo.list_reminders(tg_id)
    rows = []
    for r in items:
        box = "☑️" if r.id in selected else "☐"
        label = f"{box} {schedule.format_fire(r.next_fire_at)} · {_preview(lang, r.text)}"
        rows.append([InlineKeyboardButton(label, callback_data=f"rem:mark:{r.id}")])
    all_ids = {r.id for r in items}
    toggle_all = "rem.desel_all" if selected >= all_ids and all_ids else "rem.sel_all"
    rows.append(
        [
            InlineKeyboardButton(t(lang, toggle_all), callback_data="rem:markall"),
            InlineKeyboardButton(
                t(lang, "rem.del_selected", n=len(selected)), callback_data="rem:delsel"
            ),
        ]
    )
    rows.append([InlineKeyboardButton(t(lang, "rem.del_all"), callback_data="rem:delall")])
    rows.append(
        [
            InlineKeyboardButton(t(lang, "rem.done_btn"), callback_data="rem:list"),
            InlineKeyboardButton(t(lang, "common.home_btn"), callback_data=_HOME_CB),
        ]
    )
    return t(lang, "rem.select_title"), InlineKeyboardMarkup(rows)


# Быстрый выбор «когда» устроен папками:
#   ⏱ Часы -> [🕐 В котором часу 00–23] / [⏱ Через N часов 1–24]
#   📅 Дни  -> [1][2][3][неделя][месяц][полгода][год][своё] -> шаг времени
#   ⚙️ Точное время / повтор -> тип повтора + интервал (пошагово)
_DAY_NAMED = ("week", "month", "halfyear", "year")
_DAY_CODE_RE = r"(\d{1,2}|week|month|halfyear|year)"


def _grid(buttons: list, cols: int = 4) -> list:
    return [buttons[i:i + cols] for i in range(0, len(buttons), cols)]


def _nav_row(lang: str, back_cb: str):
    return [
        InlineKeyboardButton(t(lang, "common.back_btn"), callback_data=back_cb),
        InlineKeyboardButton(t(lang, "common.home_btn"), callback_data=_HOME_CB),
    ]


def _cancel_home_row(lang: str):
    """Нижняя строка шагов ввода: «Отмена» (шаг назад) + «Домой» (старт)."""
    return [
        InlineKeyboardButton(t(lang, "common.cancel_btn"), callback_data="rem:cancel"),
        InlineKeyboardButton(t(lang, "common.home_btn"), callback_data=_HOME_CB),
    ]


def _render_when_main(lang: str):
    rows = [
        [InlineKeyboardButton(t(lang, "rem.folder_hours"), callback_data="rem:folder:hours")],
        [InlineKeyboardButton(t(lang, "rem.folder_days"), callback_data="rem:folder:days")],
        [InlineKeyboardButton(t(lang, "rem.exact_btn"), callback_data="rem:kinds")],
        [InlineKeyboardButton(t(lang, "common.cancel_btn"), callback_data="rem:list")],
    ]
    return t(lang, "rem.when_q"), InlineKeyboardMarkup(rows)


def _render_hours_folder(lang: str):
    rows = [
        [InlineKeyboardButton(t(lang, "rem.hclock_btn"), callback_data="rem:hclock")],
        [InlineKeyboardButton(t(lang, "rem.hrel_btn"), callback_data="rem:hrel")],
        _nav_row(lang, "rem:new"),
    ]
    return t(lang, "rem.hours_title"), InlineKeyboardMarkup(rows)


def _render_clock(lang: str):
    btns = [InlineKeyboardButton(f"{h:02d}:00", callback_data=f"rem:hat:{h}") for h in range(24)]
    rows = _grid(btns) + [_nav_row(lang, "rem:folder:hours")]
    return t(lang, "rem.hclock_title"), InlineKeyboardMarkup(rows)


def _render_hrel(lang: str):
    btns = [InlineKeyboardButton(str(n), callback_data=f"rem:hin:{n}") for n in range(1, 25)]
    rows = _grid(btns) + [_nav_row(lang, "rem:folder:hours")]
    return t(lang, "rem.hrel_title"), InlineKeyboardMarkup(rows)


def _render_days(lang: str):
    """Папка дни: сетка 1–30 (как часы) + неделя/месяц/полгода/год."""
    nums = [InlineKeyboardButton(str(n), callback_data=f"rem:dday:{n}") for n in range(1, 31)]
    rows = _grid(nums, 6)
    named = [
        InlineKeyboardButton(t(lang, f"rem.d.{c}"), callback_data=f"rem:dday:{c}")
        for c in _DAY_NAMED
    ]
    rows += _grid(named, 2)
    rows.append(_nav_row(lang, "rem:new"))
    return t(lang, "rem.days_title"), InlineKeyboardMarkup(rows)


def _render_kinds(lang: str):
    rows = [
        [InlineKeyboardButton(t(lang, f"rem.kind.{k}"), callback_data=f"rem:kind:{k}")]
        for k in _KIND_ORDER
    ]
    rows.append(_nav_row(lang, "rem:new"))
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
            _cancel_home_row(lang),
        ]
    )


def _time_kb(lang: str, with_back: bool) -> InlineKeyboardMarkup:
    """Шаг 2 — время: полная сетка часов 00–23 (тап -> ровно/минуты) + ручной ввод."""
    btns = [InlineKeyboardButton(f"{h:02d}:00", callback_data=f"rem:time:{h:02d}00") for h in range(24)]
    rows = _grid(btns, 6)
    rows.append([InlineKeyboardButton(t(lang, "rem.time_custom"), callback_data="rem:time:custom")])
    if with_back:
        rows.append([InlineKeyboardButton(t(lang, "rem.time_back"), callback_data="rem:time:back")])
    rows.append(_cancel_home_row(lang))
    return InlineKeyboardMarkup(rows)


# Интервал: единицы и сетки N (по образцу папок).
_INT_UNITS = ("min", "hour", "day")
_INT_UNIT_SECONDS = {"min": 60, "hour": 3600, "day": 86400}
_INT_GRID = {"min": range(5, 60, 5), "hour": range(1, 25), "day": range(1, 31)}


def _int_units_kb(lang: str) -> InlineKeyboardMarkup:
    """Интервал: выбор единицы (каждые минуты / часы / дни)."""
    rows = [[InlineKeyboardButton(t(lang, f"rem.int_unit.{u}"), callback_data=f"rem:iunit:{u}") for u in _INT_UNITS]]
    rows.append(_cancel_home_row(lang))
    return InlineKeyboardMarkup(rows)


def _int_grid_kb(lang: str, unit: str) -> InlineKeyboardMarkup:
    """Интервал: сетка N для выбранной единицы."""
    btns = [InlineKeyboardButton(str(n), callback_data=f"rem:iset:{unit}:{n}") for n in _INT_GRID[unit]]
    rows = _grid(btns, 6) + [_nav_row(lang, "rem:iunits")]
    return InlineKeyboardMarkup(rows)


def _int_start_kb(lang: str) -> InlineKeyboardMarkup:
    """Интервал задан — от какого момента отсчитывать."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "rem.int_start_now"), callback_data="rem:intstart:now")],
            [InlineKeyboardButton(t(lang, "rem.int_start_date"), callback_data="rem:intstart:date")],
            _cancel_home_row(lang),
        ]
    )


def _cancel_kb(lang: str) -> InlineKeyboardMarkup:
    """Отмена (шаг назад) + Домой на шагах ввода."""
    return InlineKeyboardMarkup([_cancel_home_row(lang)])


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
            [[
                InlineKeyboardButton(t(lang, "rem.to_list"), callback_data="rem:list"),
                InlineKeyboardButton(t(lang, "common.home_btn"), callback_data=_HOME_CB),
            ]]
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
    context.user_data.pop("rem_sel", None)  # выход из режима выбора
    text, markup = await _render_list(update.effective_user.id, lang)
    await _edit(update, text, markup)


# ----- режим выбора (массовое удаление) -----

def _sel(context: ContextTypes.DEFAULT_TYPE) -> set[int]:
    return context.user_data.setdefault("rem_sel", set())


async def _show_select(update, context, lang) -> None:
    text, markup = await _render_select(update.effective_user.id, lang, _sel(context))
    await _edit(update, text, markup)


async def open_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Вход в режим выбора (галочки)."""
    lang = await user_lang(update, context)
    context.user_data["rem_sel"] = set()
    await _show_select(update, context, lang)


async def toggle_mark(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    rid = _arg(update.callback_query.data)
    sel = _sel(context)
    sel.discard(rid) if rid in sel else sel.add(rid)
    await _show_select(update, context, lang)


async def toggle_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    items = await repo.list_reminders(update.effective_user.id)
    all_ids = {r.id for r in items}
    sel = _sel(context)
    context.user_data["rem_sel"] = set() if sel >= all_ids and all_ids else all_ids
    await _show_select(update, context, lang)


async def del_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    sel = _sel(context)
    if not sel:
        await answer_safely(update.callback_query, t(lang, "rem.none_selected"), show_alert=True)
        return
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "common.yes_delete"), callback_data="rem:delselyes")],
            [InlineKeyboardButton(t(lang, "common.cancel_btn"), callback_data="rem:edit")],
        ]
    )
    await _edit(update, t(lang, "rem.confirm_del_sel", n=len(sel)), markup)


async def del_selected_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    ids = list(_sel(context))
    n = await repo.delete_reminders(update.effective_user.id, ids)
    context.user_data.pop("rem_sel", None)
    body, markup = await _render_list(update.effective_user.id, lang)
    await _edit(update, t(lang, "rem.deleted_n", n=n) + "\n\n" + body, markup)


async def del_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "common.yes_delete"), callback_data="rem:delallyes")],
            [InlineKeyboardButton(t(lang, "common.cancel_btn"), callback_data="rem:edit")],
        ]
    )
    await _edit(update, t(lang, "rem.confirm_del_all"), markup)


async def del_all_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    n = await repo.delete_all_reminders(update.effective_user.id)
    context.user_data.pop("rem_sel", None)
    body, markup = await _render_list(update.effective_user.id, lang)
    await _edit(update, t(lang, "rem.deleted_n", n=n) + "\n\n" + body, markup)


async def new_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    text, markup = _render_when_main(lang)
    await _edit(update, text, markup)


async def new_kinds(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    text, markup = _render_kinds(lang)
    await _edit(update, text, markup)


async def folder_hours(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    text, markup = _render_hours_folder(lang)
    await _edit(update, text, markup)


async def screen_clock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    text, markup = _render_clock(lang)
    await _edit(update, text, markup)


async def screen_hrel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    text, markup = _render_hrel(lang)
    await _edit(update, text, markup)


async def folder_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    text, markup = _render_days(lang)
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

async def _start_once_fire(update, context, lang, fire) -> int:
    """Разовое напоминание на готовый момент -> сразу спросить текст."""
    context.user_data["rem_kind"] = schedule.ONCE
    context.user_data["rem_fire"] = fire
    context.user_data["rem_interval"] = None
    context.user_data.pop("rem_date", None)
    context.user_data.pop("rem_time", None)
    await edit_safely(
        update.callback_query,
        f"⏰ {schedule.format_fire(fire)}\n\n{t(lang, 'rem.enter_text')}",
        reply_markup=_cancel_kb(lang),
    )
    return R_TEXT


async def clock_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Папка часы -> выбран час HH: спросить «ровно HH:00 или минуты».

    Экраны выбора часа/минут — навигация (вне диалога); в диалог входим только
    финальным выбором rem:cset:H:M (см. clock_set).
    """
    lang = await user_lang(update, context)
    h = int(update.callback_query.data.rsplit(":", 1)[1])
    hh = f"{h:02d}"
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "rem.time_exact_btn", h=hh), callback_data=f"rem:cset:{h}:0")],
            [InlineKeyboardButton(t(lang, "rem.time_mins_btn"), callback_data=f"rem:cmins:{h}")],
            _nav_row(lang, "rem:hclock"),
        ]
    )
    await edit_safely(update.callback_query, t(lang, "rem.time_choice", h=hh), reply_markup=kb)


async def clock_minutes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Сетка минут 00,05,…,55 для выбранного часа (папка часы)."""
    lang = await user_lang(update, context)
    h = int(update.callback_query.data.rsplit(":", 1)[1])
    btns = [InlineKeyboardButton(f"{m:02d}", callback_data=f"rem:cset:{h}:{m}") for m in range(0, 60, 5)]
    rows = _grid(btns) + [_nav_row(lang, f"rem:hat:{h}")]
    await edit_safely(
        update.callback_query,
        t(lang, "rem.time_mins_title", h=f"{h:02d}"),
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def clock_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Итог папки часы: HH:MM сегодня/завтра -> вход в диалог, спросить текст."""
    lang = await user_lang(update, context)
    _, _, h, m = update.callback_query.data.split(":")
    return await _start_once_fire(update, context, lang, schedule.at_clock_min(int(h), int(m)))


async def hour_in(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Папка часы -> через N часов от сейчас."""
    lang = await user_lang(update, context)
    n = int(update.callback_query.data.rsplit(":", 1)[1])
    return await _start_once_fire(update, context, lang, schedule.in_hours(n))


async def day_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Папка дни -> выбран день: «то же время что сейчас» или «своё время».

    Экраны дня/часа/минут — навигация (вне диалога); в диалог входим финальным
    выбором (rem:dnow / rem:dset).
    """
    lang = await user_lang(update, context)
    code = update.callback_query.data.rsplit(":", 1)[1]
    now_l = schedule.to_local(schedule.now_utc())
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(
                t(lang, "rem.day_same", hm=now_l.strftime("%H:%M")),
                callback_data=f"rem:dnow:{code}",
            )],
            [InlineKeyboardButton(t(lang, "rem.day_other_time"), callback_data=f"rem:dhour:{code}")],
            _nav_row(lang, "rem:folder:days"),
        ]
    )
    await edit_safely(update.callback_query, t(lang, "rem.day_time_q"), reply_markup=kb)


async def day_hour_grid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Своё время: сетка часов 00–23 для выбранного дня."""
    lang = await user_lang(update, context)
    code = update.callback_query.data.rsplit(":", 1)[1]
    btns = [InlineKeyboardButton(f"{h:02d}:00", callback_data=f"rem:dh:{code}:{h}") for h in range(24)]
    rows = _grid(btns) + [_nav_row(lang, f"rem:dday:{code}")]
    await edit_safely(update.callback_query, t(lang, "rem.hclock_title"), reply_markup=InlineKeyboardMarkup(rows))


async def day_hour_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Своё время: выбран час -> «ровно HH:00 или минуты» (для выбранного дня)."""
    lang = await user_lang(update, context)
    _, _, code, h = update.callback_query.data.split(":")
    hh = f"{int(h):02d}"
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "rem.time_exact_btn", h=hh), callback_data=f"rem:dset:{code}:{h}:0")],
            [InlineKeyboardButton(t(lang, "rem.time_mins_btn"), callback_data=f"rem:dm:{code}:{h}")],
            _nav_row(lang, f"rem:dhour:{code}"),
        ]
    )
    await edit_safely(update.callback_query, t(lang, "rem.time_choice", h=hh), reply_markup=kb)


async def day_min_grid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Своё время: сетка минут 00,05,…,55 для выбранного дня и часа."""
    lang = await user_lang(update, context)
    _, _, code, h = update.callback_query.data.split(":")
    btns = [InlineKeyboardButton(f"{m:02d}", callback_data=f"rem:dset:{code}:{h}:{m}") for m in range(0, 60, 5)]
    rows = _grid(btns) + [_nav_row(lang, f"rem:dh:{code}:{h}")]
    await edit_safely(
        update.callback_query,
        t(lang, "rem.time_mins_title", h=f"{int(h):02d}"),
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def day_same_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Итог: через N дней в то же время, что сейчас -> текст."""
    lang = await user_lang(update, context)
    code = update.callback_query.data.rsplit(":", 1)[1]
    now_l = schedule.to_local(schedule.now_utc())
    fire = schedule.combine_local_to_utc(schedule.date_for_day_code(code), now_l.hour, now_l.minute)
    return await _start_once_fire(update, context, lang, fire)


async def day_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Итог: через N дней в выбранное HH:MM -> текст."""
    lang = await user_lang(update, context)
    _, _, code, h, m = update.callback_query.data.split(":")
    fire = schedule.combine_local_to_utc(schedule.date_for_day_code(code), int(h), int(m))
    return await _start_once_fire(update, context, lang, fire)


async def _goto_first_step(update, context, lang, kind: str, *, via_callback: bool) -> int:
    """Открывает первый нужный шаг для типа: дата / время / интервал."""
    if kind == schedule.INTERVAL:
        body, kb, state = t(lang, "rem.int_unit_q"), _int_units_kb(lang), R_INT_UNIT
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
    """Пресет часа (ЧЧММ в callback) -> спросить: ровно HH:00 или выбрать минуты."""
    lang = await user_lang(update, context)
    hhmm = update.callback_query.data.rsplit(":", 1)[1]
    h = int(hhmm[:2])
    hh = f"{h:02d}"
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "rem.time_exact_btn", h=hh), callback_data=f"rem:tset:{h}:0")],
            [InlineKeyboardButton(t(lang, "rem.time_mins_btn"), callback_data=f"rem:tmins:{h}")],
            [InlineKeyboardButton(t(lang, "common.back_btn"), callback_data="rem:tstep")],
        ]
    )
    await edit_safely(update.callback_query, t(lang, "rem.time_choice", h=hh), reply_markup=kb)
    return R_TIME


async def time_minutes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сетка минут 00, 05, …, 55 для выбранного часа."""
    lang = await user_lang(update, context)
    h = int(update.callback_query.data.rsplit(":", 1)[1])
    btns = [InlineKeyboardButton(f"{m:02d}", callback_data=f"rem:tset:{h}:{m}") for m in range(0, 60, 5)]
    rows = _grid(btns) + [[InlineKeyboardButton(t(lang, "common.back_btn"), callback_data="rem:tstep")]]
    await edit_safely(
        update.callback_query,
        t(lang, "rem.time_mins_title", h=f"{h:02d}"),
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return R_TIME


async def time_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Итоговое время выбрано (rem:tset:H:M) -> собрать напоминание."""
    lang = await user_lang(update, context)
    _, _, h, m = update.callback_query.data.split(":")
    context.user_data["rem_time"] = (int(h), int(m))
    return await _finalize(update, context, lang, via_callback=True)


async def time_step_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Назад к сетке пресетов времени (из экрана «ровно/минуты»)."""
    lang = await user_lang(update, context)
    return await _show_time_step(update, context, lang, via_callback=True)


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

async def int_unit_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Интервал: выбрана единица -> сетка N."""
    lang = await user_lang(update, context)
    unit = update.callback_query.data.rsplit(":", 1)[1]
    await edit_safely(
        update.callback_query, t(lang, "rem.int_n_q"), reply_markup=_int_grid_kb(lang, unit)
    )
    return R_INT_GRID


async def int_n_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Интервал: выбрано N -> «с какого момента»."""
    lang = await user_lang(update, context)
    _, _, unit, n = update.callback_query.data.split(":")
    context.user_data["rem_interval"] = int(n) * _INT_UNIT_SECONDS[unit]
    await edit_safely(update.callback_query, t(lang, "rem.int_start_q"), reply_markup=_int_start_kb(lang))
    return R_INT_START


async def int_units_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Назад к выбору единицы интервала (из сетки N)."""
    lang = await user_lang(update, context)
    await edit_safely(update.callback_query, t(lang, "rem.int_unit_q"), reply_markup=_int_units_kb(lang))
    return R_INT_UNIT


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


async def home_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """«🏠 Домой» на шаге ввода: завершаем диалог (чтобы не перехватывал ввод)
    и показываем стартовое меню."""
    _clear_draft(context)
    await show_dashboard(update, context)
    return ConversationHandler.END


_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(clock_set, pattern=r"^rem:cset:\d{1,2}:\d{1,2}$"),
        CallbackQueryHandler(hour_in, pattern=r"^rem:hin:\d{1,2}$"),
        CallbackQueryHandler(day_same_now, pattern=rf"^rem:dnow:{_DAY_CODE_RE}$"),
        CallbackQueryHandler(day_set, pattern=rf"^rem:dset:{_DAY_CODE_RE}:\d{{1,2}}:\d{{1,2}}$"),
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
            CallbackQueryHandler(time_minutes, pattern=r"^rem:tmins:\d{1,2}$"),
            CallbackQueryHandler(time_set, pattern=r"^rem:tset:\d{1,2}:\d{1,2}$"),
            CallbackQueryHandler(time_step_back, pattern=r"^rem:tstep$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, recv_time),
        ],
        R_INT_UNIT: [
            CallbackQueryHandler(int_unit_pick, pattern=r"^rem:iunit:(min|hour|day)$"),
        ],
        R_INT_GRID: [
            CallbackQueryHandler(int_n_pick, pattern=r"^rem:iset:(min|hour|day):\d{1,2}$"),
            CallbackQueryHandler(int_units_back, pattern=r"^rem:iunits$"),
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
        CallbackQueryHandler(home_cb, pattern=rf"^{CALLBACK_PREFIX}{HOME_KEY}$"),
    ],
    # позволяет заново войти в диалог по кнопке, даже если предыдущий «завис»
    # (напр. пользователь нажал /start, не закрыв старое окно интервала/повтора)
    allow_reentry=True,
    per_message=False,
)


def setup(app: Application) -> None:
    register(Module(key="reminders", title_key="module.reminders", on_open=open_reminders))
    app.add_handler(_conversation)
    app.add_handler(CallbackQueryHandler(open_reminders, pattern=r"^rem:list$"))
    app.add_handler(CallbackQueryHandler(new_reminder, pattern=r"^rem:new$"))
    app.add_handler(CallbackQueryHandler(new_kinds, pattern=r"^rem:kinds$"))
    app.add_handler(CallbackQueryHandler(folder_hours, pattern=r"^rem:folder:hours$"))
    app.add_handler(CallbackQueryHandler(folder_days, pattern=r"^rem:folder:days$"))
    app.add_handler(CallbackQueryHandler(screen_clock, pattern=r"^rem:hclock$"))
    app.add_handler(CallbackQueryHandler(screen_hrel, pattern=r"^rem:hrel$"))
    app.add_handler(CallbackQueryHandler(clock_choice, pattern=r"^rem:hat:\d{1,2}$"))
    app.add_handler(CallbackQueryHandler(clock_minutes, pattern=r"^rem:cmins:\d{1,2}$"))
    app.add_handler(CallbackQueryHandler(day_chosen, pattern=rf"^rem:dday:{_DAY_CODE_RE}$"))
    app.add_handler(CallbackQueryHandler(day_hour_grid, pattern=rf"^rem:dhour:{_DAY_CODE_RE}$"))
    app.add_handler(CallbackQueryHandler(day_hour_choice, pattern=rf"^rem:dh:{_DAY_CODE_RE}:\d{{1,2}}$"))
    app.add_handler(CallbackQueryHandler(day_min_grid, pattern=rf"^rem:dm:{_DAY_CODE_RE}:\d{{1,2}}$"))
    app.add_handler(CallbackQueryHandler(snooze_cb, pattern=r"^snooze:\d+:(\d+|tom|tom_same)$"))
    # запасной обработчик отмены, если диалог уже завершён (устаревший промпт)
    app.add_handler(CallbackQueryHandler(open_reminders, pattern=r"^rem:cancel$"))
    app.add_handler(CallbackQueryHandler(open_reminder, pattern=r"^rem:open:\d+$"))
    app.add_handler(CallbackQueryHandler(toggle_reminder, pattern=r"^rem:toggle:\d+$"))
    app.add_handler(CallbackQueryHandler(confirm_del, pattern=r"^rem:del:\d+$"))
    app.add_handler(CallbackQueryHandler(do_del, pattern=r"^rem:delyes:\d+$"))
    # режим выбора (массовое удаление)
    app.add_handler(CallbackQueryHandler(open_select, pattern=r"^rem:edit$"))
    app.add_handler(CallbackQueryHandler(toggle_mark, pattern=r"^rem:mark:\d+$"))
    app.add_handler(CallbackQueryHandler(toggle_all, pattern=r"^rem:markall$"))
    app.add_handler(CallbackQueryHandler(del_selected, pattern=r"^rem:delsel$"))
    app.add_handler(CallbackQueryHandler(del_selected_yes, pattern=r"^rem:delselyes$"))
    app.add_handler(CallbackQueryHandler(del_all, pattern=r"^rem:delall$"))
    app.add_handler(CallbackQueryHandler(del_all_yes, pattern=r"^rem:delallyes$"))
