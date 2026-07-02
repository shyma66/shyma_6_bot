"""Чистая логика напоминаний: таймзоны, парсинг ввода, пересчёт next_fire_at.

Время пользователь задаёт в местном поясе (REMINDER_TZ, по умолчанию Europe/Berlin),
хранится всё в UTC. Без зависимостей от БД/телеграма — легко тестируется.
"""
import calendar
import os
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo(os.getenv("REMINDER_TZ", "Europe/Berlin"))

# Типы повтора
ONCE = "once"
DAILY = "daily"
WEEKLY = "weekly"
MONTHLY = "monthly"
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
    """Понятная пользователю ошибка разбора ввода. Несёт i18n-ключ + параметры;
    текст на языке пользователя собирает обработчик через core.i18n.t."""

    def __init__(self, key: str, **fmt):
        super().__init__(key)
        self.key = key
        self.fmt = fmt


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
    if kind in (ONCE, WEEKLY, MONTHLY):
        try:
            local = datetime.strptime(raw, _DT_FMT)
        except ValueError:
            raise ParseError("rem.err.dt_format")
        fire = _local_to_utc(local)
        if fire <= now_utc():
            raise ParseError("rem.err.past")
        return fire, None

    if kind == DAILY:
        try:
            t = datetime.strptime(raw, _TIME_FMT).time()
        except ValueError:
            raise ParseError("rem.err.time_format")
        return _next_daily_fire(t), None

    if kind == INTERVAL:
        m = _INTERVAL_RE.match(raw)
        if not m:
            raise ParseError("rem.err.interval_format")
        seconds = int(m.group(1)) * _UNIT_SECONDS[m.group(2).lower()]
        if seconds < MIN_INTERVAL_SECONDS:
            raise ParseError("rem.err.interval_min")
        if seconds > MAX_INTERVAL_SECONDS:
            raise ParseError("rem.err.interval_max")
        return now_utc() + timedelta(seconds=seconds), seconds

    raise ParseError("rem.err.unknown_kind")


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

    ref = ref or now_utc()
    nxt = _ensure_utc(current_next)

    if kind == MONTHLY:
        # шаг в локальном календаре (сохраняем день/время, кламп до конца месяца)
        while nxt <= ref:
            nxt = _add_month_utc(nxt)
        return nxt

    if kind == DAILY:
        step = timedelta(days=1)
    elif kind == WEEKLY:
        step = timedelta(days=7)
    elif kind == INTERVAL:
        step = timedelta(seconds=interval_seconds or MIN_INTERVAL_SECONDS)
    else:
        return None

    while nxt <= ref:
        nxt += step
    return nxt


def _add_month_utc(utc_dt: datetime) -> datetime:
    """+1 месяц в локальном календаре (день клампится до последнего дня месяца). -> UTC."""
    local = to_local(utc_dt)
    month = local.month % 12 + 1
    year = local.year + (1 if local.month == 12 else 0)
    last_day = calendar.monthrange(year, month)[1]
    local2 = local.replace(year=year, month=month, day=min(local.day, last_day))
    return local2.astimezone(timezone.utc)


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
    raise ParseError("rem.err.unknown_preset")


def snooze_target(code: str) -> datetime:
    """Куда отложить: число минут или 'tom' (завтра 09:00). -> UTC."""
    if code == "tom":
        return _at_local(to_local(now_utc()) + timedelta(days=1), 9, 0)
    return now_utc() + timedelta(minutes=int(code))


def format_fire(utc_dt: datetime) -> str:
    return to_local(utc_dt).strftime(_DT_FMT)


def describe_repeat(lang: str, kind: str, interval_seconds: int | None) -> str:
    from core.i18n import t  # локальный импорт: schedule остаётся импортируемым без ядра

    if kind in (ONCE, DAILY, WEEKLY, MONTHLY):
        return t(lang, f"rem.repeat.{kind}")
    if kind == INTERVAL and interval_seconds:
        if interval_seconds % 86400 == 0:
            return t(lang, "rem.repeat.every_d", n=interval_seconds // 86400)
        if interval_seconds % 3600 == 0:
            return t(lang, "rem.repeat.every_h", n=interval_seconds // 3600)
        return t(lang, "rem.repeat.every_m", n=interval_seconds // 60)
    return "—"
