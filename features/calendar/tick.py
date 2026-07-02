"""Календарная часть /tick: синк фидов по кулдауну + напоминания о событиях.

Вызывается из эндпоинта /tick в bot_start (внешний cron раз в ~5 мин).
"""
from datetime import timedelta

from features.calendar import repo, sync
from features.reminders.schedule import format_fire, now_utc

# Если инстанс проспал начало события сильнее этого — молча гасим, не спамим.
_STALE_AFTER = timedelta(hours=1)


async def sync_feed(feed) -> str | None:
    """Синкает один фид. Возвращает None при успехе или текст ошибки (без URL)."""
    try:
        ics_text = await sync.fetch_ics(feed.url)
        title, events = sync.parse_events(ics_text)
        await repo.apply_sync(feed.id, title, events)
        return None
    except sync.FeedError as e:
        await repo.mark_sync_error(feed.id, str(e))
        return str(e)
    except Exception as e:  # noqa: BLE001 — один фид не должен ронять tick
        await repo.mark_sync_error(feed.id, "внутренняя ошибка синхронизации")
        print(f"[calendar] фид id={feed.id}: неожиданная ошибка: {e}")
        return "внутренняя ошибка синхронизации"


def event_text(ev) -> str:
    if ev.all_day:
        return f"📅 Сегодня: {ev.summary} (весь день)"
    return f"📅 Скоро событие: {ev.summary}\n🕐 {format_fire(ev.starts_at)}"


async def process_calendar(bot) -> dict:
    """Синкает созревшие фиды и шлёт напоминания о близких событиях."""
    synced = errors = 0
    for feed in await repo.feeds_to_sync(sync.SYNC_COOLDOWN_MINUTES):
        err = await sync_feed(feed)
        if err is None:
            synced += 1
        else:
            errors += 1
            print(f"[calendar] фид id={feed.id}: {err}")  # URL не логируем (#05)

    sent = 0
    for ev, tg_user_id in await repo.due_event_notifications():
        stale = repo.ensure_utc(ev.starts_at) < now_utc() - _STALE_AFTER
        if not stale:
            try:
                await bot.send_message(chat_id=tg_user_id, text=event_text(ev))
                sent += 1
            except Exception as e:  # noqa: BLE001 — попробуем снова в следующий tick
                print(f"[calendar] не удалось отправить событие {ev.id}: {e}")
                continue
        await repo.mark_notified(ev.id)
    return {"cal_synced": synced, "cal_errors": errors, "cal_sent": sent}
