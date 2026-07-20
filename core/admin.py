"""Админ-доступ, флаги «модуль выключен» и журнал ошибок.

Админ опознаётся по числовому Telegram ID из переменной окружения ADMIN_ID:
username менять можно и освободившийся ник может занять посторонний, а id
неизменен. ID берётся из окружения, а не из кода — в репозиторий не попадает.

Флаги модулей лежат в таблице app_settings, но читаются в память один раз при
старте: меню рисуется на каждое нажатие, и ходить за этим в Neon — лишние
compute-часы. Если БД недоступна, считаем, что включено всё (бот остаётся
рабочим, админ просто не увидит сохранённые выключения до восстановления БД).
"""
import os
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from DataBase.database import load_settings, set_setting

_ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()
ADMIN_ID: int | None = int(_ADMIN_ID_RAW) if _ADMIN_ID_RAW.isdigit() else None

_SETTING_PREFIX = "module_off:"

# Ключи выключенных модулей. Пустое множество = включено всё.
_disabled: set[str] = set()

# Журнал последних ошибок для админ-панели (в памяти, теряется при рестарте).
_ERROR_LOG_MAX = 20
_ANTIFLOOD = timedelta(minutes=1)


@dataclass(frozen=True)
class ErrorRecord:
    at: datetime
    where: str
    text: str


_errors: deque[ErrorRecord] = deque(maxlen=_ERROR_LOG_MAX)
_last_notified: dict[str, datetime] = {}


def is_admin(telegram_user_id: int | None) -> bool:
    """Админ ли это. Без ADMIN_ID в окружении админа нет ни у кого."""
    return ADMIN_ID is not None and telegram_user_id == ADMIN_ID


def admin_configured() -> bool:
    return ADMIN_ID is not None


# ----- флаги модулей -----

async def load_flags() -> None:
    """Поднимает выключенные модули из БД в кэш (вызывается при старте)."""
    _disabled.clear()
    try:
        settings = await load_settings()
    except Exception as e:  # noqa: BLE001 — БД недоступна: работаем со «всё включено»
        print(f"[admin] не удалось прочитать флаги модулей: {e!r} — считаю все включёнными")
        return
    for key, value in settings.items():
        if key.startswith(_SETTING_PREFIX) and value == "1":
            _disabled.add(key[len(_SETTING_PREFIX):])
    if _disabled:
        print(f"[admin] выключены модули: {', '.join(sorted(_disabled))}")


def is_disabled(module_key: str) -> bool:
    return module_key in _disabled


def disabled_keys() -> set[str]:
    return set(_disabled)


async def set_disabled(module_key: str, disabled: bool) -> None:
    """Меняет флаг в кэше и (если БД жива) сохраняет его.

    Кэш обновляем всегда: даже при мёртвой БД выключение должно подействовать
    немедленно — иначе админ-панель бесполезна ровно тогда, когда нужнее всего.
    """
    if disabled:
        _disabled.add(module_key)
    else:
        _disabled.discard(module_key)
    try:
        await set_setting(_SETTING_PREFIX + module_key, "1" if disabled else None)
    except Exception as e:  # noqa: BLE001
        print(f"[admin] флаг {module_key} не сохранён в БД: {e!r} — действует до рестарта")


# ----- журнал ошибок -----

def record_error(where: str, exc: BaseException) -> ErrorRecord:
    """Кладёт ошибку в журнал админ-панели и возвращает запись."""
    rec = ErrorRecord(
        at=datetime.now(timezone.utc), where=where, text=f"{type(exc).__name__}: {exc}"[:500]
    )
    _errors.appendleft(rec)
    return rec


def recent_errors() -> list[ErrorRecord]:
    return list(_errors)


def clear_errors() -> None:
    _errors.clear()
    _last_notified.clear()


def should_notify(rec: ErrorRecord) -> bool:
    """Антифлуд: один и тот же тип ошибки в том же месте — не чаще раза в минуту.

    Без этого шторм (например, недоступная БД на каждом нажатии) превращает
    личку админа в ленту одинаковых сообщений.
    """
    signature = f"{rec.where}|{rec.text.split(':', 1)[0]}"
    last = _last_notified.get(signature)
    if last is not None and rec.at - last < _ANTIFLOOD:
        return False
    _last_notified[signature] = rec.at
    return True
