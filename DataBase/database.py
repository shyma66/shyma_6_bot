"""Подключение к БД (Neon Postgres, async) + помощники.

Мягкая деградация: если DATABASE_URL не задан, функции ничего не делают
(бот продолжает работать как раньше). Достаточно добавить DATABASE_URL в .env,
чтобы включить регистрацию пользователей и хранение данных.
"""
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import find_dotenv, load_dotenv
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from DataBase.models import Base, User

load_dotenv(find_dotenv())

# Принимаем стандартную строку Neon (postgresql://...?sslmode=require) как есть.
DATABASE_URL = os.getenv("DATABASE_URL")

# Параметры строки подключения, которые понимает psycopg, но НЕ понимает asyncpg.
_ASYNCPG_UNSUPPORTED = {"sslmode", "channel_binding"}


def _normalize_async_url(url: str) -> str:
    """Приводит Postgres-URL к async-драйверу asyncpg и убирает несовместимые параметры.

    Не-Postgres URL (напр. sqlite+aiosqlite для локальной разработки) не трогаем.
    """
    parts = urlsplit(url)
    if not parts.scheme.startswith("postgres"):
        return url
    scheme = parts.scheme if "+" in parts.scheme else "postgresql+asyncpg"
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in _ASYNCPG_UNSUPPORTED]
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


if DATABASE_URL:
    _url = _normalize_async_url(DATABASE_URL)
    # ssl=True только для Postgres/asyncpg (Neon требует SSL). Для прочих драйверов
    # (напр. локальный sqlite+aiosqlite) ssl неприменим.
    _connect_args = {"ssl": True} if _url.startswith("postgresql+asyncpg") else {}
    engine = create_async_engine(_url, pool_pre_ping=True, connect_args=_connect_args)
else:
    engine = None
async_session = (
    async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    if engine
    else None
)


# Мини-миграции: create_all не добавляет колонки в уже существующие таблицы,
# поэтому новые поля доезжают через ALTER TABLE (только Postgres; локальный
# sqlite для тестов создаётся сразу с актуальной схемой).
_MIGRATIONS = [
    # 2026-07-02: настраиваемое время предупреждения календаря
    "ALTER TABLE calendar_feeds ADD COLUMN IF NOT EXISTS lead_minutes INTEGER NOT NULL DEFAULT 30",
]


async def init_db() -> None:
    """Создаёт таблицы при старте, если их ещё нет, и доводит схему миграциями."""
    if engine is None:
        print("[DB] DATABASE_URL not set — пропускаю инициализацию БД (добавь его в .env для Neon).")
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if conn.dialect.name == "postgresql":
            for stmt in _MIGRATIONS:
                await conn.execute(text(stmt))
    print("[DB] таблицы готовы.")


async def get_or_create_user(
    telegram_user_id: int, username: str | None = None
) -> int | None:
    """Заводит пользователя по telegram_user_id (без дублей). Возвращает внутренний id."""
    if async_session is None:
        return None
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(telegram_user_id=telegram_user_id, username=username)
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user.id
