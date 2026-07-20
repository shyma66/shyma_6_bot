"""Доступ к данным календаря (фид + события). Запросы изолированы по владельцу.

Если БД не настроена (async_session is None) — безопасные пустые результаты.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from DataBase.database import async_session, get_or_create_user
from DataBase.models import CalendarEvent, CalendarFeed, User
from features.calendar import sync
from features.calendar.sync import ParsedEvent
from features.reminders.schedule import now_utc


def ensure_utc(dt: datetime) -> datetime:
    """sqlite отдаёт naive-datetime — доводим до aware UTC для сравнений."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def get_feed(tg_id: int) -> CalendarFeed | None:
    if not async_session:
        return None
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        res = await s.execute(select(CalendarFeed).where(CalendarFeed.user_id == uid))
        return res.scalar_one_or_none()


async def save_feed(tg_id: int, url: str, title: str | None) -> CalendarFeed | None:
    """Подключает фид (или заменяет ссылку существующего — старые события стираются)."""
    if not async_session:
        return None
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        res = await s.execute(select(CalendarFeed).where(CalendarFeed.user_id == uid))
        feed = res.scalar_one_or_none()
        if feed is None:
            feed = CalendarFeed(
                user_id=uid,
                url=url,
                title=title,
                active=True,
                lead_minutes=sync.DEFAULT_LEAD_MINUTES,
            )
            s.add(feed)
        else:
            feed.url = url
            feed.title = title
            feed.active = True
            feed.last_error = None
            feed.last_synced_at = None
            for ev in await _feed_events(s, feed.id):
                await s.delete(ev)
        await s.commit()
        await s.refresh(feed)
        return feed


async def set_lead(tg_id: int, minutes: int) -> CalendarFeed | None:
    """Меняет время предупреждения подписки (за сколько минут напоминать)."""
    feed = await get_feed(tg_id)
    if feed is None:
        return None
    async with async_session() as s:
        f = await s.get(CalendarFeed, feed.id)
        f.lead_minutes = minutes
        await s.commit()
        await s.refresh(f)
        return f


async def delete_feed(tg_id: int) -> bool:
    feed = await get_feed(tg_id)
    if feed is None:
        return False
    async with async_session() as s:
        f = await s.get(CalendarFeed, feed.id)
        for ev in await _feed_events(s, feed.id):
            await s.delete(ev)
        await s.delete(f)
        await s.commit()
        return True


async def upcoming_events(tg_id: int, limit: int = 8) -> list[CalendarEvent]:
    feed = await get_feed(tg_id)
    if feed is None:
        return []
    async with async_session() as s:
        res = await s.execute(
            select(CalendarEvent)
            .where(CalendarEvent.feed_id == feed.id, CalendarEvent.starts_at >= now_utc())
            .order_by(CalendarEvent.starts_at)
            .limit(limit)
        )
        return list(res.scalars().all())


# ----- для синка / tick -----

async def feeds_to_sync(cooldown_minutes: int) -> list[tuple[CalendarFeed, str | None]]:
    """Активные фиды, которые пора синкать (давно или ещё ни разу), + язык владельца."""
    if not async_session:
        return []
    threshold = now_utc() - timedelta(minutes=cooldown_minutes)
    async with async_session() as s:
        res = await s.execute(
            select(CalendarFeed, User.language)
            .join(User, CalendarFeed.user_id == User.id)
            .where(CalendarFeed.active.is_(True))
        )
        rows = res.all()
    return [
        (f, lang)
        for f, lang in rows
        if f.last_synced_at is None or ensure_utc(f.last_synced_at) <= threshold
    ]


async def apply_sync(feed_id: int, title: str | None, events: list[ParsedEvent]) -> None:
    """Сливает распарсенный фид в БД: новые события добавляет, сдвинутые обновляет
    (и снова напомнит), исчезнувшие будущие удаляет, прошедшие старше суток чистит."""
    if not async_session:
        return
    now = now_utc()
    async with async_session() as s:
        feed = await s.get(CalendarFeed, feed_id)
        if feed is None:
            return
        feed.last_synced_at = now
        feed.last_error = None
        if title:
            feed.title = title[:255]

        existing = {ev.uid: ev for ev in await _feed_events(s, feed_id)}
        seen: set[str] = set()
        for p in events:
            seen.add(p.uid)
            cur = existing.get(p.uid)
            if cur is None:
                s.add(
                    CalendarEvent(
                        feed_id=feed_id,
                        uid=p.uid,
                        summary=p.summary,
                        starts_at=p.starts_at,
                        all_day=p.all_day,
                    )
                )
            else:
                if ensure_utc(cur.starts_at) != p.starts_at:
                    cur.starts_at = p.starts_at
                    cur.notified = False  # событие сдвинули — напомним заново
                cur.summary = p.summary
                cur.all_day = p.all_day

        for uid, cur in existing.items():
            starts = ensure_utc(cur.starts_at)
            if uid not in seen and starts > now:
                await s.delete(cur)  # событие отменили в календаре
            elif starts < now - timedelta(days=1):
                await s.delete(cur)  # давно прошло
        await s.commit()


async def mark_sync_error(feed_id: int, err: str) -> None:
    """Запоминает ошибку синка; last_synced_at двигаем, чтобы не долбить фид каждый tick."""
    if not async_session:
        return
    async with async_session() as s:
        feed = await s.get(CalendarFeed, feed_id)
        if feed is None:
            return
        feed.last_error = err[:255]
        feed.last_synced_at = now_utc()
        await s.commit()


async def due_event_notifications() -> list[tuple[CalendarEvent, int, str | None]]:
    """События без отправленного напоминания, до начала которых осталось меньше
    lead_minutes их подписки, + telegram_user_id и язык владельца."""
    if not async_session:
        return []
    now = now_utc()
    async with async_session() as s:
        res = await s.execute(
            select(
                CalendarEvent,
                CalendarFeed.lead_minutes,
                User.telegram_user_id,
                User.language,
            )
            .join(CalendarFeed, CalendarEvent.feed_id == CalendarFeed.id)
            .join(User, CalendarFeed.user_id == User.id)
            .where(
                CalendarEvent.notified.is_(False),
                CalendarFeed.active.is_(True),
            )
            .order_by(CalendarEvent.starts_at)
        )
        rows = res.all()
    # порог у каждой подписки свой — фильтруем здесь (объёмы крошечные)
    return [
        (ev, tg, lang)
        for ev, lead, tg, lang in rows
        if ensure_utc(ev.starts_at) <= now + timedelta(minutes=lead)
    ]


async def mark_notified(event_id: int) -> None:
    if not async_session:
        return
    async with async_session() as s:
        ev = await s.get(CalendarEvent, event_id)
        if ev is not None:
            ev.notified = True
            await s.commit()


async def _feed_events(s, feed_id: int) -> list[CalendarEvent]:
    res = await s.execute(select(CalendarEvent).where(CalendarEvent.feed_id == feed_id))
    return list(res.scalars().all())
