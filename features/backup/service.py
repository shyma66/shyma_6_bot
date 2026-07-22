"""Обслуживание баз на каждом /tick: фейловер, фейлбек, ежедневная копия.

Стратегия (по договорённости с владельцем):
  • В норме работаем на основной (primary), раз в сутки копируем primary -> backup.
  • Основная недоступна (квота Neon выжжена) -> фейловер на backup, работаем на нём.
  • Основная снова доступна (1-е число, счётчик compute сброшен) -> копируем
    накопленное backup -> primary и ВОЗВРАЩАЕМСЯ на primary. Возврат детерминирован
    (а не по «свежести»), иначе бот навсегда застрял бы на backup.

Пока активна primary, backup не трогаем (кроме суточной копии) — он должен
оставаться «холодным», чтобы не жечь свою квоту compute.
"""
from datetime import date

from DataBase.database import (
    active_key,
    load_settings,
    mirror_active_to_others,
    probe_key,
    select_active,
    set_active,
    set_setting,
    touch_heartbeat,
)

PRIMARY, BACKUP = "primary", "backup"
_LAST_MIRROR_KEY = "last_mirror_date"


async def _daily_mirror() -> dict:
    """Раз в сутки копирует активную базу в резерв (гейт по дате в app_settings)."""
    today = date.today().isoformat()
    try:
        settings = await load_settings()
    except Exception:  # noqa: BLE001
        settings = {}
    if settings.get(_LAST_MIRROR_KEY) == today:
        return {"mirror": "skip"}
    res = await mirror_active_to_others()
    if res.get("ok"):
        await set_setting(_LAST_MIRROR_KEY, today)
        return {"mirror": "done", "targets": res.get("targets")}
    return {"mirror": "none", "reason": res.get("reason")}


async def run_periodic() -> dict:
    """Метка свежести + фейловер/фейлбек + суточная копия. Зовётся из /tick."""
    active = active_key()
    if active is None:
        await select_active()
        active = active_key()
    if active is None:
        return {"db": "no active"}

    if active == BACKUP:
        # работаем на резерве; на каждом тике проверяем, не вернулась ли основная
        await touch_heartbeat()
        if await probe_key(PRIMARY):
            # основная восстановилась -> переносим данные backup -> primary и возвращаемся
            m = await mirror_active_to_others()  # active=backup -> копия уходит в primary
            set_active(PRIMARY)
            await touch_heartbeat()
            # данные теперь равны -> суточную копію на сегодня считаем сделанной
            await set_setting(_LAST_MIRROR_KEY, date.today().isoformat())
            return {"db": "failback->primary", "mirror": m}
        return {"db": "backup"}

    # active == primary
    if await probe_key(PRIMARY):
        await touch_heartbeat()
        return {"db": "primary", **await _daily_mirror()}
    # основная упала -> фейловер на резерв
    if await probe_key(BACKUP):
        set_active(BACKUP)
        await touch_heartbeat()
        return {"db": "failover->backup"}
    return {"db": "primary down, no backup"}
