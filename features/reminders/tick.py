"""Обработка созревших напоминаний (вызывается эндпоинтом /tick по внешнему cron)."""
from core.i18n import FALLBACK_LANG, LANGS
from features.reminders import repo, schedule
from features.reminders.handlers import snooze_markup


async def process_due(bot) -> int:
    """Шлёт все созревшие напоминания и пересчитывает/гасит их. Возвращает число отправленных."""
    due = await repo.due_reminders()
    sent = 0
    for reminder, tg_user_id, lang in due:
        if lang not in LANGS:
            lang = FALLBACK_LANG
        try:
            await bot.send_message(
                chat_id=tg_user_id,
                text=f"🔔 {reminder.text}",
                reply_markup=snooze_markup(reminder.id, lang),
            )
            sent += 1
        except Exception as e:  # noqa: BLE001 — не валим весь tick из-за одного адресата
            print(f"[tick] не удалось отправить напоминание {reminder.id}: {e}")
        next_fire = schedule.compute_next(
            reminder.repeat_kind, reminder.next_fire_at, reminder.interval_seconds
        )
        await repo.apply_fire(reminder.id, next_fire)
    return sent
