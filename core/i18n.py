"""Мультиязычность (ru/en/de/uk): словарь переводов + определение языка пользователя.

Язык хранится в users.language; если не задан — берётся из language_code клиента
Telegram (не из списка -> en) и сразу сохраняется, чтобы фоновые отправки (/tick)
знали язык без апдейта. Ключи вида "модуль.смысл"; t() подставляет {плейсхолдеры}.
Украинская версия — намеренно шутливая (запрос пользователя), но с теми же
{плейсхолдерами}; лежит отдельным словарём _UK и вливается в _T при импорте.
"""
from telegram import Update
from telegram.ext import ContextTypes

from DataBase.database import get_user_language, set_user_language

LANGS = ("ru", "en", "de", "uk")
LANG_TITLES = {
    "ru": "Русский",
    "en": "English",
    "de": "Deutsch",
    "uk": "🇺🇦 Українська",
}
DEFAULT_LANG = "en"      # для language_code вне списка LANGS
FALLBACK_LANG = "ru"     # для фоновых отправок, если язык ещё не сохранён

_T: dict[str, dict[str, str]] = {
    # ----- общее -----
    "common.menu_btn": {"ru": "⬅️ Меню", "en": "⬅️ Menu", "de": "⬅️ Menü"},
    "common.cancel_btn": {"ru": "⬅️ Отмена", "en": "⬅️ Cancel", "de": "⬅️ Abbrechen"},
    "common.back_btn": {"ru": "⬅️ Назад", "en": "⬅️ Back", "de": "⬅️ Zurück"},
    "common.yes_delete": {"ru": "✅ Да, удалить", "en": "✅ Yes, delete", "de": "✅ Ja, löschen"},
    "common.too_long": {
        "ru": "Слишком длинно (макс {max}). Введи короче:",
        "en": "Too long (max {max}). Try something shorter:",
        "de": "Zu lang (max. {max}). Bitte kürzer:",
    },
    "common.try_again": {
        "ru": "⚠️ {err}\nПопробуй ещё раз:",
        "en": "⚠️ {err}\nTry again:",
        "de": "⚠️ {err}\nBitte erneut:",
    },
    # ----- меню / ядро -----
    "menu.title": {
        "ru": "Главное меню — выбери модуль:",
        "en": "Main menu — pick a module:",
        "de": "Hauptmenü — wähle ein Modul:",
    },
    "menu.unknown_module": {
        "ru": "Неизвестный модуль",
        "en": "Unknown module",
        "de": "Unbekanntes Modul",
    },
    "module.shelves": {"ru": "🗄 Шкаф памяти", "en": "🗄 Memory shelf", "de": "🗄 Gedächtnisschrank"},
    "module.reminders": {"ru": "⏰ Напоминания", "en": "⏰ Reminders", "de": "⏰ Erinnerungen"},
    "module.calendar": {"ru": "📅 Календарь", "en": "📅 Calendar", "de": "📅 Kalender"},
    "module.language": {
        "ru": "🌐 Язык / Language",
        "en": "🌐 Language",
        "de": "🌐 Sprache / Language",
    },
    "lang.title": {
        "ru": "Выбери язык:",
        "en": "Choose your language:",
        "de": "Sprache wählen:",
    },
    # ----- команды -----
    "start.greeting": {
        "ru": "Привет, {name}! Я ShymaBot.",
        "en": "Hi {name}! I'm ShymaBot.",
        "de": "Hallo {name}! Ich bin ShymaBot.",
    },
    "stop.bye": {"ru": "Пока, {name}!", "en": "Bye, {name}!", "de": "Tschüss, {name}!"},
    "support.text": {
        "ru": "{name}, по всем вопросам пиши в поддержку: @shyma_6",
        "en": "Dear {name}, please contact our support: @shyma_6",
        "de": "Hallo {name}, bitte kontaktiere unseren Support: @shyma_6",
    },
    "msg.received": {
        "ru": "Сообщение получено!",
        "en": "Message received!",
        "de": "Nachricht erhalten!",
    },
    # ----- шкаф -----
    "shelf.choose": {"ru": "Выбери полку:", "en": "Pick a shelf:", "de": "Wähle ein Regal:"},
    "shelf.empty": {"ru": "Полок пока нет.", "en": "No shelves yet.", "de": "Noch keine Regale."},
    "shelf.new_btn": {"ru": "➕ Новая полка", "en": "➕ New shelf", "de": "➕ Neues Regal"},
    "shelf.not_found": {
        "ru": "Полка не найдена.",
        "en": "Shelf not found.",
        "de": "Regal nicht gefunden.",
    },
    "shelf.back_to_shelves": {"ru": "⬅️ К полкам", "en": "⬅️ To shelves", "de": "⬅️ Zu den Regalen"},
    "shelf.notes": {"ru": "Заметки:", "en": "Notes:", "de": "Notizen:"},
    "shelf.no_notes": {"ru": "Заметок пока нет.", "en": "No notes yet.", "de": "Noch keine Notizen."},
    "shelf.delete_btn": {"ru": "🗑 Удалить полку", "en": "🗑 Delete shelf", "de": "🗑 Regal löschen"},
    "shelf.confirm_del": {
        "ru": "Удалить полку вместе со всеми её заметками?",
        "en": "Delete this shelf with all its notes?",
        "de": "Regal mitsamt allen Notizen löschen?",
    },
    "shelf.enter_name": {
        "ru": "Введите название новой полки:",
        "en": "Enter a name for the new shelf:",
        "de": "Name des neuen Regals eingeben:",
    },
    "shelf.name_empty": {
        "ru": "Название пустое. Введите ещё раз:",
        "en": "The name is empty. Try again:",
        "de": "Der Name ist leer. Bitte erneut:",
    },
    "note.new_btn": {"ru": "➕ Новая заметка", "en": "➕ New note", "de": "➕ Neue Notiz"},
    "note.not_found": {
        "ru": "Заметка не найдена.",
        "en": "Note not found.",
        "de": "Notiz nicht gefunden.",
    },
    "note.title": {"ru": "📝 Заметка:", "en": "📝 Note:", "de": "📝 Notiz:"},
    "note.edit_btn": {"ru": "✏️ Редактировать", "en": "✏️ Edit", "de": "✏️ Bearbeiten"},
    "note.delete_btn": {"ru": "🗑 Удалить", "en": "🗑 Delete", "de": "🗑 Löschen"},
    "note.back_to_shelf": {"ru": "⬅️ К полке", "en": "⬅️ To the shelf", "de": "⬅️ Zum Regal"},
    "note.enter_text": {
        "ru": "Введите текст заметки:",
        "en": "Enter the note text:",
        "de": "Text der Notiz eingeben:",
    },
    "note.enter_new_text": {
        "ru": "Введите новый текст заметки:",
        "en": "Enter the new note text:",
        "de": "Neuen Text der Notiz eingeben:",
    },
    "note.empty_preview": {"ru": "(пусто)", "en": "(empty)", "de": "(leer)"},
    # ----- напоминания -----
    "rem.title": {"ru": "⏰ Напоминания", "en": "⏰ Reminders", "de": "⏰ Erinnerungen"},
    "rem.list_label": {"ru": "Список:", "en": "Your reminders:", "de": "Liste:"},
    "rem.empty": {"ru": "Пока пусто.", "en": "Nothing yet.", "de": "Noch leer."},
    "rem.new_btn": {"ru": "➕ Новое напоминание", "en": "➕ New reminder", "de": "➕ Neue Erinnerung"},
    "rem.when_q": {
        "ru": "Когда напомнить?",
        "en": "When should I remind you?",
        "de": "Wann soll ich erinnern?",
    },
    "rem.preset.in1h": {"ru": "⏱ Через 1 час", "en": "⏱ In 1 hour", "de": "⏱ In 1 Stunde"},
    "rem.preset.in3h": {"ru": "⏱ Через 3 часа", "en": "⏱ In 3 hours", "de": "⏱ In 3 Stunden"},
    "rem.preset.eve": {"ru": "🌙 Сегодня вечером", "en": "🌙 This evening", "de": "🌙 Heute Abend"},
    "rem.preset.tom_morning": {
        "ru": "☀️ Завтра утром",
        "en": "☀️ Tomorrow morning",
        "de": "☀️ Morgen früh",
    },
    "rem.preset.tom_eve": {
        "ru": "🌆 Завтра вечером",
        "en": "🌆 Tomorrow evening",
        "de": "🌆 Morgen Abend",
    },
    "rem.preset.weekend": {"ru": "📅 В выходные", "en": "📅 On the weekend", "de": "📅 Am Wochenende"},
    "rem.exact_btn": {
        "ru": "⚙️ Точное время / повтор",
        "en": "⚙️ Exact time / repeat",
        "de": "⚙️ Genaue Zeit / Wiederholung",
    },
    "rem.choose_kind": {
        "ru": "Выбери тип напоминания:",
        "en": "Choose the reminder type:",
        "de": "Art der Erinnerung wählen:",
    },
    "rem.kind.once": {"ru": "Разовое", "en": "One-time", "de": "Einmalig"},
    "rem.kind.daily": {"ru": "Ежедневно", "en": "Daily", "de": "Täglich"},
    "rem.kind.weekly": {"ru": "Еженедельно", "en": "Weekly", "de": "Wöchentlich"},
    "rem.kind.monthly": {"ru": "Ежемесячно", "en": "Monthly", "de": "Monatlich"},
    "rem.kind.interval": {"ru": "Интервал", "en": "Interval", "de": "Intervall"},
    "rem.hint.dt": {
        "ru": "Введи дату и время: ДД.ММ.ГГГГ ЧЧ:ММ (например 25.12.2026 09:30)",
        "en": "Enter date and time: DD.MM.YYYY HH:MM (e.g. 25.12.2026 09:30)",
        "de": "Datum und Uhrzeit eingeben: TT.MM.JJJJ HH:MM (z. B. 25.12.2026 09:30)",
    },
    "rem.hint.time": {
        "ru": "Введи время: ЧЧ:ММ (например 09:30)",
        "en": "Enter a time: HH:MM (e.g. 09:30)",
        "de": "Uhrzeit eingeben: HH:MM (z. B. 09:30)",
    },
    "rem.hint.interval": {
        "ru": "Введи интервал: 30m / 2h / 1d (м/ч/д)",
        "en": "Enter an interval: 30m / 2h / 1d",
        "de": "Intervall eingeben: 30m / 2h / 1d",
    },
    "rem.enter_text": {
        "ru": "Теперь введи текст напоминания:",
        "en": "Now enter the reminder text:",
        "de": "Jetzt den Erinnerungstext eingeben:",
    },
    "rem.created": {"ru": "✅ Напоминание создано.", "en": "✅ Reminder created.", "de": "✅ Erinnerung erstellt."},
    "rem.not_found": {
        "ru": "Напоминание не найдено.",
        "en": "Reminder not found.",
        "de": "Erinnerung nicht gefunden.",
    },
    "rem.to_list": {"ru": "⬅️ К списку", "en": "⬅️ To the list", "de": "⬅️ Zur Liste"},
    "rem.card": {
        "ru": "⏰ Напоминание\n\nТекст: {text}\nКогда: {when}\nПовтор: {repeat}\nСтатус: {status}",
        "en": "⏰ Reminder\n\nText: {text}\nWhen: {when}\nRepeat: {repeat}\nStatus: {status}",
        "de": "⏰ Erinnerung\n\nText: {text}\nWann: {when}\nWiederholung: {repeat}\nStatus: {status}",
    },
    "rem.status.active": {"ru": "активно", "en": "active", "de": "aktiv"},
    "rem.status.paused": {"ru": "на паузе", "en": "paused", "de": "pausiert"},
    "rem.text_btn": {"ru": "✏️ Текст", "en": "✏️ Text", "de": "✏️ Text"},
    "rem.time_btn": {"ru": "🕐 Время", "en": "🕐 Time", "de": "🕐 Zeit"},
    "rem.pause_btn": {"ru": "⏸ Пауза", "en": "⏸ Pause", "de": "⏸ Pause"},
    "rem.resume_btn": {"ru": "▶️ Возобновить", "en": "▶️ Resume", "de": "▶️ Fortsetzen"},
    "rem.confirm_del": {
        "ru": "Удалить напоминание?",
        "en": "Delete this reminder?",
        "de": "Diese Erinnerung löschen?",
    },
    "rem.enter_new_text": {
        "ru": "Введи новый текст напоминания:",
        "en": "Enter the new reminder text:",
        "de": "Neuen Erinnerungstext eingeben:",
    },
    "rem.new_time": {
        "ru": "🕐 Новое время ({kind}).\n{hint}",
        "en": "🕐 New time ({kind}).\n{hint}",
        "de": "🕐 Neue Zeit ({kind}).\n{hint}",
    },
    "rem.time_updated": {"ru": "✅ Время обновлено.", "en": "✅ Time updated.", "de": "✅ Zeit aktualisiert."},
    "rem.snoozed_until": {
        "ru": "💤 Отложено до {when}",
        "en": "💤 Snoozed until {when}",
        "de": "💤 Verschoben auf {when}",
    },
    "rem.snooze_failed": {
        "ru": "Не удалось отложить (напоминание не найдено).",
        "en": "Couldn't snooze (reminder not found).",
        "de": "Verschieben fehlgeschlagen (Erinnerung nicht gefunden).",
    },
    "rem.snooze.10": {"ru": "💤 +10 мин", "en": "💤 +10 min", "de": "💤 +10 Min"},
    "rem.snooze.60": {"ru": "💤 +1 час", "en": "💤 +1 hour", "de": "💤 +1 Stunde"},
    "rem.snooze.tom": {"ru": "💤 Завтра 09:00", "en": "💤 Tomorrow 09:00", "de": "💤 Morgen 09:00"},
    "rem.repeat.once": {"ru": "разово", "en": "one-time", "de": "einmalig"},
    "rem.repeat.daily": {"ru": "ежедневно", "en": "daily", "de": "täglich"},
    "rem.repeat.weekly": {"ru": "еженедельно", "en": "weekly", "de": "wöchentlich"},
    "rem.repeat.monthly": {"ru": "ежемесячно", "en": "monthly", "de": "monatlich"},
    "rem.repeat.every_d": {"ru": "каждые {n} дн.", "en": "every {n} d", "de": "alle {n} Tg."},
    "rem.repeat.every_h": {"ru": "каждые {n} ч.", "en": "every {n} h", "de": "alle {n} Std."},
    "rem.repeat.every_m": {"ru": "каждые {n} мин.", "en": "every {n} min", "de": "alle {n} Min."},
    "rem.err.dt_format": {
        "ru": "Формат: ДД.ММ.ГГГГ ЧЧ:ММ (например 25.12.2026 09:30)",
        "en": "Format: DD.MM.YYYY HH:MM (e.g. 25.12.2026 09:30)",
        "de": "Format: TT.MM.JJJJ HH:MM (z. B. 25.12.2026 09:30)",
    },
    "rem.err.past": {
        "ru": "Это время уже прошло. Укажи будущее время.",
        "en": "That time has already passed. Pick a future time.",
        "de": "Diese Zeit ist schon vorbei. Bitte eine zukünftige Zeit.",
    },
    "rem.err.time_format": {
        "ru": "Формат времени: ЧЧ:ММ (например 09:30)",
        "en": "Time format: HH:MM (e.g. 09:30)",
        "de": "Zeitformat: HH:MM (z. B. 09:30)",
    },
    "rem.err.interval_format": {
        "ru": "Формат интервала: 30m / 2h / 1d (м/ч/д)",
        "en": "Interval format: 30m / 2h / 1d",
        "de": "Intervallformat: 30m / 2h / 1d",
    },
    "rem.err.interval_min": {
        "ru": "Минимальный интервал — 1 минута.",
        "en": "Minimum interval is 1 minute.",
        "de": "Mindestintervall: 1 Minute.",
    },
    "rem.err.interval_max": {
        "ru": "Слишком большой интервал (макс ~1 год).",
        "en": "Interval too large (max ~1 year).",
        "de": "Intervall zu groß (max. ~1 Jahr).",
    },
    "rem.err.unknown_kind": {
        "ru": "Неизвестный тип напоминания.",
        "en": "Unknown reminder type.",
        "de": "Unbekannter Erinnerungstyp.",
    },
    "rem.err.unknown_preset": {
        "ru": "Неизвестный пресет.",
        "en": "Unknown preset.",
        "de": "Unbekannte Vorlage.",
    },
    # ----- календарь -----
    "cal.intro": {
        "ru": "📅 Календарь\n\nПодключи опубликованный календарь по ссылке — я буду читать "
              "события и напоминать перед началом (по умолчанию за {lead} мин, потом настроишь).\n"
              "(О «весь день»-событиях напомню утром.)",
        "en": "📅 Calendar\n\nConnect a published calendar link — I'll read the events and "
              "remind you before they start (default {lead} min, adjustable later).\n"
              "(For all-day events I'll remind you in the morning.)",
        "de": "📅 Kalender\n\nVerbinde einen veröffentlichten Kalender-Link — ich lese die "
              "Termine und erinnere dich vor Beginn (Standard: {lead} Min, später einstellbar).\n"
              "(An ganztägige Termine erinnere ich morgens.)",
    },
    "cal.connect_btn": {
        "ru": "🔗 Подключить календарь",
        "en": "🔗 Connect a calendar",
        "de": "🔗 Kalender verbinden",
    },
    "cal.connect_hint": {
        "ru": "Пришли ссылку на опубликованный календарь (webcal://… или https://….ics).\n\n"
              "iCloud: Календарь → настройки календаря → «Открытый календарь» → скопировать ссылку.\n"
              "Совет: публикуй отдельный календарь «Bot», а не основной.",
        "en": "Send the link to your published calendar (webcal://… or https://….ics).\n\n"
              "iCloud: Calendar → calendar settings → “Public Calendar” → copy the link.\n"
              "Tip: publish a separate “Bot” calendar, not your main one.",
        "de": "Schicke den Link zu deinem veröffentlichten Kalender (webcal://… oder https://….ics).\n\n"
              "iCloud: Kalender → Kalendereinstellungen → „Öffentlicher Kalender“ → Link kopieren.\n"
              "Tipp: veröffentliche einen separaten „Bot“-Kalender, nicht deinen Hauptkalender.",
    },
    "cal.title_line": {"ru": "📅 Календарь: {name}", "en": "📅 Calendar: {name}", "de": "📅 Kalender: {name}"},
    "cal.checked": {"ru": "Проверен: {when}", "en": "Checked: {when}", "de": "Geprüft: {when}"},
    "cal.not_synced": {
        "ru": "ещё не синхронизирован",
        "en": "not synced yet",
        "de": "noch nicht synchronisiert",
    },
    "cal.error_line": {"ru": "⚠️ Ошибка: {err}", "en": "⚠️ Error: {err}", "de": "⚠️ Fehler: {err}"},
    "cal.upcoming": {"ru": "Ближайшие события:", "en": "Upcoming events:", "de": "Nächste Termine:"},
    "cal.no_events": {
        "ru": "Ближайших событий не нашёл.",
        "en": "No upcoming events found.",
        "de": "Keine anstehenden Termine gefunden.",
    },
    "cal.lead_line": {
        "ru": "Напомню за {lead} до начала.",
        "en": "I'll remind you {lead} before start.",
        "de": "Ich erinnere dich {lead} vor Beginn.",
    },
    "cal.sync_btn": {"ru": "🔄 Обновить сейчас", "en": "🔄 Refresh now", "de": "🔄 Jetzt aktualisieren"},
    "cal.lead_btn": {"ru": "⏱ За сколько", "en": "⏱ Lead time", "de": "⏱ Vorlaufzeit"},
    "cal.change_url_btn": {"ru": "🔗 Сменить ссылку", "en": "🔗 Change link", "de": "🔗 Link ändern"},
    "cal.disconnect_btn": {"ru": "🗑 Отключить", "en": "🗑 Disconnect", "de": "🗑 Trennen"},
    "cal.all_day": {"ru": "(весь день)", "en": "(all day)", "de": "(ganztägig)"},
    "cal.syncing": {
        "ru": "🔄 Проверяю календарь…",
        "en": "🔄 Checking the calendar…",
        "de": "🔄 Kalender wird geprüft…",
    },
    "cal.confirm_del": {
        "ru": "Отключить календарь? Подписка и импортированные события будут удалены.",
        "en": "Disconnect the calendar? The subscription and imported events will be removed.",
        "de": "Kalender trennen? Abo und importierte Termine werden gelöscht.",
    },
    "cal.delyes_btn": {"ru": "✅ Да, отключить", "en": "✅ Yes, disconnect", "de": "✅ Ja, trennen"},
    "cal.lead_screen": {
        "ru": "⏱ Сейчас напоминаю за {lead} до начала события.\nЗа сколько напоминать?",
        "en": "⏱ Currently reminding {lead} before an event starts.\nHow early should I remind you?",
        "de": "⏱ Aktuell erinnere ich {lead} vor Beginn.\nWie früh soll ich erinnern?",
    },
    "cal.lead_custom_btn": {"ru": "✏️ Своё", "en": "✏️ Custom", "de": "✏️ Eigene"},
    "cal.lead_custom_hint": {
        "ru": "Введи своё время: число минут или с единицей — 45m / 2h / 1d (м/ч/д).\n"
              "От {min} мин до {max_days} дней.",
        "en": "Enter your lead time: minutes, or with a unit — 45m / 2h / 1d.\n"
              "From {min} min to {max_days} days.",
        "de": "Eigene Vorlaufzeit eingeben: Minuten oder mit Einheit — 45m / 2h / 1d.\n"
              "Von {min} Min bis {max_days} Tagen.",
    },
    "cal.lead_set": {
        "ru": "✅ Буду напоминать за {lead}.",
        "en": "✅ I'll remind you {lead} in advance.",
        "de": "✅ Ich erinnere dich {lead} im Voraus.",
    },
    "cal.connected": {"ru": "✅ Календарь подключён.", "en": "✅ Calendar connected.", "de": "✅ Kalender verbunden."},
    "cal.db_missing": {
        "ru": "⚠️ БД не настроена — сохранить подписку не могу.",
        "en": "⚠️ Database is not configured — can't save the subscription.",
        "de": "⚠️ Datenbank nicht konfiguriert — Abo kann nicht gespeichert werden.",
    },
    "cal.try_other": {
        "ru": "⚠️ {err}\nПопробуй другую ссылку:",
        "en": "⚠️ {err}\nTry another link:",
        "de": "⚠️ {err}\nBitte einen anderen Link:",
    },
    "cal.event_soon": {
        "ru": "📅 Скоро событие: {summary}\n🕐 {when}",
        "en": "📅 Upcoming event: {summary}\n🕐 {when}",
        "de": "📅 Bald: {summary}\n🕐 {when}",
    },
    "cal.event_today": {
        "ru": "📅 Сегодня: {summary} (весь день)",
        "en": "📅 Today: {summary} (all day)",
        "de": "📅 Heute: {summary} (ganztägig)",
    },
    "cal.unit.min": {"ru": "{n} мин", "en": "{n} min", "de": "{n} Min"},
    "cal.unit.hour": {"ru": "{n} ч", "en": "{n} h", "de": "{n} Std."},
    "cal.unit.day": {"ru": "{n} д", "en": "{n} d", "de": "{n} Tg."},
    "cal.err.not_url": {
        "ru": "Это не похоже на ссылку. Нужен адрес вида webcal://… или https://…",
        "en": "That doesn't look like a link. It should start with webcal://… or https://…",
        "de": "Das sieht nicht wie ein Link aus. Erwartet: webcal://… oder https://…",
    },
    "cal.err.http": {
        "ru": "сервер календаря ответил {code}",
        "en": "the calendar server responded with {code}",
        "de": "der Kalender-Server antwortete mit {code}",
    },
    "cal.err.network": {
        "ru": "сервер календаря недоступен (сеть/таймаут)",
        "en": "the calendar server is unreachable (network/timeout)",
        "de": "der Kalender-Server ist nicht erreichbar (Netz/Timeout)",
    },
    "cal.err.bad_ics": {
        "ru": "не удалось разобрать файл календаря (битый ICS?)",
        "en": "couldn't parse the calendar file (broken ICS?)",
        "de": "Kalenderdatei konnte nicht gelesen werden (defektes ICS?)",
    },
    "cal.err.bad_date": {
        "ru": "неожиданный формат даты в фиде",
        "en": "unexpected date format in the feed",
        "de": "unerwartetes Datumsformat im Feed",
    },
    "cal.err.internal": {
        "ru": "внутренняя ошибка синхронизации",
        "en": "internal sync error",
        "de": "interner Synchronisierungsfehler",
    },
    "cal.err.lead_format": {
        "ru": "Формат: число минут или 45m / 2h / 1d (м/ч/д)",
        "en": "Format: minutes, or 45m / 2h / 1d",
        "de": "Format: Minuten oder 45m / 2h / 1d",
    },
    "cal.err.lead_min": {
        "ru": "Минимум — {min} минут.",
        "en": "Minimum is {min} minutes.",
        "de": "Minimum: {min} Minuten.",
    },
    "cal.err.lead_max": {
        "ru": "Максимум — {max_days} дней.",
        "en": "Maximum is {max_days} days.",
        "de": "Maximum: {max_days} Tage.",
    },
    # ----- оценки (немецкая система, баллы 0–15) -----
    "module.grades": {"ru": "🎓 Оценки (Noten)", "en": "🎓 Grades", "de": "🎓 Noten"},
    "grades.title": {"ru": "🎓 Оценки", "en": "🎓 Grades", "de": "🎓 Noten"},
    "grades.overall_points": {
        "ru": "Общий средний (баллы 0–15): {avg}",
        "en": "Overall average (points 0–15): {avg}",
        "de": "Gesamtschnitt (Punkte 0–15): {avg}",
    },
    "grades.overall_marks": {
        "ru": "Общий средний (оценки 1–6): {avg}",
        "en": "Overall average (grades 1–6): {avg}",
        "de": "Gesamtschnitt (Noten 1–6): {avg}",
    },
    "grades.scale_q": {
        "ru": "Какая шкала у предмета «{title}»?",
        "en": "Which grading scale does “{title}” use?",
        "de": "Welche Notenskala hat „{title}“?",
    },
    "grades.scale.points": {
        "ru": "Баллы 0–15",
        "en": "Points 0–15",
        "de": "Punkte 0–15",
    },
    "grades.scale.marks": {
        "ru": "Оценки 1–6",
        "en": "Grades 1–6",
        "de": "Noten 1–6",
    },
    "grades.choose": {"ru": "Выбери предмет:", "en": "Pick a subject:", "de": "Wähle ein Fach:"},
    "grades.empty": {
        "ru": "Предметов пока нет.",
        "en": "No subjects yet.",
        "de": "Noch keine Fächer.",
    },
    "grades.new_subj_btn": {"ru": "➕ Новый предмет", "en": "➕ New subject", "de": "➕ Neues Fach"},
    "grades.subj_not_found": {
        "ru": "Предмет не найден.",
        "en": "Subject not found.",
        "de": "Fach nicht gefunden.",
    },
    "grades.schnitt": {"ru": "Средний: {avg}", "en": "Average: {avg}", "de": "Schnitt: {avg}"},
    "grades.no_avg": {"ru": "—", "en": "—", "de": "—"},
    "grades.no_grades": {
        "ru": "Оценок пока нет.",
        "en": "No grades yet.",
        "de": "Noch keine Noten.",
    },
    "grades.kind.sa": {"ru": "SA", "en": "SA", "de": "SA"},
    "grades.kind.ka": {"ru": "KA", "en": "KA", "de": "KA"},
    "grades.kind.muendlich": {"ru": "Устно", "en": "Oral", "de": "Mündlich"},
    "grades.formula_note": {
        "ru": "Формула: маленькие = (2·KA + Устно)/3, итог = (SA + маленькие)/2",
        "en": "Formula: small = (2·KA + Oral)/3, total = (SA + small)/2",
        "de": "Formel: klein = (2·KA + Mündlich)/3, gesamt = (SA + klein)/2",
    },
    "grades.formula_note_marks": {
        "ru": "Формула: каждая SA ×2, устная ×1 (напр. SA 4, Устно 5 → 4.33)",
        "en": "Formula: each SA ×2, oral ×1 (e.g. SA 4, Oral 5 → 4.33)",
        "de": "Formel: jede SA ×2, mündlich ×1 (z. B. SA 4, Mündlich 5 → 4,33)",
    },
    "grades.enter_value": {
        "ru": "Введи значение {min}–{max} ({kind}):",
        "en": "Enter a value {min}–{max} ({kind}):",
        "de": "Wert {min}–{max} eingeben ({kind}):",
    },
    "grades.err.value": {
        "ru": "Нужно целое число от {min} до {max}.",
        "en": "Please enter a whole number from {min} to {max}.",
        "de": "Bitte eine ganze Zahl von {min} bis {max}.",
    },
    "grades.enter_name": {
        "ru": "Введи название предмета:",
        "en": "Enter the subject name:",
        "de": "Name des Fachs eingeben:",
    },
    "grades.enter_new_name": {
        "ru": "Введи новое название предмета:",
        "en": "Enter the new subject name:",
        "de": "Neuen Namen des Fachs eingeben:",
    },
    "grades.rename_btn": {"ru": "✏️ Переименовать", "en": "✏️ Rename", "de": "✏️ Umbenennen"},
    "grades.del_subj_btn": {
        "ru": "🗑 Удалить предмет",
        "en": "🗑 Delete subject",
        "de": "🗑 Fach löschen",
    },
    "grades.confirm_del_subj": {
        "ru": "Удалить предмет «{title}» со всеми оценками?",
        "en": "Delete subject “{title}” with all its grades?",
        "de": "Fach „{title}“ mitsamt allen Noten löschen?",
    },
    "grades.del_grade_btn": {
        "ru": "🗑 Удалить оценку",
        "en": "🗑 Delete a grade",
        "de": "🗑 Note löschen",
    },
    "grades.pick_del": {
        "ru": "Какую оценку удалить?",
        "en": "Which grade should I delete?",
        "de": "Welche Note soll gelöscht werden?",
    },
    "grades.back_to_subjects": {
        "ru": "⬅️ К предметам",
        "en": "⬅️ To subjects",
        "de": "⬅️ Zu den Fächern",
    },
    "grades.back_to_subject": {"ru": "⬅️ К предмету", "en": "⬅️ To the subject", "de": "⬅️ Zum Fach"},
    "grades.limit_subjects": {
        "ru": "Слишком много предметов (макс {max}).",
        "en": "Too many subjects (max {max}).",
        "de": "Zu viele Fächer (max. {max}).",
    },
    "grades.limit_grades": {
        "ru": "Слишком много оценок в предмете (макс {max}).",
        "en": "Too many grades in this subject (max {max}).",
        "de": "Zu viele Noten in diesem Fach (max. {max}).",
    },
}

# ----- Українська (жартівлива версія 🇺🇦, за бажанням користувача) -----
_UK: dict[str, str] = {
    "common.menu_btn": "⬅️ До хати",
    "common.cancel_btn": "⬅️ Йой, не треба",
    "common.back_btn": "⬅️ Взад",
    "common.yes_delete": "✅ Так, у смітник!",
    "common.too_long": "Йой, задовго (макс {max}). Коротше, будь ласка:",
    "common.try_again": "⚠️ {err}\nНу, ще разок:",
    "menu.title": "Головне меню — тицяй, шо треба:",
    "menu.unknown_module": "Шо це за модуль? Не знаю такого 🤷",
    "module.shelves": "🗄 Шафа пам'яті",
    "module.reminders": "⏰ Нагадайки",
    "module.calendar": "📅 Календарик",
    "module.language": "🌐 Мова / Language",
    "lang.title": "Обирай мову, козаче:",
    "start.greeting": "Здоров, {name}! Я ShymaBot, твій кишеньковий помічник 🫡",
    "stop.bye": "Бувай, {name}! Не пропадай!",
    "support.text": "{name}, як шо припекло — пиши в підтримку: @shyma_6",
    "msg.received": "Прийняв! Шо з цим робити — не знаю, але прийняв 😄",
    "shelf.choose": "Обирай полицю:",
    "shelf.empty": "Полиць нема. Порожньо, як у гаманці перед зарплатою 🫠",
    "shelf.new_btn": "➕ Нова полиця",
    "shelf.not_found": "Полиця десь загубилась 🤔",
    "shelf.back_to_shelves": "⬅️ До полиць",
    "shelf.notes": "Нотатки:",
    "shelf.no_notes": "Нотаток нема. Чисто, аж блищить ✨",
    "shelf.delete_btn": "🗑 Знести полицю",
    "shelf.confirm_del": "Знести полицю разом з усіма нотатками? Точно-точно?",
    "shelf.enter_name": "Як назвемо нову полицю?",
    "shelf.name_empty": "Пуста назва — то не назва. Ще раз:",
    "note.new_btn": "➕ Нова нотатка",
    "note.not_found": "Нотатка втекла 🏃",
    "note.title": "📝 Нотатка:",
    "note.edit_btn": "✏️ Поправити",
    "note.delete_btn": "🗑 Знести",
    "note.back_to_shelf": "⬅️ До полиці",
    "note.enter_text": "Пиши текст нотатки:",
    "note.enter_new_text": "Пиши новий текст нотатки:",
    "note.empty_preview": "(пустка)",
    "rem.title": "⏰ Нагадайки",
    "rem.list_label": "Ось шо маємо:",
    "rem.empty": "Поки нічого. Живи спокійно 😌",
    "rem.new_btn": "➕ Нова нагадайка",
    "rem.when_q": "Коли тобі нагадати, золотко?",
    "rem.preset.in1h": "⏱ За годинку",
    "rem.preset.in3h": "⏱ За три годинки",
    "rem.preset.eve": "🌙 Сьогодні ввечері",
    "rem.preset.tom_morning": "☀️ Завтра зранку",
    "rem.preset.tom_eve": "🌆 Завтра ввечері",
    "rem.preset.weekend": "📅 На вихідних",
    "rem.exact_btn": "⚙️ Точний час / повтор",
    "rem.choose_kind": "Який тип нагадайки?",
    "rem.kind.once": "Разова",
    "rem.kind.daily": "Щодня",
    "rem.kind.weekly": "Щотижня",
    "rem.kind.monthly": "Щомісяця",
    "rem.kind.interval": "Інтервал",
    "rem.hint.dt": "Пиши дату й час: ДД.ММ.РРРР ГГ:ХХ (наприклад 25.12.2026 09:30)",
    "rem.hint.time": "Пиши час: ГГ:ХХ (наприклад 09:30)",
    "rem.hint.interval": "Пиши інтервал: 30m / 2h / 1d (м/ч/д)",
    "rem.enter_text": "А тепер — шо тобі нагадати?",
    "rem.created": "✅ Нагадайка готова. Не забуду, слово козака!",
    "rem.not_found": "Нагадайка десь ділась 🤔",
    "rem.to_list": "⬅️ До списку",
    "rem.card": "⏰ Нагадайка\n\nТекст: {text}\nКоли: {when}\nПовтор: {repeat}\nСтатус: {status}",
    "rem.status.active": "працює",
    "rem.status.paused": "дрімає",
    "rem.text_btn": "✏️ Текст",
    "rem.time_btn": "🕐 Час",
    "rem.pause_btn": "⏸ Хай подрімає",
    "rem.resume_btn": "▶️ Буди!",
    "rem.confirm_del": "Знести нагадайку? Точно?",
    "rem.enter_new_text": "Пиши новий текст нагадайки:",
    "rem.new_time": "🕐 Новий час ({kind}).\n{hint}",
    "rem.time_updated": "✅ Час поміняв.",
    "rem.snoozed_until": "💤 Відклав на {when}. Спи спокійно.",
    "rem.snooze_failed": "Не вийшло відкласти (нагадайка загубилась).",
    "rem.snooze.10": "💤 +10 хв",
    "rem.snooze.60": "💤 +1 годинка",
    "rem.snooze.tom": "💤 Завтра 09:00",
    "rem.repeat.once": "разово",
    "rem.repeat.daily": "щодня",
    "rem.repeat.weekly": "щотижня",
    "rem.repeat.monthly": "щомісяця",
    "rem.repeat.every_d": "кожні {n} дн.",
    "rem.repeat.every_h": "кожні {n} год.",
    "rem.repeat.every_m": "кожні {n} хв.",
    "rem.err.dt_format": "Формат такий: ДД.ММ.РРРР ГГ:ХХ (наприклад 25.12.2026 09:30)",
    "rem.err.past": "Це вже було, машини часу нема 🙃 Давай майбутнє.",
    "rem.err.time_format": "Формат часу: ГГ:ХХ (наприклад 09:30)",
    "rem.err.interval_format": "Формат інтервалу: 30m / 2h / 1d (м/ч/д)",
    "rem.err.interval_min": "Мінімум — 1 хвилина. Швидше не встигну 🏃",
    "rem.err.interval_max": "Занадто довго (макс ~рік). Я стільки не всиджу.",
    "rem.err.unknown_kind": "Шо це за тип? Не знаю такого.",
    "rem.err.unknown_preset": "Шо це за пресет? Не знаю такого.",
    "cal.intro": "📅 Календарик\n\nПідключи опублікований календар за посиланням — я "
                 "читатиму події і нагадуватиму перед початком (за замовчуванням за {lead} хв, "
                 "потім підкрутиш).\n(Про «весь день»-події нагадаю зранку.)",
    "cal.connect_btn": "🔗 Підключити календар",
    "cal.connect_hint": "Кидай посилання на опублікований календар (webcal://… або https://….ics).\n\n"
                        "iCloud: Календар → налаштування календаря → «Відкритий календар» → "
                        "скопіювати посилання.\nПорада: публікуй окремий календар «Bot», а не основний.",
    "cal.title_line": "📅 Календарик: {name}",
    "cal.checked": "Перевірено: {when}",
    "cal.not_synced": "ще не синхронізувався",
    "cal.error_line": "⚠️ Халепа: {err}",
    "cal.upcoming": "Найближчі події:",
    "cal.no_events": "Подій не бачу. Відпочивай 😎",
    "cal.lead_line": "Нагадаю за {lead} до початку.",
    "cal.sync_btn": "🔄 Оновити зараз",
    "cal.lead_btn": "⏱ За скільки",
    "cal.change_url_btn": "🔗 Змінити посилання",
    "cal.disconnect_btn": "🗑 Відключити",
    "cal.all_day": "(весь день)",
    "cal.syncing": "🔄 Дивлюсь, шо там у календарі…",
    "cal.confirm_del": "Відключити календар? Підписка і всі завантажені події підуть у смітник.",
    "cal.delyes_btn": "✅ Так, відключай",
    "cal.lead_screen": "⏱ Зараз нагадую за {lead} до початку події.\nЗа скільки нагадувати?",
    "cal.lead_custom_btn": "✏️ Своє",
    "cal.lead_custom_hint": "Пиши свій час: число хвилин або з одиницею — 45m / 2h / 1d (м/ч/д).\n"
                            "Від {min} хв до {max_days} днів.",
    "cal.lead_set": "✅ Нагадуватиму за {lead}. Домовились!",
    "cal.connected": "✅ Календар підключено. Тепер я в курсі твоїх справ 😏",
    "cal.db_missing": "⚠️ База не налаштована — нема куди зберегти підписку.",
    "cal.try_other": "⚠️ {err}\nДавай інше посилання:",
    "cal.event_soon": "📅 Скоро подія: {summary}\n🕐 {when}",
    "cal.event_today": "📅 Сьогодні: {summary} (весь день)",
    "cal.unit.min": "{n} хв",
    "cal.unit.hour": "{n} год",
    "cal.unit.day": "{n} дн",
    "cal.err.not_url": "Це не схоже на посилання. Треба щось типу webcal://… або https://…",
    "cal.err.http": "сервер календаря відповів {code} (не в гуморі)",
    "cal.err.network": "сервер календаря не відповідає (мережа/таймаут)",
    "cal.err.bad_ics": "не зміг розібрати файл календаря (битий ICS?)",
    "cal.err.bad_date": "дивний формат дати у фіді",
    "cal.err.internal": "внутрішня халепа синхронізації",
    "cal.err.lead_format": "Формат: число хвилин або 45m / 2h / 1d (м/ч/д)",
    "cal.err.lead_min": "Мінімум — {min} хвилин.",
    "cal.err.lead_max": "Максимум — {max_days} днів.",
    "module.grades": "🎓 Оцінки (Noten)",
    "grades.title": "🎓 Оцінки",
    "grades.overall_points": "Загальний середній (бали 0–15): {avg}",
    "grades.overall_marks": "Загальний середній (оцінки 1–6): {avg}",
    "grades.scale_q": "Яка шкала у предмета «{title}»?",
    "grades.scale.points": "Бали 0–15",
    "grades.scale.marks": "Оцінки 1–6",
    "grades.choose": "Обирай предмет:",
    "grades.empty": "Предметів нема. Канікули? 🏖",
    "grades.new_subj_btn": "➕ Новий предмет",
    "grades.subj_not_found": "Предмет кудись зник 🤔",
    "grades.schnitt": "Середній: {avg}",
    "grades.no_avg": "—",
    "grades.no_grades": "Оцінок ще нема. Поки що все чисто 😇",
    "grades.kind.sa": "SA",
    "grades.kind.ka": "KA",
    "grades.kind.muendlich": "Усно",
    "grades.formula_note": "Формула: маленькі = (2·KA + Усно)/3, разом = (SA + маленькі)/2",
    "grades.formula_note_marks": "Формула: кожна SA ×2, усна ×1 (напр. SA 4, Усно 5 → 4.33)",
    "grades.enter_value": "Пиши значення {min}–{max} ({kind}):",
    "grades.err.value": "Треба ціле число від {min} до {max}. І не «з мінусом» 🙃",
    "grades.enter_name": "Як звати предмет?",
    "grades.enter_new_name": "Нова назва предмета:",
    "grades.rename_btn": "✏️ Перейменувати",
    "grades.del_subj_btn": "🗑 Знести предмет",
    "grades.confirm_del_subj": "Знести «{title}» з усіма оцінками? Директор не дізнається 😉",
    "grades.del_grade_btn": "🗑 Знести оцінку",
    "grades.pick_del": "Яку оцінку зносимо?",
    "grades.back_to_subjects": "⬅️ До предметів",
    "grades.back_to_subject": "⬅️ До предмета",
    "grades.limit_subjects": "Забагато предметів (макс {max}). Ти шо, вундеркінд?",
    "grades.limit_grades": "Забагато оцінок (макс {max}).",
}

for _key, _text in _UK.items():
    _T[_key]["uk"] = _text


def t(lang: str, key: str, **fmt) -> str:
    """Перевод по ключу с подстановкой плейсхолдеров. Fallback: en -> ru -> сам ключ."""
    entry = _T.get(key)
    if entry is None:
        return key
    text = entry.get(lang) or entry.get("en") or entry.get("ru") or key
    return text.format(**fmt) if fmt else text


def norm_lang(code: str | None) -> str:
    """language_code Telegram ('ru-RU', 'de', …) -> ru/en/de (иначе en)."""
    if code:
        prefix = code.split("-")[0].lower()
        if prefix in LANGS:
            return prefix
    return DEFAULT_LANG


async def user_lang(update: Update, context: ContextTypes.DEFAULT_TYPE | None) -> str:
    """Язык пользователя: кэш диалога -> БД -> language_code Telegram (и сохраняем,
    чтобы фоновые отправки /tick знали язык)."""
    if context is not None:
        cached = context.user_data.get("lang")
        if cached in LANGS:
            return cached
    tg_user = update.effective_user
    lang = await get_user_language(tg_user.id)
    if lang not in LANGS:
        lang = norm_lang(tg_user.language_code)
        await set_user_language(tg_user.id, lang)
    if context is not None:
        context.user_data["lang"] = lang
    return lang
