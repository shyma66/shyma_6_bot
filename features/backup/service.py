"""Ежедневная авто-копия активной базы в резерв + метка свежести.

Вызывается из /tick (внешний cron раз в ~10 мин). Метку свежести обновляем
каждый тик — по ней при старте выбирается база с самыми новыми данными.
Зеркалирование запускаем не чаще раза в сутки (гейт по дате в app_settings),
чтобы не жечь compute обеих Neon без нужды.
"""
from datetime import date

from DataBase.database import (
    load_settings,
    mirror_active_to_others,
    set_setting,
    touch_heartbeat,
)

_LAST_MIRROR_KEY = "last_mirror_date"


async def run_periodic() -> dict:
    """Метка свежести + (раз в сутки) зеркалирование. Возвращает краткий итог для /tick."""
    await touch_heartbeat()

    settings = await load_settings()
    today = date.today().isoformat()
    if settings.get(_LAST_MIRROR_KEY) == today:
        return {"mirror": "skipped (уже сегодня)"}

    result = await mirror_active_to_others()
    if result.get("ok"):
        # отметку ставим только при успехе, иначе повторим на следующем тике
        await set_setting(_LAST_MIRROR_KEY, today)
        return {"mirror": "done", **result}
    return {"mirror": "failed", **result}
