"""Доступ к данным напоминаний. Запросы изолированы по владельцу.

Если БД не настроена (async_session is None) — безопасные пустые результаты.
"""
from datetime import datetime

from sqlalchemy import select

from DataBase.database import async_session, get_or_create_user
from DataBase.models import Reminder, User
from features.reminders import schedule


async def list_reminders(tg_id: int) -> list[Reminder]:
    if async_session is None:
        return []
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        res = await s.execute(
            select(Reminder).where(Reminder.user_id == uid).order_by(Reminder.next_fire_at)
        )
        return list(res.scalars().all())


async def create_reminder(
    tg_id: int,
    text: str,
    next_fire_at: datetime,
    repeat_kind: str,
    interval_seconds: int | None,
) -> Reminder | None:
    if async_session is None:
        return None
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        r = Reminder(
            user_id=uid,
            text=text,
            next_fire_at=next_fire_at,
            repeat_kind=repeat_kind,
            interval_seconds=interval_seconds,
            active=True,
        )
        s.add(r)
        await s.commit()
        await s.refresh(r)
        return r


async def get_reminder(tg_id: int, rid: int) -> Reminder | None:
    if async_session is None:
        return None
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        res = await s.execute(
            select(Reminder).where(Reminder.id == rid, Reminder.user_id == uid)
        )
        return res.scalar_one_or_none()


async def update_text(tg_id: int, rid: int, text: str) -> Reminder | None:
    if await get_reminder(tg_id, rid) is None:
        return None
    async with async_session() as s:
        r = await s.get(Reminder, rid)
        r.text = text
        await s.commit()
        await s.refresh(r)
        return r


async def set_active(tg_id: int, rid: int, active: bool) -> Reminder | None:
    if await get_reminder(tg_id, rid) is None:
        return None
    async with async_session() as s:
        r = await s.get(Reminder, rid)
        r.active = active
        await s.commit()
        await s.refresh(r)
        return r


async def snooze(tg_id: int, rid: int, new_fire) -> bool:
    """Отложить: новое next_fire_at + снова активно (для разовых после срабатывания)."""
    if await get_reminder(tg_id, rid) is None:
        return False
    async with async_session() as s:
        r = await s.get(Reminder, rid)
        r.next_fire_at = new_fire
        r.active = True
        await s.commit()
        return True


async def delete_reminder(tg_id: int, rid: int) -> bool:
    if await get_reminder(tg_id, rid) is None:
        return False
    async with async_session() as s:
        r = await s.get(Reminder, rid)
        await s.delete(r)
        await s.commit()
        return True


# ----- для /tick -----

async def due_reminders() -> list[tuple[Reminder, int]]:
    """Созревшие активные напоминания + telegram_user_id владельца."""
    if async_session is None:
        return []
    async with async_session() as s:
        res = await s.execute(
            select(Reminder, User.telegram_user_id)
            .join(User, Reminder.user_id == User.id)
            .where(Reminder.active.is_(True), Reminder.next_fire_at <= schedule.now_utc())
            .order_by(Reminder.next_fire_at)
        )
        return [(r, tg) for r, tg in res.all()]


async def apply_fire(rid: int, next_fire_at: datetime | None) -> None:
    """После отправки: либо новое next_fire_at (повтор), либо гасим (разовое)."""
    if async_session is None:
        return
    async with async_session() as s:
        r = await s.get(Reminder, rid)
        if r is None:
            return
        if next_fire_at is None:
            r.active = False
        else:
            r.next_fire_at = next_fire_at
        await s.commit()
