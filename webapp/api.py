"""JSON-API для Telegram Mini App «Напоминания».

Аутентификация — по Telegram initData (HMAC-SHA256 по BOT_TOKEN): фронт шлёт
её в заголовке X-Telegram-Init-Data, сервер проверяет подпись и достаёт user.id.
Вся работа с данными — через существующие repo/schedule, изоляция по владельцу,
учёт согласия (Datenschutz). Времена — в поясе бота (REMINDER_TZ), как во всём боте.
"""
import hashlib
import hmac
import json
import os
import time
from datetime import date as _date
from urllib.parse import parse_qsl

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from core.admin import is_admin, is_disabled, is_prime, module_is_prime_only
from DataBase.database import (
    add_prime_request,
    get_user_language,
    has_consent,
    set_consent,
    set_user_language,
)
from features.reminders import repo, schedule

router = APIRouter(prefix="/api")

# Модули главного меню Mini App -> ключ в реестре бота (для флагов вкл/prime).
# «memory» в Mini App = модуль «Шкаф» (shelves) в боте.
_MINI_MODULES = (
    ("memory", "shelves"),
    ("reminders", "reminders"),
    ("calendar", "calendar"),
    ("grades", "grades"),
    ("settings", "settings"),
)
_LANGS = ("ru", "en", "de", "uk")

_BOT_TOKEN = os.getenv("BOT_TOKEN", "")
_MAX_AGE = 24 * 3600  # initData старше суток не принимаем


# ----- аутентификация -----

def verify_init_data(init_data: str) -> dict | None:
    """Проверяет подпись Telegram initData и возвращает объект user (или None)."""
    if not init_data or not _BOT_TOKEN:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:  # noqa: BLE001
        return None
    recv_hash = pairs.pop("hash", None)
    if not recv_hash:
        return None
    data_check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", _BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, recv_hash):
        return None
    try:
        if time.time() - int(pairs.get("auth_date", "0")) > _MAX_AGE:
            return None
    except ValueError:
        return None
    try:
        return json.loads(pairs.get("user", "{}"))
    except Exception:  # noqa: BLE001
        return None


async def _auth(init_data: str | None) -> tuple[int, str | None]:
    user = verify_init_data(init_data or "")
    if not user or "id" not in user:
        raise HTTPException(status_code=401, detail="bad init data")
    return int(user["id"]), user.get("username")


# ----- сериализация -----

def _ser(r) -> dict:
    """Напоминание -> JSON с локальными полями (пояс бота), чтобы фронт не зависел от tz устройства."""
    loc = schedule.to_local(r.next_fire_at)
    return {
        "id": r.id,
        "text": r.text,
        "active": r.active,
        "kind": r.repeat_kind,
        "interval_seconds": r.interval_seconds,
        "y": loc.year, "mo": loc.month, "d": loc.day,
        "hh": loc.hour, "mi": loc.minute,
    }


def _now_local() -> dict:
    n = schedule.to_local(schedule.now_utc())
    return {"y": n.year, "mo": n.month, "d": n.day, "hh": n.hour, "mi": n.minute}


# ----- тела запросов -----

class CreateBody(BaseModel):
    text: str = ""
    kind: str = "once"                 # once|daily|weekly|monthly|interval
    date: str | None = None            # YYYY-MM-DD (локальная дата)
    time: str | None = None            # HH:MM (локальное время)
    interval_seconds: int | None = None
    start_now: bool = False            # для интервала: старт «сейчас»


class TextBody(BaseModel):
    text: str


class IdsBody(BaseModel):
    ids: list[int]


def _parse_time(s: str | None) -> tuple[int, int]:
    try:
        hh, mm = (s or "09:00").split(":")
        return int(hh), int(mm)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="bad time")


def _parse_date(s: str | None) -> _date:
    try:
        return _date.fromisoformat(s)  # YYYY-MM-DD
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="bad date")


def _compute(b: CreateBody):
    """Из тела запроса -> (next_fire_at UTC, kind, interval_seconds). Пояс — как в боте."""
    kind = b.kind
    if kind == "interval":
        secs = int(b.interval_seconds or schedule.MIN_INTERVAL_SECONDS)
        if b.start_now:
            return schedule.interval_start_now(secs), "interval", secs
        hh, mm = _parse_time(b.time)
        return schedule.combine_local_to_utc(_parse_date(b.date), hh, mm), "interval", secs
    if kind == "daily":
        hh, mm = _parse_time(b.time)
        return schedule.daily_fire(hh, mm), "daily", None
    if kind not in ("once", "weekly", "monthly"):
        raise HTTPException(status_code=400, detail="bad kind")
    hh, mm = _parse_time(b.time)
    fire = schedule.combine_local_to_utc(_parse_date(b.date), hh, mm)
    if kind == "once" and fire <= schedule.now_utc():
        raise HTTPException(status_code=400, detail="past")
    return fire, kind, None


# ----- эндпоинты -----

@router.get("/me")
async def me(x_telegram_init_data: str = Header(default=None)):
    """Профиль для главного меню Mini App: имя, язык, роль, флаги модулей, согласие."""
    user = verify_init_data(x_telegram_init_data or "")
    if not user or "id" not in user:
        raise HTTPException(status_code=401, detail="bad init data")
    uid = int(user["id"])
    role = "admin" if is_admin(uid) else ("prime" if is_prime(uid) else "common")
    modules = [
        {"key": mini, "disabled": is_disabled(reg), "prime_only": module_is_prime_only(reg)}
        for mini, reg in _MINI_MODULES
    ]
    return {
        "consent": await has_consent(uid),
        "now": _now_local(),
        "name": user.get("first_name") or user.get("username") or "",
        "lang": await get_user_language(uid),
        "role": role,
        "modules": modules,
    }


class LangBody(BaseModel):
    lang: str


@router.post("/consent")
async def consent(x_telegram_init_data: str = Header(default=None)):
    """«Принимаю» на экране согласия Mini App -> сохраняем согласие в БД (как в боте)."""
    user = verify_init_data(x_telegram_init_data or "")
    if not user or "id" not in user:
        raise HTTPException(status_code=401, detail="bad init data")
    await set_consent(int(user["id"]), user.get("username"))
    return {"ok": True}


@router.post("/lang")
async def set_lang(body: LangBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    if body.lang not in _LANGS:
        raise HTTPException(status_code=400, detail="bad lang")
    await set_user_language(uid, body.lang)
    return {"ok": True}


@router.post("/prime_request")
async def prime_request(x_telegram_init_data: str = Header(default=None)):
    """Заявка на prime-доступ из шторки меню -> в очередь (админ увидит в панели)."""
    user = verify_init_data(x_telegram_init_data or "")
    if not user or "id" not in user:
        raise HTTPException(status_code=401, detail="bad init data")
    status = await add_prime_request(int(user["id"]), user.get("username"))
    return {"ok": True, "status": status}


@router.get("/reminders")
async def list_reminders(x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    if not await has_consent(uid):
        raise HTTPException(status_code=403, detail="no consent")
    items = await repo.list_reminders(uid)
    return {"now": _now_local(), "reminders": [_ser(r) for r in items]}


@router.post("/reminders")
async def create(body: CreateBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    if not await has_consent(uid):
        raise HTTPException(status_code=403, detail="no consent")
    fire, kind, interval = _compute(body)
    text = (body.text or "").strip()[:4000] or "—"
    r = await repo.create_reminder(uid, text, fire, kind, interval)
    return _ser(r)


@router.patch("/reminders/{rid}")
async def edit_text(rid: int, body: TextBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    text = (body.text or "").strip()[:4000]
    if not text:
        raise HTTPException(status_code=400, detail="empty")
    r = await repo.update_text(uid, rid, text)
    if r is None:
        raise HTTPException(status_code=404, detail="not found")
    return _ser(r)


@router.patch("/reminders/{rid}/schedule")
async def edit_schedule(rid: int, body: CreateBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    if not await has_consent(uid):
        raise HTTPException(status_code=403, detail="no consent")
    fire, kind, interval = _compute(body)
    r = await repo.update_schedule(uid, rid, fire, kind, interval)
    if r is None:
        raise HTTPException(status_code=404, detail="not found")
    return _ser(r)


@router.post("/reminders/{rid}/toggle")
async def toggle(rid: int, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    cur = await repo.get_reminder(uid, rid)
    if cur is None:
        raise HTTPException(status_code=404, detail="not found")
    r = await repo.set_active(uid, rid, not cur.active)
    return _ser(r)


@router.delete("/reminders/{rid}")
async def delete_one(rid: int, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await repo.delete_reminder(uid, rid)
    return {"ok": True}


@router.post("/reminders/bulk_delete")
async def bulk_delete(body: IdsBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    n = await repo.delete_reminders(uid, body.ids)
    return {"ok": True, "deleted": n}


@router.post("/reminders/delete_all")
async def delete_all(x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    n = await repo.delete_all_reminders(uid)
    return {"ok": True, "deleted": n}
