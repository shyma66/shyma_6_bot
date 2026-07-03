"""Доступ к данным оценок (предметы + оценки). Запросы изолированы по владельцу.

Если БД не настроена (async_session is None) — безопасные пустые результаты.
"""
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from DataBase.database import async_session, get_or_create_user
from DataBase.models import GradeEntry, GradeSubject


async def list_subjects(tg_id: int) -> list[GradeSubject]:
    """Предметы владельца с загруженными оценками (для средних)."""
    if async_session is None:
        return []
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        res = await s.execute(
            select(GradeSubject)
            .options(selectinload(GradeSubject.grades))
            .where(GradeSubject.user_id == uid)
            .order_by(GradeSubject.created_at)
        )
        return list(res.scalars().all())


async def create_subject(tg_id: int, title: str, scale: str = "points") -> GradeSubject | None:
    if async_session is None:
        return None
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        subject = GradeSubject(user_id=uid, title=title, scale=scale)
        s.add(subject)
        await s.commit()
        await s.refresh(subject)
        return subject


async def get_subject(tg_id: int, sid: int) -> GradeSubject | None:
    """Предмет с оценками; None, если чужой/нет."""
    if async_session is None:
        return None
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        res = await s.execute(
            select(GradeSubject)
            .options(selectinload(GradeSubject.grades))
            .where(GradeSubject.id == sid, GradeSubject.user_id == uid)
        )
        return res.scalar_one_or_none()


async def rename_subject(tg_id: int, sid: int, title: str) -> GradeSubject | None:
    if await get_subject(tg_id, sid) is None:
        return None
    async with async_session() as s:
        subject = await s.get(GradeSubject, sid)
        subject.title = title
        await s.commit()
    return await get_subject(tg_id, sid)


async def delete_subject(tg_id: int, sid: int) -> bool:
    if await get_subject(tg_id, sid) is None:
        return False
    async with async_session() as s:
        subject = await s.get(
            GradeSubject, sid, options=[selectinload(GradeSubject.grades)]
        )
        await s.delete(subject)
        await s.commit()
        return True


async def add_grade(tg_id: int, sid: int, kind: str, value: int) -> bool:
    if await get_subject(tg_id, sid) is None:
        return False
    async with async_session() as s:
        s.add(GradeEntry(subject_id=sid, kind=kind, value=value))
        await s.commit()
        return True


async def delete_grade(tg_id: int, gid: int) -> int | None:
    """Удаляет оценку владельца; возвращает subject_id (для возврата на экран)."""
    if async_session is None:
        return None
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        res = await s.execute(
            select(GradeEntry)
            .join(GradeSubject, GradeEntry.subject_id == GradeSubject.id)
            .where(GradeEntry.id == gid, GradeSubject.user_id == uid)
        )
        grade = res.scalar_one_or_none()
        if grade is None:
            return None
        sid = grade.subject_id
        await s.delete(grade)
        await s.commit()
        return sid
