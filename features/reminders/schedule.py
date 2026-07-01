"""Чистая логика напоминаний: таймзоны, парсинг ввода, пересчёт next_fire_at.

Время пользователь задаёт в местном поясе (REMINDER_TZ, по умолчанию Europe/Berlin),
хранится всё в UTC. Без зависимостей от БД/телеграма — легко тестируется.
"""
import os
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo(os.getenv("REMINDER_TZ", "Europe/Berlin"))

# Типы повтора
ONCE = "once"
DAILY = "daily"
WEEKLY = "weekly"
INTERVAL = "interval"

MIN_INTERVAL_SECONDS = 60          # минимум 1 минута
MAX_INTERVAL_SECONDS = 365 * 86400  # максимум ~год

_DT_FMT = "%d.%m.%Y %H:%M"
_TIME_FMT = "%H:%M"
_INTERVAL_RE = re.compile(r"^\s*(\d+)\s*([mhdмчд])\s*$", re.IGNORECASE)
_UNIT_SECONDS = {
    "m": 60, "м": 60,
    "h": 3600, "ч": 3600,
    "d": 86400, "д": 86400,
}


class ParseError(ValueError):
    """Понятная пользователю ошибка разбора ввода."""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _local_to_utc(local_naive: datetime) -> datetime:
    return local_naive.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc)


def to_local(utc_dt: datetime) -> datetime:
    return _ensure_utc(utc_dt).astimezone(LOCAL_TZ)


def parse_when(kind: str, raw: str) -> tuple[datetime, int | None]:
    """Разбирает ввод «когда» по типу. Возвращает (next_fire_at_utc, interval_seconds)."""
    raw = raw.strip()
    if kind in (ONCE, WEEKLY):
        try:
            local = datetime.strptime(raw, _DT_FMT)
        except ValueError:
            raise ParseError("Формат: ДД.ММ.ГГГГ ЧЧ:ММ (например 25.12.2026 09:30)")
        fire = _local_to_utc(local)
        if fire <= now_utc():
            raise ParseError("Это время уже прошло. Укажи будущее время.")
        return fire, None

    if kind == DAILY:
        try:
            t = datetime.strptime(raw, _TIME_FMT).time()
        except ValueError:
            raise ParseError("Формат времени: ЧЧ:ММ (например 09:30)")
        return _next_daily_fire(t), None

    if kind == INTERVAL:
        m = _INTERVAL_RE.match(raw)
        if not m:
            raise ParseError("Формат интервала: 30m / 2h / 1d (м/ч/д)")
        seconds = int(m.group(1)) * _UNIT_SECONDS[m.group(2).lower()]
        if seconds < MIN_INTERVAL_SECONDS:
            raise ParseError("Минимальный интервал — 1 минута.")
        if seconds > MAX_INTERVAL_SECONDS:
            raise ParseError("Слишком большой интервал (макс ~1 год).")
        return now_utc() + timedelta(seconds=seconds), seconds

    raise ParseError("Неизвестный тип напоминания.")


def _next_daily_fire(t: time) -> datetime:
    """Ближайшее наступление времени t (местное) сегодня/завтра -> UTC."""
    now_local = to_local(now_utc())
    candidate = now_local.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    if candidate <= now_local:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def compute_next(
    kind: str, current_next: datetime, interval_seconds: int | None, ref: datetime | None = None
) -> datetime | None:
    """Следующее срабатывание после текущего. None — для разовых (гасим).

    Если пропущено несколько периодов (инстанс спал), проматываем до будущего.
    """
    if kind == ONCE:
        return None
    if kind == DAILY:
        step = timedelta(days=1)
    elif kind == WEEKLY:
        step = timedelta(days=7)
    elif kind == INTERVAL:
        step = timedelta(seconds=interval_seconds or MIN_INTERVAL_SECONDS)
    else:
        return None

    ref = ref or now_utc()
    nxt = _ensure_utc(current_next)
    while nxt <= ref:
        nxt += step
    return nxt


def _at_local(local_dt: datetime, hh: int, mm: int) -> datetime:
    """Тот же локальный день с временем hh:mm -> UTC (aware)."""
    return local_dt.replace(hour=hh, minute=mm, second=0, microsecond=0).astimezone(
        timezone.utc
    )


def _today_or_tomorrow(hh: int, mm: int) -> datetime:
    """Сегодня hh:mm по местному, а если уже прошло — завтра. -> UTC."""
    now_l = to_local(now_utc())
    cand = now_l.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if cand <= now_l:
        cand += timedelta(days=1)
    return cand.astimezone(timezone.utc)


def preset_fire(code: str) -> datetime:
    """Быстрый пресет времени -> next_fire_at (UTC). Всегда в будущем."""
    if code == "in1h":
        return now_utc() + timedelta(hours=1)
    if code == "in3h":
        return now_utc() + timedelta(hours=3)
    if code == "eve":  # сегодня вечером (19:00), иначе завтра 19:00
        return _today_or_tomorrow(19, 0)
    if code == "tom_morning":
        return _at_local(to_local(now_utc()) + timedelta(days=1), 9, 0)
    if code == "tom_eve":
        return _at_local(to_local(now_utc()) + timedelta(days=1), 19, 0)
    if code == "weekend":  # ближайшая суббота 10:00
        now_l = to_local(now_utc())
        days = (5 - now_l.weekday()) % 7  # суббота = 5
        target = _at_local(now_l + timedelta(days=days), 10, 0)
        if target <= now_utc():
            target = _at_local(now_l + timedelta(days=days + 7), 10, 0)
        return target
    raise ParseError("Неизвестный пресет")


def snooze_target(code: str) -> datetime:
    """Куда отложить: число минут или 'tom' (завтра 09:00). -> UTC."""
    if code == "tom":
        return _at_local(to_local(now_utc()) + timedelta(days=1), 9, 0)
    return now_utc() + timedelta(minutes=int(code))


def format_fire(utc_dt: datetime) -> str:
    return to_local(utc_dt).strftime(_DT_FMT)


def describe_repeat(kind: str, interval_seconds: int | None) -> str:
    if kind == ONCE:
        return "разово"
    if kind == DAILY:
        return "ежедневно"
    if kind == WEEKLY:
        return "еженедельно"
    if kind == INTERVAL and interval_seconds:
        if interval_seconds % 86400 == 0:
            return f"каждые {interval_seconds // 86400} дн."
        if interval_seconds % 3600 == 0:
            return f"каждые {interval_seconds // 3600} ч."
        return f"каждые {interval_seconds // 60} мин."
    return "—"
