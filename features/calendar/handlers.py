"""Модуль «Календарь»: подписка на публичный ICS-фид -> авто-напоминания о событиях.

Навигация — инлайн-кнопки; ввод ссылки/минут — через ConversationHandler.
callback_data:
  cal:home | cal:connect | cal:sync | cal:del | cal:delyes | cal:cancel
  cal:lead | cal:leadset:<мин> | cal:leadcustom
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
from features.calendar import repo, sync, tick
from features.reminders.schedule import to_local

C_URL, C_LEAD = range(2)  # состояния диалога: ждём ссылку на фид / время предупреждения

# Пресеты «за сколько напоминать» (минуты); подписи строит _lead_label.
LEAD_PRESET_MINUTES = (10, 15, 30, 60, 120, 180, 1440)

_HOME_CB = f"{CALLBACK_PREFIX}{HOME_KEY}"


def _lead_label(lang: str, minutes: int) -> str:
    if minutes % 1440 == 0:
        return t(lang, "cal.unit.day", n=minutes // 1440)
    if minutes % 60 == 0:
        return t(lang, "cal.unit.hour", n=minutes // 60)
    return t(lang, "cal.unit.min", n=minutes)


def _event_line(lang: str, ev) -> str:
    local = to_local(ev.starts_at)
    when = f"{local:%d.%m} {t(lang, 'cal.all_day')}" if ev.all_day else f"{local:%d.%m %H:%M}"
    summary = ev.summary[:40] + ("…" if len(ev.summary) > 40 else "")
    return f"• {when} — {summary}"


async def _render_home(tg_id: int, lang: str):
    feed = await repo.get_feed(tg_id)
    if feed is None:
        text = t(lang, "cal.intro", lead=sync.DEFAULT_LEAD_MINUTES)
        rows = [
            [InlineKeyboardButton(t(lang, "cal.connect_btn"), callback_data="cal:connect")],
            [InlineKeyboardButton(t(lang, "common.menu_btn"), callback_data=_HOME_CB)],
        ]
        return text, InlineKeyboardMarkup(rows)

    name = feed.title or sync.display_source(feed.url)
    synced = (
        f"{to_local(repo.ensure_utc(feed.last_synced_at)):%d.%m.%Y %H:%M}"
        if feed.last_synced_at
        else t(lang, "cal.not_synced")
    )
    lines = [t(lang, "cal.title_line", name=name), t(lang, "cal.checked", when=synced)]
    if feed.last_error:
        lines.append(t(lang, "cal.error_line", err=feed.last_error))
    events = await repo.upcoming_events(tg_id)
    if events:
        lines.append("\n" + t(lang, "cal.upcoming"))
        lines.extend(_event_line(lang, ev) for ev in events)
    else:
        lines.append("\n" + t(lang, "cal.no_events"))
    lines.append("\n" + t(lang, "cal.lead_line", lead=_lead_label(lang, feed.lead_minutes)))

    rows = [
        [
            InlineKeyboardButton(t(lang, "cal.sync_btn"), callback_data="cal:sync"),
            InlineKeyboardButton(t(lang, "cal.lead_btn"), callback_data="cal:lead"),
        ],
        [InlineKeyboardButton(t(lang, "cal.change_url_btn"), callback_data="cal:connect")],
        [InlineKeyboardButton(t(lang, "cal.disconnect_btn"), callback_data="cal:del")],
        [InlineKeyboardButton(t(lang, "common.menu_btn"), callback_data=_HOME_CB)],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _edit_home(update: Update, lang: str) -> None:
    text, markup = await _render_home(update.effective_user.id, lang)
    await edit_safely(update.callback_query, text, reply_markup=markup)


def _cancel_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t(lang, "common.cancel_btn"), callback_data="cal:cancel")]]
    )


# ----- навигация -----

async def open_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    await _edit_home(update, lang)


async def sync_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    feed = await repo.get_feed(update.effective_user.id)
    if feed is not None:
        await edit_safely(update.callback_query, t(lang, "cal.syncing"))
        await tick.sync_feed(feed, lang)
    await _edit_home(update, lang)


async def lead_screen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Экран «за сколько до события напоминать»: пресеты + свой ввод."""
    lang = await user_lang(update, context)
    feed = await repo.get_feed(update.effective_user.id)
    if feed is None:
        await _edit_home(update, lang)
        return
    rows = [
        [
            InlineKeyboardButton(
                _lead_label(lang, minutes), callback_data=f"cal:leadset:{minutes}"
            )
            for minutes in LEAD_PRESET_MINUTES[i:i + 3]
        ]
        for i in range(0, len(LEAD_PRESET_MINUTES), 3)
    ]
    rows.append([InlineKeyboardButton(t(lang, "cal.lead_custom_btn"), callback_data="cal:leadcustom")])
    rows.append(
        [
            InlineKeyboardButton(t(lang, "common.back_btn"), callback_data="cal:home"),
            InlineKeyboardButton(t(lang, "common.home_btn"), callback_data=_HOME_CB),
        ]
    )
    await edit_safely(
        update.callback_query,
        t(lang, "cal.lead_screen", lead=_lead_label(lang, feed.lead_minutes)),
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def set_lead_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    minutes = int(update.callback_query.data.rsplit(":", 1)[1])
    await repo.set_lead(update.effective_user.id, minutes)
    await _edit_home(update, lang)


async def confirm_del(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "cal.delyes_btn"), callback_data="cal:delyes")],
            [InlineKeyboardButton(t(lang, "common.cancel_btn"), callback_data="cal:home")],
        ]
    )
    await edit_safely(update.callback_query, t(lang, "cal.confirm_del"), reply_markup=markup)


async def do_del(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update, context)
    await repo.delete_feed(update.effective_user.id)
    await _edit_home(update, lang)


# ----- диалог подключения / свой lead -----

async def connect_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    await edit_safely(
        update.callback_query, t(lang, "cal.connect_hint"), reply_markup=_cancel_kb(lang)
    )
    return C_URL


async def recv_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    try:
        url = sync.normalize_url(update.message.text)
        ics_text = await sync.fetch_ics(url)
        title, events = sync.parse_events(ics_text)
    except sync.FeedError as e:
        await update.message.reply_text(
            t(lang, "cal.try_other", err=t(lang, e.key, **e.fmt)),
            reply_markup=_cancel_kb(lang),
        )
        return C_URL
    feed = await repo.save_feed(update.effective_user.id, url, title)
    if feed is None:
        await update.message.reply_text(t(lang, "cal.db_missing"))
        return ConversationHandler.END
    await repo.apply_sync(feed.id, title, events)
    body, markup = await _render_home(update.effective_user.id, lang)
    await update.message.reply_text(
        t(lang, "cal.connected") + "\n\n" + body, reply_markup=markup
    )
    return ConversationHandler.END


async def lead_custom_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    await edit_safely(
        update.callback_query,
        t(
            lang,
            "cal.lead_custom_hint",
            min=sync.MIN_LEAD_MINUTES,
            max_days=sync.MAX_LEAD_MINUTES // 1440,
        ),
        reply_markup=_cancel_kb(lang),
    )
    return C_LEAD


async def recv_lead(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await user_lang(update, context)
    try:
        minutes = sync.parse_lead_minutes(update.message.text)
    except sync.FeedError as e:
        await update.message.reply_text(
            t(lang, "common.try_again", err=t(lang, e.key, **e.fmt)),
            reply_markup=_cancel_kb(lang),
        )
        return C_LEAD
    await repo.set_lead(update.effective_user.id, minutes)
    body, markup = await _render_home(update.effective_user.id, lang)
    await update.message.reply_text(
        t(lang, "cal.lead_set", lead=_lead_label(lang, minutes)) + "\n\n" + body,
        reply_markup=markup,
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена по команде /cancel (текстовое сообщение)."""
    lang = await user_lang(update, context)
    text, markup = await _render_home(update.effective_user.id, lang)
    await update.message.reply_text(text, reply_markup=markup)
    return ConversationHandler.END


async def cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена по кнопке «⬅️ Отмена» на шаге ввода."""
    lang = await user_lang(update, context)
    await _edit_home(update, lang)
    return ConversationHandler.END


_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(connect_entry, pattern=r"^cal:connect$"),
        CallbackQueryHandler(lead_custom_entry, pattern=r"^cal:leadcustom$"),
    ],
    states={
        C_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_url)],
        C_LEAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_lead)],
    },
    fallbacks=[
        CommandHandler("cancel", cancel),
        CallbackQueryHandler(cancel_cb, pattern=r"^cal:cancel$"),
    ],
    per_message=False,
)


def setup(app: Application) -> None:
    register(Module(key="calendar", title_key="module.calendar", on_open=open_calendar))
    app.add_handler(_conversation)
    app.add_handler(CallbackQueryHandler(open_calendar, pattern=r"^cal:home$"))
    app.add_handler(CallbackQueryHandler(sync_now, pattern=r"^cal:sync$"))
    app.add_handler(CallbackQueryHandler(lead_screen, pattern=r"^cal:lead$"))
    app.add_handler(CallbackQueryHandler(set_lead_cb, pattern=r"^cal:leadset:\d+$"))
    # запасной обработчик отмены, если диалог уже завершён (устаревший промпт)
    app.add_handler(CallbackQueryHandler(open_calendar, pattern=r"^cal:cancel$"))
    app.add_handler(CallbackQueryHandler(confirm_del, pattern=r"^cal:del$"))
    app.add_handler(CallbackQueryHandler(do_del, pattern=r"^cal:delyes$"))
