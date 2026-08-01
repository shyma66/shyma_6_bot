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

from core.admin import (
    clear_errors,
    grant_prime,
    is_admin,
    is_disabled,
    is_prime,
    module_is_prime_only,
    recent_errors,
    revoke_prime,
    set_disabled,
    set_module_prime_only,
)
from DataBase.database import (
    add_prime_request,
    db_status,
    delete_prime_request,
    erase_user,
    get_user_language,
    has_consent,
    list_prime_requests,
    list_prime_users,
    set_consent,
    set_user_language,
)
from features.calendar import repo as cal_repo
from features.calendar import sync as cal_sync
from features.calendar import tick as cal_tick
from features.diet import logic as diet_logic
from features.diet import off as diet_off
from features.diet import repo as diet_repo  # импорт регистрирует diet-таблицы в Base.metadata
from features.grades import logic as grades_logic
from features.grades import repo as grades_repo
from features.reminders import repo, schedule
from features.shelves import repo as shelves_repo

router = APIRouter(prefix="/api")

# Модули главного меню Mini App -> ключ в реестре бота (для флагов вкл/prime).
# «memory» в Mini App = модуль «Шкаф» (shelves) в боте.
_MINI_MODULES = (
    ("memory", "shelves"),
    ("reminders", "reminders"),
    ("calendar", "calendar"),
    ("grades", "grades"),
    ("diet", "diet"),
    ("settings", "settings"),
)
_LANGS = ("ru", "en", "de", "uk")
# Версия Mini App «Калории» (отдельный файл webapp/diet/). Бампать при изменении
# фронта диеты — уходит в /api/me как diet_v, меню строит URL /webapp/diet/?v=…
_DIET_VER = "3"

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


async def _gate(uid: int, reg_key: str) -> None:
    """Серверная защита модуля (не полагаемся только на UI): согласие + вкл/prime.

    403 detail различается на фронте: 'no consent' -> экран согласия, иначе шторка.
    """
    if not await has_consent(uid):
        raise HTTPException(status_code=403, detail="no consent")
    if is_disabled(reg_key) and not is_admin(uid):
        raise HTTPException(status_code=403, detail="module off")
    if module_is_prime_only(reg_key) and not (is_admin(uid) or is_prime(uid)):
        raise HTTPException(status_code=403, detail="prime only")


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
        "diet_v": _DIET_VER,
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


# ===== Модуль «Полка памяти» (memory / shelves) =====

class TitleBody(BaseModel):
    title: str = ""


def _ser_shelf(shelf, count: int) -> dict:
    return {"id": shelf.id, "title": shelf.title, "count": count}


def _ser_note(n) -> dict:
    return {"id": n.id, "text": n.text}


@router.get("/shelves")
async def list_shelves(x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "shelves")
    items = await shelves_repo.list_shelves_with_counts(uid)
    return {"shelves": [_ser_shelf(sh, cnt) for sh, cnt in items]}


@router.post("/shelves")
async def create_shelf(body: TitleBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "shelves")
    title = (body.title or "").strip()[:255]
    if not title:
        raise HTTPException(status_code=400, detail="empty")
    sh = await shelves_repo.create_shelf(uid, title)
    if sh is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    return _ser_shelf(sh, 0)


@router.patch("/shelves/{sid}")
async def rename_shelf(sid: int, body: TitleBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "shelves")
    title = (body.title or "").strip()[:255]
    if not title:
        raise HTTPException(status_code=400, detail="empty")
    sh = await shelves_repo.update_shelf(uid, sid, title)
    if sh is None:
        raise HTTPException(status_code=404, detail="not found")
    return _ser_shelf(sh, 0)


@router.delete("/shelves/{sid}")
async def delete_shelf(sid: int, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "shelves")
    await shelves_repo.delete_shelf(uid, sid)
    return {"ok": True}


@router.post("/shelves/bulk_delete")
async def bulk_delete_shelves(body: IdsBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "shelves")
    n = await shelves_repo.delete_shelves(uid, body.ids)
    return {"ok": True, "deleted": n}


@router.get("/shelves/{sid}/notes")
async def list_notes(sid: int, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "shelves")
    if await shelves_repo.get_shelf(uid, sid) is None:
        raise HTTPException(status_code=404, detail="not found")
    items = await shelves_repo.list_notes(uid, sid)
    return {"notes": [_ser_note(n) for n in items]}


@router.post("/shelves/{sid}/notes")
async def create_note(sid: int, body: TextBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "shelves")
    text = (body.text or "").strip()[:4000]
    if not text:
        raise HTTPException(status_code=400, detail="empty")
    n = await shelves_repo.create_note(uid, sid, text)
    if n is None:
        raise HTTPException(status_code=404, detail="not found")
    return _ser_note(n)


@router.patch("/notes/{nid}")
async def edit_note(nid: int, body: TextBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "shelves")
    text = (body.text or "").strip()[:4000]
    if not text:
        raise HTTPException(status_code=400, detail="empty")
    n = await shelves_repo.update_note(uid, nid, text)
    if n is None:
        raise HTTPException(status_code=404, detail="not found")
    return _ser_note(n)


@router.delete("/notes/{nid}")
async def delete_note(nid: int, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "shelves")
    shelf_id = await shelves_repo.delete_note(uid, nid)
    if shelf_id is None:
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True, "shelf_id": shelf_id}


# ===== Модуль «Настройки» (settings) =====

@router.post("/settings/delete_data")
async def delete_data(x_telegram_init_data: str = Header(default=None)):
    """«Удалить все мои данные» — полное стирание во ВСЕХ базах (как в боте)."""
    uid, _ = await _auth(x_telegram_init_data)
    if not await has_consent(uid):
        raise HTTPException(status_code=403, detail="no consent")
    await erase_user(uid)
    from core.admin import forget_prime  # чистим кэш prime, как do_delete в боте
    forget_prime(uid)
    return {"ok": True}


# ===== Модуль «Календарь» (calendar) =====

class UrlBody(BaseModel):
    url: str = ""


class LeadBody(BaseModel):
    minutes: int = cal_sync.DEFAULT_LEAD_MINUTES


def _local_dt(dt) -> dict | None:
    if dt is None:
        return None
    loc = schedule.to_local(dt)
    return {"y": loc.year, "mo": loc.month, "d": loc.day, "hh": loc.hour, "mi": loc.minute}


def _ser_feed(feed) -> dict:
    return {
        "connected": True,
        "title": feed.title or cal_sync.display_source(feed.url),
        "source": cal_sync.display_source(feed.url),
        "url": feed.url,
        "lead_min": feed.lead_minutes,
        "last_synced": _local_dt(feed.last_synced_at),
        "error": feed.last_error,
    }


def _ser_event(ev) -> dict:
    loc = schedule.to_local(ev.starts_at)
    return {
        "y": loc.year, "mo": loc.month, "d": loc.day, "hh": loc.hour, "mi": loc.minute,
        "all_day": ev.all_day, "summary": ev.summary,
    }


async def _calendar_state(uid: int) -> dict:
    feed = await cal_repo.get_feed(uid)
    if feed is None:
        return {"feed": None, "events": [], "now": _now_local()}
    events = await cal_repo.upcoming_events(uid)
    return {"feed": _ser_feed(feed), "events": [_ser_event(e) for e in events], "now": _now_local()}


@router.get("/calendar")
async def calendar_get(x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "calendar")
    return await _calendar_state(uid)


@router.post("/calendar/connect")
async def calendar_connect(body: UrlBody, x_telegram_init_data: str = Header(default=None)):
    """Подписка на публичный ICS-фид: нормализуем URL, сохраняем, сразу синкаем."""
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "calendar")
    try:
        url = cal_sync.normalize_url(body.url or "")
    except cal_sync.FeedError:
        raise HTTPException(status_code=400, detail="bad url")
    feed = await cal_repo.save_feed(uid, url, cal_sync.display_source(url))
    if feed is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    lang = await get_user_language(uid)
    await cal_tick.sync_feed(feed, lang)   # ошибка синка не роняет подписку — попадёт в feed.error
    return await _calendar_state(uid)


@router.post("/calendar/sync")
async def calendar_sync(x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "calendar")
    feed = await cal_repo.get_feed(uid)
    if feed is None:
        raise HTTPException(status_code=404, detail="no feed")
    lang = await get_user_language(uid)
    await cal_tick.sync_feed(feed, lang)
    return await _calendar_state(uid)


@router.post("/calendar/lead")
async def calendar_lead(body: LeadBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "calendar")
    minutes = max(cal_sync.MIN_LEAD_MINUTES, min(int(body.minutes), cal_sync.MAX_LEAD_MINUTES))
    feed = await cal_repo.set_lead(uid, minutes)
    if feed is None:
        raise HTTPException(status_code=404, detail="no feed")
    return {"feed": _ser_feed(feed)}


@router.delete("/calendar")
async def calendar_disconnect(x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "calendar")
    await cal_repo.delete_feed(uid)
    return {"ok": True}


# ===== Модуль «Оценки» (grades) =====

# Типы оценок: наружу — привычные немецкие метки, в БД — внутренние коды логики.
_KIND_OUT = {grades_logic.SA: "SA", grades_logic.KA: "KA", grades_logic.ORAL: "Mündlich"}
_KIND_IN = {v: k for k, v in _KIND_OUT.items()}


class SubjectBody(BaseModel):
    title: str = ""
    scale: str = grades_logic.SCALE_POINTS


class GradeBody(BaseModel):
    kind: str = ""
    value: int = 0


def _subject_avg(subj):
    return grades_logic.subject_average([(g.kind, g.value) for g in subj.grades], subj.scale)


def _ser_subject(subj) -> dict:
    return {
        "id": subj.id,
        "title": subj.title,
        "scale": subj.scale,
        "avg": grades_logic.fmt_avg(_subject_avg(subj)),
        "grades": [
            {"id": g.id, "kind": _KIND_OUT.get(g.kind, g.kind), "value": g.value}
            for g in subj.grades
        ],
    }


def _overall(subjects, scale: str) -> str:
    avgs = []
    for su in subjects:
        if su.scale != scale:
            continue
        a = grades_logic.subject_average([(g.kind, g.value) for g in su.grades], scale)
        if a is not None:
            avgs.append(a)
    return grades_logic.fmt_avg(grades_logic.overall_average(avgs))


@router.get("/grades")
async def grades_get(x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "grades")
    subs = await grades_repo.list_subjects(uid)
    return {
        "subjects": [_ser_subject(s) for s in subs],
        "overall": {"points": _overall(subs, "points"), "marks": _overall(subs, "marks")},
    }


@router.post("/grades/subjects")
async def create_subject(body: SubjectBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "grades")
    title = (body.title or "").strip()[:100]
    if not title:
        raise HTTPException(status_code=400, detail="empty")
    if body.scale not in grades_logic.SCALES:
        raise HTTPException(status_code=400, detail="bad scale")
    subj = await grades_repo.create_subject(uid, title, body.scale)
    if subj is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    return _ser_subject(subj)


@router.patch("/grades/subjects/{sid}")
async def rename_subject(sid: int, body: TitleBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "grades")
    title = (body.title or "").strip()[:100]
    if not title:
        raise HTTPException(status_code=400, detail="empty")
    subj = await grades_repo.rename_subject(uid, sid, title)
    if subj is None:
        raise HTTPException(status_code=404, detail="not found")
    return _ser_subject(subj)


@router.delete("/grades/subjects/{sid}")
async def delete_subject(sid: int, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "grades")
    await grades_repo.delete_subject(uid, sid)
    return {"ok": True}


@router.post("/grades/subjects/{sid}/grades")
async def add_grade(sid: int, body: GradeBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "grades")
    subj = await grades_repo.get_subject(uid, sid)
    if subj is None:
        raise HTTPException(status_code=404, detail="not found")
    kind_int = _KIND_IN.get(body.kind)
    if kind_int is None or kind_int not in grades_logic.kinds_for_scale(subj.scale):
        raise HTTPException(status_code=400, detail="bad kind")
    try:
        value = grades_logic.parse_value(str(body.value), subj.scale)
    except ValueError:
        raise HTTPException(status_code=400, detail="bad value")
    await grades_repo.add_grade(uid, sid, kind_int, value)
    subj = await grades_repo.get_subject(uid, sid)
    return _ser_subject(subj)


@router.delete("/grades/grades/{gid}")
async def delete_grade(gid: int, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "grades")
    sid = await grades_repo.delete_grade(uid, gid)
    if sid is None:
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True, "subject_id": sid}


# ===== Модуль «Админ-панель» (admin) =====
# Только для админа (числовой ADMIN_ID). Все мутации — обёртки над существующими
# функциями core.admin / DataBase (те же, что в админ-панели бота).

_MINI_TO_REG = dict(_MINI_MODULES)


class AdminIdBody(BaseModel):
    id: str = ""
    user: str | None = None


def _require_admin(uid: int) -> None:
    if not is_admin(uid):
        raise HTTPException(status_code=403, detail="admin only")


def _parse_uid(raw) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="bad id")


def _uname(uid: int, username: str | None) -> str:
    return username or ("id" + str(uid)[-4:])


def _admin_modules() -> list[dict]:
    return [
        {"key": mini, "enabled": not is_disabled(reg),
         "tier": "prime" if module_is_prime_only(reg) else "everyone"}
        for mini, reg in _MINI_MODULES
    ]


async def _admin_members() -> list[dict]:
    return [
        {"id": str(uid), "user": _uname(uid, uname), "since": _local_dt(since)}
        for uid, uname, since in await list_prime_users()
    ]


async def _admin_waitlist() -> list[dict]:
    return [
        {"id": str(uid), "user": _uname(uid, uname), "when": _local_dt(when)}
        for uid, uname, when in await list_prime_requests()
    ]


def _admin_errors() -> list[dict]:
    return [{"where": e.where, "msg": e.text, "when": _local_dt(e.at)} for e in recent_errors()]


async def _admin_dbs() -> list[dict]:
    out = []
    for d in await db_status():
        state = "active" if d["active"] else ("standby" if d["alive"] else "down")
        out.append({"name": d["key"], "state": state, "size": d["size"], "users": d["users"]})
    return out


@router.get("/admin")
async def admin_get(x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    _require_admin(uid)
    return {
        "modules": _admin_modules(),
        "members": await _admin_members(),
        "waitlist": await _admin_waitlist(),
        "errors": _admin_errors(),
        "dbs": await _admin_dbs(),
    }


@router.post("/admin/module/{key}/toggle")
async def admin_toggle_module(key: str, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    _require_admin(uid)
    reg = _MINI_TO_REG.get(key)
    if reg is None:
        raise HTTPException(status_code=404, detail="unknown module")
    await set_disabled(reg, not is_disabled(reg))
    return {"modules": _admin_modules()}


@router.post("/admin/module/{key}/tier")
async def admin_toggle_tier(key: str, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    _require_admin(uid)
    reg = _MINI_TO_REG.get(key)
    if reg is None:
        raise HTTPException(status_code=404, detail="unknown module")
    await set_module_prime_only(reg, not module_is_prime_only(reg))
    return {"modules": _admin_modules()}


@router.post("/admin/prime/allow")
async def admin_prime_allow(body: AdminIdBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    _require_admin(uid)
    pid = _parse_uid(body.id)
    await grant_prime(pid, body.user)
    await delete_prime_request(pid)
    return {"members": await _admin_members(), "waitlist": await _admin_waitlist()}


@router.post("/admin/prime/deny")
async def admin_prime_deny(body: AdminIdBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    _require_admin(uid)
    await delete_prime_request(_parse_uid(body.id))
    return {"waitlist": await _admin_waitlist()}


@router.post("/admin/prime/add")
async def admin_prime_add(body: AdminIdBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    _require_admin(uid)
    await grant_prime(_parse_uid(body.id))
    return {"members": await _admin_members()}


@router.delete("/admin/prime/{pid}")
async def admin_prime_revoke(pid: str, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    _require_admin(uid)
    await revoke_prime(_parse_uid(pid))
    return {"members": await _admin_members()}


@router.post("/admin/errors/clear")
async def admin_clear_errors(x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    _require_admin(uid)
    clear_errors()
    return {"ok": True}


# ===== Модуль «Калории» (diet) =====

class DietProfileBody(BaseModel):
    age: int = 0
    height_cm: int = 0
    weight_kg: float = 0.0
    goal: str = "maintain"
    activity: str = "sedentary"
    units: str = "metric"


class DietFoodBody(BaseModel):
    name: str = ""
    kcal_100: float = 0.0
    protein_100: float = 0.0
    fat_100: float = 0.0
    carb_100: float = 0.0
    sugar_100: float = 0.0


class DietEntryBody(BaseModel):
    date: str | None = None
    meal: str = "snack"
    food_id: int = 0
    amount: float = 0.0
    unit: str = "g"


class DietExpBody(BaseModel):
    date: str | None = None
    kcal: int = 0
    weight_kg: float | None = None
    source: str = "manual"


def _diet_today():
    return schedule.to_local(schedule.now_utc()).date()


def _ser_diet_profile(p) -> dict:
    return {
        "age": p.age, "height_cm": p.height_cm, "weight_kg": p.weight_kg,
        "goal": p.goal, "activity": p.activity, "units": p.units, "tdee": p.tdee,
        "daily_target_kcal": p.daily_target_kcal, "protein_target_g": p.protein_target_g,
        "macro_targets": diet_logic.macro_targets(p.daily_target_kcal, p.protein_target_g),
    }


def _ser_diet_food(f) -> dict:
    return {
        "id": f.id, "name": f.name, "brand": f.brand,
        "kcal_100": f.kcal_100, "protein_100": f.protein_100, "fat_100": f.fat_100,
        "carb_100": f.carb_100, "sugar_100": f.sugar_100,
    }


def _ser_diet_entry(e, food) -> dict:
    return {
        "id": e.id, "meal": e.meal, "food_id": e.food_id, "name": food.name,
        "amount": e.amount, "unit": e.unit, "kcal": round(e.kcal),
        "protein": round(e.protein, 1), "fat": round(e.fat, 1),
        "carb": round(e.carb, 1), "sugar": round(e.sugar, 1),
    }


@router.get("/diet/profile")
async def diet_get_profile(x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "diet")
    p = await diet_repo.get_profile(uid)
    return {"profile": _ser_diet_profile(p) if p else None, "now": _now_local()}


@router.put("/diet/profile")
async def diet_put_profile(body: DietProfileBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "diet")
    try:
        diet_logic.validate_profile(body.age, body.height_cm, body.weight_kg, body.goal, body.activity)
    except diet_logic.DietError as e:
        raise HTTPException(status_code=400, detail=e.key)
    p = await diet_repo.save_profile(uid, body.age, body.height_cm, body.weight_kg,
                                     body.goal, body.activity, body.units)
    if p is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    return {"profile": _ser_diet_profile(p)}


@router.post("/diet/foods")
async def diet_create_food(body: DietFoodBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "diet")
    name = (body.name or "").strip()[:80]
    if not name:
        raise HTTPException(status_code=400, detail="empty name")
    for v in (body.kcal_100, body.protein_100, body.fat_100, body.carb_100, body.sugar_100):
        if v is None or v < 0:
            raise HTTPException(status_code=400, detail="bad value")
    f = await diet_repo.create_manual_food(uid, name, body.kcal_100, body.protein_100,
                                           body.fat_100, body.carb_100, body.sugar_100)
    if f is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    return {"food": _ser_diet_food(f)}


@router.get("/diet/day")
async def diet_day(date: str | None = None, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "diet")
    day = _parse_date(date) if date else _diet_today()
    rows = await diet_repo.list_entries(uid, day)
    meals: dict[str, list] = {"breakfast": [], "lunch": [], "dinner": [], "snack": []}
    for e, food in rows:
        meals[e.meal if e.meal in meals else "snack"].append(_ser_diet_entry(e, food))
    p = await diet_repo.get_profile(uid)
    exp = await diet_repo.get_expenditure(uid, day)
    return {
        "now": _now_local(),
        "date": day.isoformat(),
        "profile": _ser_diet_profile(p) if p else None,
        "eaten": diet_repo.day_totals(rows),
        "meals": meals,
        "burned": (exp.kcal if exp else None),
        "weight_kg": (exp.weight_kg if exp else None),
        "prime": bool(is_prime(uid) or is_admin(uid)),
    }


@router.post("/diet/entries")
async def diet_add_entry(body: DietEntryBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "diet")
    if body.meal not in diet_logic.MEALS:
        raise HTTPException(status_code=400, detail="bad meal")
    if body.unit not in diet_logic.FOOD_UNITS:
        raise HTTPException(status_code=400, detail="bad unit")
    if body.amount is None or body.amount <= 0:
        raise HTTPException(status_code=400, detail="bad amount")
    day = _parse_date(body.date) if body.date else _diet_today()
    e = await diet_repo.add_entry(uid, day, body.meal, body.food_id, body.amount, body.unit)
    if e is None:
        raise HTTPException(status_code=404, detail="food not found")
    return {"ok": True, "id": e.id}


@router.delete("/diet/entries/{eid}")
async def diet_del_entry(eid: int, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "diet")
    await diet_repo.delete_entry(uid, eid)
    return {"ok": True}


@router.post("/diet/entries/bulk_delete")
async def diet_bulk_del(body: IdsBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "diet")
    n = await diet_repo.delete_entries(uid, body.ids)
    return {"ok": True, "deleted": n}


@router.put("/diet/expenditure")
async def diet_put_exp(body: DietExpBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "diet")
    if body.kcal is None or body.kcal < 0:
        raise HTTPException(status_code=400, detail="bad kcal")
    day = _parse_date(body.date) if body.date else _diet_today()
    w = body.weight_kg
    if w is not None and not (diet_logic.WEIGHT_MIN <= w <= diet_logic.WEIGHT_MAX):
        w = None
    await diet_repo.set_expenditure(uid, day, int(body.kcal), w, body.source)
    return {"ok": True}


class DietFavBody(BaseModel):
    food_id: int = 0
    default_amount: float = 100.0


def _ser_diet_fav(fav, food) -> dict:
    d = _ser_diet_food(food)
    d["fav_id"] = fav.id
    d["default_amount"] = fav.default_amount
    return d


@router.get("/diet/favorites")
async def diet_favs(x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "diet")
    items = await diet_repo.list_favorites(uid)
    return {
        "favorites": [_ser_diet_fav(f, food) for f, food in items],
        "limit": diet_repo.FREE_FAV_LIMIT,
        "prime": bool(is_prime(uid) or is_admin(uid)),
    }


@router.post("/diet/favorites")
async def diet_fav_add(body: DietFavBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "diet")
    food = await diet_repo.get_food(uid, body.food_id)
    if food is None:
        raise HTTPException(status_code=404, detail="food not found")
    existing = await diet_repo.get_favorite(uid, body.food_id)
    if existing is None and not (is_prime(uid) or is_admin(uid)):
        if await diet_repo.favorite_count(uid) >= diet_repo.FREE_FAV_LIMIT:
            raise HTTPException(status_code=403, detail="fav limit")
    amt = body.default_amount if (body.default_amount and body.default_amount > 0) else 100.0
    fav = await diet_repo.add_favorite(uid, body.food_id, amt)
    return {"ok": True, "fav_id": (fav.id if fav else None)}


@router.post("/diet/favorites/bulk_delete")
async def diet_fav_del(body: IdsBody, x_telegram_init_data: str = Header(default=None)):
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "diet")
    n = await diet_repo.remove_favorites(uid, body.ids)
    return {"ok": True, "deleted": n}


@router.get("/diet/barcode/{code}")
async def diet_barcode(code: str, x_telegram_init_data: str = Header(default=None)):
    """Поиск продукта по штрихкоду (⭐ prime). Наружу уходит только штрихкод (OpenFoodFacts)."""
    uid, _ = await _auth(x_telegram_init_data)
    await _gate(uid, "diet")
    if not (is_prime(uid) or is_admin(uid)):
        raise HTTPException(status_code=403, detail="prime only")
    code = (code or "").strip()
    if not code.isdigit() or not (8 <= len(code) <= 14):
        raise HTTPException(status_code=400, detail="bad barcode")
    data = await diet_off.lookup(code)
    if data is None:
        raise HTTPException(status_code=404, detail="not found")
    food = await diet_repo.get_or_create_barcode_food(uid, code, data)
    if food is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    d = _ser_diet_food(food)
    d["brand"] = food.brand
    return {"food": d}
