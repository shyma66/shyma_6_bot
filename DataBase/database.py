"""Подключение к БД (Neon Postgres, async) + горячий резерв + помощники.

Две базы: DATABASE_URL (основная) и DATABASE_URL_2 (резерв). Обе — одинаковая
схема. При старте бот сам выбирает активную: из достижимых берёт ту, где данные
новее (по метке db_heartbeat), при равенстве предпочитает основную. Так:
  • основная за квотой  → работаем на резерве (автоматически);
  • основная ожила, но резерв успел уйти вперёд → остаёмся на резерве (там свежее);
  • после ежедневного зеркалирования данные равны → снова предпочитается основная.

Раз в сутки активная база зеркалируется в остальные (features/backup): резерв
держит почти те же данные, потеря при аварии — максимум за сутки.

Мягкая деградация: если ни одного URL нет, `async_session` = None и функции
безопасно ничего не делают (бот работает как раньше, без хранилища).
"""
import os
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import find_dotenv, load_dotenv
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from DataBase.models import AppSetting, Base, User

load_dotenv(find_dotenv())

# Ключи баз и их URL из окружения. Порядок = приоритет при равных данных.
DB_ORDER = ("primary", "backup")
_URLS = {
    "primary": os.getenv("DATABASE_URL"),
    "backup": os.getenv("DATABASE_URL_2"),
}

_HEARTBEAT_KEY = "db_heartbeat"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

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


def _build_engine(url: str):
    _url = _normalize_async_url(url)
    is_pg = _url.startswith("postgresql+asyncpg")
    # ssl=True только для Postgres/asyncpg (Neon требует SSL). Для прочих драйверов
    # (напр. локальный sqlite+aiosqlite) ssl неприменим.
    connect_args = {"ssl": True} if is_pg else {}
    # NullPool: соединение закрывается сразу после запроса. Neon усыпляет compute
    # только когда открытых соединений нет — иначе idle-соединение держит базу
    # проснувшейся и выжигает месячную квоту CU-hrs.
    kwargs = {"poolclass": NullPool} if is_pg else {"pool_pre_ping": True}
    return create_async_engine(_url, connect_args=connect_args, **kwargs)


# Движки и фабрики сессий для всех настроенных URL.
_engines: dict[str, "object"] = {}
_sessionmakers: dict[str, async_sessionmaker] = {}
for _key in DB_ORDER:
    if _URLS[_key]:
        _eng = _build_engine(_URLS[_key])
        _engines[_key] = _eng
        _sessionmakers[_key] = async_sessionmaker(
            _eng, class_=AsyncSession, expire_on_commit=False
        )

# Активная база (выбирается select_active() при старте).
_active_key: str | None = None


class _SessionProxy:
    """Стабильный объект, который repo-модули импортируют один раз.

    Внутри всегда указывает на фабрику активной базы, поэтому смена активной БД
    видна везде без повторного импорта. Ложен, когда активной базы нет — repo
    проверяют `if not async_session:` и мягко деградируют.
    """

    def __bool__(self) -> bool:
        return _active_key is not None and _active_key in _sessionmakers

    def __call__(self) -> AsyncSession:
        if not self:
            raise RuntimeError("нет активной БД")
        return _sessionmakers[_active_key]()


# None, только если не настроен ни один URL (полная мягкая деградация).
async_session: _SessionProxy | None = _SessionProxy() if _engines else None


def active_key() -> str | None:
    return _active_key


def configured_keys() -> tuple[str, ...]:
    return tuple(k for k in DB_ORDER if k in _engines)


# Мини-миграции для существующих Postgres-таблиц (create_all не добавляет колонки).
_MIGRATIONS = [
    "ALTER TABLE calendar_feeds ADD COLUMN IF NOT EXISTS lead_minutes INTEGER NOT NULL DEFAULT 30",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS language VARCHAR(5)",
    "ALTER TABLE grade_subjects ADD COLUMN IF NOT EXISTS scale VARCHAR(8) NOT NULL DEFAULT 'points'",
]


async def _create_schema(key: str) -> None:
    eng = _engines[key]
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if conn.dialect.name == "postgresql":
            for stmt in _MIGRATIONS:
                await conn.execute(text(stmt))


async def _probe(key: str) -> bool:
    """Достижима ли база (быстрый SELECT 1)."""
    try:
        async with _sessionmakers[key]() as s:
            await s.execute(text("SELECT 1"))
        return True
    except Exception as e:  # noqa: BLE001 — недоступность БД — штатная ситуация
        print(f"[DB] {key} недоступна: {type(e).__name__}: {e}")
        return False


async def _read_heartbeat(key: str) -> datetime | None:
    try:
        async with _sessionmakers[key]() as s:
            raw = await s.scalar(
                select(AppSetting.value).where(AppSetting.key == _HEARTBEAT_KEY)
            )
        return datetime.fromisoformat(raw) if raw else None
    except Exception:  # noqa: BLE001
        return None


async def select_active() -> None:
    """Выбирает активную базу: из достижимых — с самой свежей меткой, при равенстве
    предпочитает основную. Обновляет глобальный _active_key."""
    global _active_key
    reachable = [k for k in configured_keys() if await _probe(k)]
    if not reachable:
        _active_key = None
        print("[DB] ни одна база недоступна — работаю без хранилища.")
        return
    beats = {k: (await _read_heartbeat(k)) or _EPOCH for k in reachable}
    # больше метка -> активнее; при равенстве меньший индекс в DB_ORDER (основная)
    _active_key = max(reachable, key=lambda k: (beats[k], -DB_ORDER.index(k)))
    print(f"[DB] активная база: {_active_key} (достижимы: {', '.join(reachable)})")


async def init_db() -> None:
    """Создаёт схему на всех достижimых базах и выбирает активную."""
    if not _engines:
        print("[DB] URL не заданы — пропускаю инициализацию БД.")
        return
    for key in configured_keys():
        try:
            await _create_schema(key)
            print(f"[DB] схема готова: {key}")
        except Exception as e:  # noqa: BLE001 — одна база может быть недоступна
            print(f"[DB] схема {key} не создана: {type(e).__name__}: {e}")
    await select_active()


async def touch_heartbeat() -> None:
    """Обновляет метку свежести активной базы (зовётся из /tick)."""
    if not async_session:
        return
    await set_setting(_HEARTBEAT_KEY, datetime.now(timezone.utc).isoformat())


# ----- статус для админ-панели -----

async def db_status() -> list[dict]:
    """Для каждой настроенной базы: жива, активна, размер/строки. Без внешних API."""
    out = []
    for key in configured_keys():
        alive = await _probe(key)
        size = None
        users = None
        if alive:
            size = await _db_size(key)
            users = await _count_users(key)
        out.append(
            {
                "key": key,
                "alive": alive,
                "active": key == _active_key,
                "size": size,       # человекочитаемо ("12 MB") или None
                "users": users,     # число пользователей или None
            }
        )
    return out


async def _db_size(key: str) -> str | None:
    """Занятый объём базы. pg_size_pretty на Postgres; для sqlite — примерно по строкам."""
    try:
        async with _sessionmakers[key]() as s:
            if s.bind.dialect.name == "postgresql":
                return await s.scalar(
                    text("SELECT pg_size_pretty(pg_database_size(current_database()))")
                )
            # sqlite: точного «размера квоты» нет — отдаём число страниц*размер
            pages = await s.scalar(text("PRAGMA page_count"))
            psize = await s.scalar(text("PRAGMA page_size"))
            return f"{(pages or 0) * (psize or 0) // 1024} KB"
    except Exception:  # noqa: BLE001
        return None


async def _count_users(key: str) -> int | None:
    try:
        async with _sessionmakers[key]() as s:
            return await s.scalar(select(func.count()).select_from(User))
    except Exception:  # noqa: BLE001
        return None


# ----- зеркалирование (ежедневная авто-копия активной базы в резерв) -----

# Порядок таблиц с учётом внешних ключей: сначала родители, потом дети.
def _mirror_models():
    from DataBase.models import (  # локальный импорт: избегаем циклов на старте
        AppSetting as _AS,
        CalendarEvent,
        CalendarFeed,
        GradeEntry,
        GradeSubject,
        Note,
        Reminder,
        Shelf,
        User as _U,
    )

    return [_AS, _U, Shelf, Note, Reminder, CalendarFeed, CalendarEvent, GradeSubject, GradeEntry]


async def mirror_active_to_others() -> dict:
    """Копирует активную базу во все остальные достижимые (полное зеркало).

    Резерв в норме не пишется (пишет только активная), поэтому безопасно чистим
    цель и переливаем строки как есть, сохраняя первичные ключи. Для Postgres
    после вставки правим последовательности id, чтобы будущие вставки не столкнулись.
    """
    if _active_key is None:
        return {"ok": False, "reason": "no active db"}
    targets = [k for k in configured_keys() if k != _active_key and await _probe(k)]
    if not targets:
        return {"ok": False, "reason": "no reachable target"}

    models = _mirror_models()
    # снимок активной базы
    snapshot: dict[str, list[dict]] = {}
    async with _sessionmakers[_active_key]() as src:
        for model in models:
            rows = (await src.execute(select(model))).scalars().all()
            snapshot[model.__tablename__] = [_row_to_dict(model, r) for r in rows]

    copied = 0
    for key in targets:
        async with _sessionmakers[key]() as dst:
            # чистим в обратном порядке (дети раньше родителей)
            for model in reversed(models):
                await dst.execute(model.__table__.delete())
            for model in models:
                data = snapshot[model.__tablename__]
                if data:
                    await dst.execute(model.__table__.insert(), data)
                    copied += len(data)
            if dst.bind.dialect.name == "postgresql":
                await _resync_sequences(dst, models)
            await dst.commit()
    return {"ok": True, "targets": targets, "rows": copied}


def _row_to_dict(model, row) -> dict:
    return {c.name: getattr(row, c.name) for c in model.__table__.columns}


async def _resync_sequences(session, models) -> None:
    for model in models:
        pk = list(model.__table__.primary_key.columns)
        if len(pk) != 1 or not pk[0].autoincrement:
            continue
        col = pk[0].name
        tbl = model.__tablename__
        await session.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{tbl}', '{col}'), "
                f"COALESCE((SELECT MAX({col}) FROM {tbl}), 1))"
            )
        )


# ----- прикладные помощники (работают с активной базой через прокси) -----

async def load_settings() -> dict[str, str]:
    """Все глобальные настройки одним запросом (для кэша при старте)."""
    if not async_session:
        return {}
    async with async_session() as session:
        result = await session.execute(select(AppSetting.key, AppSetting.value))
        return {key: value for key, value in result.all()}


async def set_setting(key: str, value: str | None) -> None:
    """Пишет настройку; value=None удаляет запись (возврат к значению по умолчанию)."""
    if not async_session:
        return
    async with async_session() as session:
        row = await session.get(AppSetting, key)
        if value is None:
            if row is not None:
                await session.delete(row)
        elif row is None:
            session.add(AppSetting(key=key, value=value))
        else:
            row.value = value
        await session.commit()


async def get_or_create_user(
    telegram_user_id: int, username: str | None = None
) -> int | None:
    """Заводит пользователя по telegram_user_id (без дублей). Возвращает внутренний id."""
    if not async_session:
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


async def get_user_language(telegram_user_id: int) -> str | None:
    """Сохранённый язык интерфейса (ru/en/de) или None, если не выбран."""
    if not async_session:
        return None
    async with async_session() as session:
        result = await session.execute(
            select(User.language).where(User.telegram_user_id == telegram_user_id)
        )
        return result.scalar_one_or_none()


async def set_user_language(telegram_user_id: int, lang: str) -> None:
    if not async_session:
        return
    uid = await get_or_create_user(telegram_user_id)
    async with async_session() as session:
        user = await session.get(User, uid)
        if user is not None:
            user.language = lang
            await session.commit()
