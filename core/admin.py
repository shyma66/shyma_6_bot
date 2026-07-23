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

from DataBase.database import (
    add_prime_user,
    list_prime_users,
    load_settings,
    remove_prime_user,
    set_setting,
)

_ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()
ADMIN_ID: int | None = int(_ADMIN_ID_RAW) if _ADMIN_ID_RAW.isdigit() else None

_SETTING_PREFIX = "module_off:"
_TIER_PREFIX = "module_tier:"  # module_tier:<key> = "prime" (иначе — «всем»)

# Уровни доступа. Больше число = больше прав.
TIER_COMMON, TIER_PRIME, TIER_ADMIN = 0, 1, 2

# Ключи выключенных модулей. Пустое множество = включено всё.
_disabled: set[str] = set()
# Модули, помеченные «только prime». Отсутствие в множестве = виден всем.
_prime_only: set[str] = set()
# Telegram-id prime-пользователей (кэш; источник — таблица prime_users).
_prime_ids: set[int] = set()

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


# ----- уровни доступа -----

def is_prime(telegram_user_id: int | None) -> bool:
    """Prime ли пользователь. Админ считается prime автоматически."""
    if telegram_user_id is None:
        return False
    return is_admin(telegram_user_id) or telegram_user_id in _prime_ids


def tier(telegram_user_id: int | None) -> int:
    if is_admin(telegram_user_id):
        return TIER_ADMIN
    if is_prime(telegram_user_id):
        return TIER_PRIME
    return TIER_COMMON


def prime_ids() -> set[int]:
    return set(_prime_ids)


# ----- загрузка состояния из БД в кэш (при старте) -----

async def load_state() -> None:
    """Поднимает из БД в память: выключенные модули, уровень модулей, prime-юзеров.

    Меню и проверки прав дёргаются на каждое нажатие — держим в кэше, чтобы не
    ходить в Neon каждый раз. При недоступной БД — безопасные значения по умолчанию
    (всё включено, всё «всем», prime нет).
    """
    _disabled.clear()
    _prime_only.clear()
    _prime_ids.clear()
    try:
        settings = await load_settings()
    except Exception as e:  # noqa: BLE001
        print(f"[admin] настройки не прочитаны: {e!r} — дефолты")
        settings = {}
    for key, value in settings.items():
        if key.startswith(_SETTING_PREFIX) and value == "1":
            _disabled.add(key[len(_SETTING_PREFIX):])
        elif key.startswith(_TIER_PREFIX) and value == "prime":
            _prime_only.add(key[len(_TIER_PREFIX):])
    try:
        _prime_ids.update(uid for uid, _u, _t in await list_prime_users())
    except Exception as e:  # noqa: BLE001
        print(f"[admin] prime-пользователи не прочитаны: {e!r}")
    if _disabled:
        print(f"[admin] выключены модули: {', '.join(sorted(_disabled))}")
    if _prime_only:
        print(f"[admin] только-prime модули: {', '.join(sorted(_prime_only))}")
    if _prime_ids:
        print(f"[admin] prime-пользователей: {len(_prime_ids)}")


# алиас для обратной совместимости со стартом
load_flags = load_state


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


# ----- уровень доступа модуля («всем» / «только prime») -----

def module_is_prime_only(module_key: str) -> bool:
    return module_key in _prime_only


def required_tier(module_key: str) -> int:
    return TIER_PRIME if module_key in _prime_only else TIER_COMMON


async def set_module_prime_only(module_key: str, prime_only: bool) -> None:
    if prime_only:
        _prime_only.add(module_key)
    else:
        _prime_only.discard(module_key)
    try:
        await set_setting(_TIER_PREFIX + module_key, "prime" if prime_only else None)
    except Exception as e:  # noqa: BLE001
        print(f"[admin] уровень {module_key} не сохранён в БД: {e!r} — действует до рестарта")


def can_see(module, telegram_user_id: int | None) -> bool:
    """Виден ли модуль пользователю по правам (без учёта «выключен» — это отдельно)."""
    if getattr(module, "admin_only", False):
        return is_admin(telegram_user_id)
    return tier(telegram_user_id) >= required_tier(module.key)


# ----- членство prime (кэш + БД) -----

async def grant_prime(telegram_user_id: int, username: str | None = None) -> None:
    _prime_ids.add(telegram_user_id)
    try:
        await add_prime_user(telegram_user_id, username)
    except Exception as e:  # noqa: BLE001
        print(f"[admin] prime {telegram_user_id} не сохранён в БД: {e!r} — действует до рестарта")


async def revoke_prime(telegram_user_id: int) -> None:
    _prime_ids.discard(telegram_user_id)
    try:
        await remove_prime_user(telegram_user_id)
    except Exception as e:  # noqa: BLE001
        print(f"[admin] снятие prime {telegram_user_id} не сохранено: {e!r}")


def forget_prime(telegram_user_id: int) -> None:
    """Убирает prime только из кэша (БД уже очищена, напр. при удалении данных).

    Без этого is_prime() продолжал бы возвращать True из памяти, хотя в БД/списке
    пользователя уже нет.
    """
    _prime_ids.discard(telegram_user_id)


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
