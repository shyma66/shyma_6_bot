"""Доступ к данным «шкафа»: полки и заметки. Все запросы изолированы по владельцу.

Если БД не настроена (async_session is None), функции безопасно отдают пустой
результат / None, чтобы бот не падал.
"""
from sqlalchemy import select

from DataBase.database import async_session, get_or_create_user
from DataBase.models import Note, Shelf


async def list_shelves(tg_id: int) -> list[Shelf]:
    if not async_session:
        return []
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        res = await s.execute(
            select(Shelf).where(Shelf.user_id == uid).order_by(Shelf.created_at)
        )
        return list(res.scalars().all())


async def create_shelf(tg_id: int, title: str) -> Shelf | None:
    if not async_session:
        return None
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        shelf = Shelf(user_id=uid, title=title)
        s.add(shelf)
        await s.commit()
        await s.refresh(shelf)
        return shelf


async def get_shelf(tg_id: int, shelf_id: int) -> Shelf | None:
    """Полка по id с проверкой, что она принадлежит этому пользователю."""
    if not async_session:
        return None
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        res = await s.execute(
            select(Shelf).where(Shelf.id == shelf_id, Shelf.user_id == uid)
        )
        return res.scalar_one_or_none()


async def delete_shelf(tg_id: int, shelf_id: int) -> bool:
    shelf = await get_shelf(tg_id, shelf_id)
    if shelf is None:
        return False
    async with async_session() as s:
        obj = await s.get(Shelf, shelf_id)
        await s.delete(obj)
        await s.commit()
        return True


async def list_notes(tg_id: int, shelf_id: int) -> list[Note]:
    if not async_session:
        return []
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        res = await s.execute(
            select(Note)
            .join(Shelf)
            .where(Note.shelf_id == shelf_id, Shelf.user_id == uid)
            .order_by(Note.created_at)
        )
        return list(res.scalars().all())


async def create_note(tg_id: int, shelf_id: int, text: str) -> Note | None:
    # принадлежность полки проверяем перед записью
    if await get_shelf(tg_id, shelf_id) is None:
        return None
    async with async_session() as s:
        note = Note(shelf_id=shelf_id, text=text)
        s.add(note)
        await s.commit()
        await s.refresh(note)
        return note


async def get_note(tg_id: int, note_id: int) -> Note | None:
    if not async_session:
        return None
    uid = await get_or_create_user(tg_id)
    async with async_session() as s:
        res = await s.execute(
            select(Note).join(Shelf).where(Note.id == note_id, Shelf.user_id == uid)
        )
        return res.scalar_one_or_none()


async def update_note(tg_id: int, note_id: int, text: str) -> Note | None:
    if await get_note(tg_id, note_id) is None:
        return None
    async with async_session() as s:
        note = await s.get(Note, note_id)
        note.text = text
        await s.commit()
        await s.refresh(note)
        return note


async def delete_note(tg_id: int, note_id: int) -> int | None:
    """Удаляет заметку. Возвращает shelf_id удалённой заметки (для возврата к полке)."""
    note = await get_note(tg_id, note_id)
    if note is None:
        return None
    shelf_id = note.shelf_id
    async with async_session() as s:
        obj = await s.get(Note, note_id)
        await s.delete(obj)
        await s.commit()
        return shelf_id
