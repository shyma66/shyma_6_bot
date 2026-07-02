"""Чтение публичного ICS-фида: скачивание с ретраями и парсинг событий.

Чистая логика без БД/телеграма — легко тестируется. URL фида полуприватный
(по ссылке видно события), поэтому он не попадает ни в логи, ни в тексты
ошибок (improvements #04, #05).
"""
import asyncio
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from icalendar import Calendar

from features.reminders.schedule import LOCAL_TZ, now_utc

# За сколько минут до начала события напоминать (точность = интервал /tick, ~5 мин).
LEAD_MINUTES = int(os.getenv("CALENDAR_LEAD_MINUTES", "30"))
WINDOW_DAYS = 30            # горизонт импорта событий из фида
SYNC_COOLDOWN_MINUTES = 30  # не синкать один фид чаще (Apple всё равно кэширует публикацию)
ALL_DAY_HOUR = 9            # «весь день» считаем начинающимся в 09:00 местного времени

MAX_SUMMARY = 512

_TIMEOUT = 15.0
_ATTEMPTS = 3
_BACKOFF_SECONDS = (1.0, 3.0)  # паузы между повторами скачивания


class FeedError(Exception):
    """Понятная пользователю ошибка фида (URL внутрь не попадает)."""


@dataclass
class ParsedEvent:
    uid: str
    summary: str
    starts_at: datetime  # UTC
    all_day: bool


def normalize_url(raw: str) -> str:
    """webcal:// -> https://, проверка что это вообще ссылка."""
    url = raw.strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise FeedError("Это не похоже на ссылку. Нужен адрес вида webcal://… или https://…")
    return url


def display_source(url: str) -> str:
    """Как показывать источник в UI: только домен (полный URL полуприватный)."""
    return urlsplit(url).netloc or "календарь"


async def fetch_ics(url: str) -> str:
    """Скачивает фид с повторами и backoff. В ошибках URL не упоминается."""
    last_err = "не удалось скачать календарь"
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        for attempt in range(_ATTEMPTS):
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPStatusError as e:
                last_err = f"сервер календаря ответил {e.response.status_code}"
            except httpx.HTTPError:
                last_err = "сервер календаря недоступен (сеть/таймаут)"
            if attempt < _ATTEMPTS - 1:
                await asyncio.sleep(_BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)])
    raise FeedError(last_err)


def parse_events(
    ics_text: str, ref: datetime | None = None, window_days: int = WINDOW_DAYS
) -> tuple[str | None, list[ParsedEvent]]:
    """Разбирает ICS: (имя календаря, разовые события в окне (ref; ref+window]).

    Повторяющиеся события (RRULE / RECURRENCE-ID) в v1 пропускаются —
    отдельный инкремент. Дубли UID внутри фида схлопываются (первый выигрывает).
    """
    try:
        cal = Calendar.from_ical(ics_text)
    except Exception as e:  # noqa: BLE001 — битый фид не должен ронять tick
        raise FeedError("не удалось разобрать файл календаря (битый ICS?)") from e

    ref = ref or now_utc()
    horizon = ref + timedelta(days=window_days)
    title = str(cal.get("X-WR-CALNAME")) if cal.get("X-WR-CALNAME") else None

    events: list[ParsedEvent] = []
    seen_uids: set[str] = set()
    for comp in cal.walk("VEVENT"):
        if comp.get("RRULE") is not None or comp.get("RECURRENCE-ID") is not None:
            continue
        dtstart = comp.get("DTSTART")
        if dtstart is None:
            continue
        starts_at, all_day = _to_utc_start(dtstart.dt)
        if starts_at <= ref or starts_at > horizon:
            continue
        uid = str(comp.get("UID") or "") or f"noid-{starts_at.isoformat()}"
        if uid in seen_uids:
            continue
        seen_uids.add(uid)
        summary = str(comp.get("SUMMARY") or "(без названия)")[:MAX_SUMMARY]
        events.append(ParsedEvent(uid=uid, summary=summary, starts_at=starts_at, all_day=all_day))

    events.sort(key=lambda e: e.starts_at)
    return title, events


def _to_utc_start(value) -> tuple[datetime, bool]:
    """DTSTART -> (UTC-datetime, all_day). Голая дата = «весь день», старт в ALL_DAY_HOUR."""
    if isinstance(value, datetime):
        if value.tzinfo is None:  # floating time трактуем как местное
            value = value.replace(tzinfo=LOCAL_TZ)
        return value.astimezone(timezone.utc), False
    if isinstance(value, date):
        local = datetime(value.year, value.month, value.day, ALL_DAY_HOUR, 0, tzinfo=LOCAL_TZ)
        return local.astimezone(timezone.utc), True
    raise FeedError("неожиданный формат даты в фиде")
