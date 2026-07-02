"""Модуль «Календарь»: подписка на публичный ICS-фид -> авто-напоминания о событиях.

Навигация — инлайн-кнопки; ввод ссылки — через ConversationHandler.
callback_data:
  cal:home | cal:connect | cal:sync | cal:del | cal:delyes | cal:cancel
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
from features.calendar import repo, sync, tick
from features.reminders.schedule import to_local

C_URL = 0  # состояние диалога: ждём ссылку на фид

_HOME_CB = f"{CALLBACK_PREFIX}{HOME_KEY}"

_CONNECT_HINT = (
    "Пришли ссылку на опубликованный календарь (webcal://… или https://….ics).\n\n"
    "iCloud: Календарь → настройки календаря → «Открытый календарь» → скопировать ссылку.\n"
    "Совет: публикуй отдельный календарь «Bot», а не основной."
)


def _event_line(ev) -> str:
    local = to_local(ev.starts_at)
    when = f"{local:%d.%m} (весь день)" if ev.all_day else f"{local:%d.%m %H:%M}"
    summary = ev.summary[:40] + ("…" if len(ev.summary) > 40 else "")
    return f"• {when} — {summary}"


async def _render_home(tg_id: int):
    feed = await repo.get_feed(tg_id)
    if feed is None:
        text = (
            "📅 Календарь\n\n"
            "Подключи опубликованный календарь по ссылке — я буду читать события "
            f"и напоминать за {sync.LEAD_MINUTES} мин до начала.\n"
            "(О «весь день»-событиях напомню утром.)"
        )
        rows = [
            [InlineKeyboardButton("🔗 Подключить календарь", callback_data="cal:connect")],
            [InlineKeyboardButton("⬅️ Меню", callback_data=_HOME_CB)],
        ]
        return text, InlineKeyboardMarkup(rows)

    name = feed.title or sync.display_source(feed.url)
    synced = (
        f"{to_local(repo.ensure_utc(feed.last_synced_at)):%d.%m.%Y %H:%M}"
        if feed.last_synced_at
        else "ещё не синхронизирован"
    )
    lines = [f"📅 Календарь: {name}", f"Проверен: {synced}"]
    if feed.last_error:
        lines.append(f"⚠️ Ошибка: {feed.last_error}")
    events = await repo.upcoming_events(tg_id)
    if events:
        lines.append("\nБлижайшие события:")
        lines.extend(_event_line(ev) for ev in events)
    else:
        lines.append("\nБлижайших событий не нашёл.")
    lines.append(f"\nНапомню за {sync.LEAD_MINUTES} мин до начала.")

    rows = [
        [InlineKeyboardButton("🔄 Обновить сейчас", callback_data="cal:sync")],
        [InlineKeyboardButton("🔗 Сменить ссылку", callback_data="cal:connect")],
        [InlineKeyboardButton("🗑 Отключить", callback_data="cal:del")],
        [InlineKeyboardButton("⬅️ Меню", callback_data=_HOME_CB)],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _edit_home(update: Update) -> None:
    text, markup = await _render_home(update.effective_user.id)
    await edit_safely(update.callback_query, text, reply_markup=markup)


def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Отмена", callback_data="cal:cancel")]]
    )


# ----- навигация -----

async def open_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _edit_home(update)


async def sync_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    feed = await repo.get_feed(update.effective_user.id)
    if feed is not None:
        await edit_safely(update.callback_query, "🔄 Проверяю календарь…")
        await tick.sync_feed(feed)
    await _edit_home(update)


async def confirm_del(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Да, отключить", callback_data="cal:delyes")],
            [InlineKeyboardButton("⬅️ Отмена", callback_data="cal:home")],
        ]
    )
    await edit_safely(
        update.callback_query,
        "Отключить календарь? Подписка и импортированные события будут удалены.",
        reply_markup=markup,
    )


async def do_del(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await repo.delete_feed(update.effective_user.id)
    await _edit_home(update)


# ----- диалог подключения -----

async def connect_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await edit_safely(update.callback_query, _CONNECT_HINT, reply_markup=_cancel_kb())
    return C_URL


async def recv_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        url = sync.normalize_url(update.message.text)
        ics_text = await sync.fetch_ics(url)
        title, events = sync.parse_events(ics_text)
    except sync.FeedError as e:
        await update.message.reply_text(
            f"⚠️ {e}\nПопробуй другую ссылку:", reply_markup=_cancel_kb()
        )
        return C_URL
    feed = await repo.save_feed(update.effective_user.id, url, title)
    if feed is None:
        await update.message.reply_text("⚠️ БД не настроена — сохранить подписку не могу.")
        return ConversationHandler.END
    await repo.apply_sync(feed.id, title, events)
    body, markup = await _render_home(update.effective_user.id)
    await update.message.reply_text("✅ Календарь подключён.\n\n" + body, reply_markup=markup)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена по команде /cancel (текстовое сообщение)."""
    text, markup = await _render_home(update.effective_user.id)
    await update.message.reply_text(text, reply_markup=markup)
    return ConversationHandler.END


async def cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена по кнопке «⬅️ Отмена» на шаге ввода ссылки."""
    await _edit_home(update)
    return ConversationHandler.END


_conversation = ConversationHandler(
    entry_points=[CallbackQueryHandler(connect_entry, pattern=r"^cal:connect$")],
    states={C_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_url)]},
    fallbacks=[
        CommandHandler("cancel", cancel),
        CallbackQueryHandler(cancel_cb, pattern=r"^cal:cancel$"),
    ],
    per_message=False,
)


def setup(app: Application) -> None:
    register(Module(key="calendar", title="📅 Календарь", on_open=open_calendar))
    app.add_handler(_conversation)
    app.add_handler(CallbackQueryHandler(open_calendar, pattern=r"^cal:home$"))
    app.add_handler(CallbackQueryHandler(sync_now, pattern=r"^cal:sync$"))
    # запасной обработчик отмены, если диалог уже завершён (устаревший промпт)
    app.add_handler(CallbackQueryHandler(open_calendar, pattern=r"^cal:cancel$"))
    app.add_handler(CallbackQueryHandler(confirm_del, pattern=r"^cal:del$"))
    app.add_handler(CallbackQueryHandler(do_del, pattern=r"^cal:delyes$"))
