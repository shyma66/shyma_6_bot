"""Подключение к БД (Neon Postgres, async) + помощники.

Мягкая деградация: если DATABASE_URL не задан, функции ничего не делают
(бот продолжает работать как раньше). Достаточно добавить DATABASE_URL в .env,
чтобы включить регистрацию пользователей и хранение данных.
"""
import os

from dotenv import find_dotenv, load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from DataBase.models import Base, User

load_dotenv(find_dotenv())

# Формат: postgresql+asyncpg://USER:PASSWORD@HOST/DBNAME
DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True) if DATABASE_URL else None
async_session = (
    async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    if engine
    else None
)


async def init_db() -> None:
    """Создаёт таблицы при старте, если их ещё нет."""
    if engine is None:
        print("[DB] DATABASE_URL not set — пропускаю инициализацию БД (добавь его в .env для Neon).")
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[DB] таблицы готовы.")


async def get_or_create_user(telegram_user_id: int, username: str | None = None) -> None:
    """Заводит пользователя по telegram_user_id, если его ещё нет (без дублей)."""
    if async_session is None:
        return
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )
        if result.scalar_one_or_none() is None:
            session.add(User(telegram_user_id=telegram_user_id, username=username))
            await session.commit()
