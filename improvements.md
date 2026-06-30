# improvements.md

> Список предложений по улучшению. Ничего не внедряется без согласования.
> Приоритет **1–5**, где **5 = самый высокий/срочный**.

## 1. Список типов

| Nr | Tipp (kurz)                                          | Prio (1–5) | Status |
|----|------------------------------------------------------|------------|--------|
| 01 | Напоминания через внешний cron + /tick (free засыпает)| 5          | offen  |
| 02 | Валидация ввода времени/интервалов напоминаний       | 4          | offen  |
| 03 | FSM-хранилище в БД вместо памяти (Neon)               | 4          | offen  |
| 04 | Retry + обработка ошибок при скачивании ICS-фида      | 3          | offen  |
| 05 | URL-подписку не писать в логи (полуприватные данные)  | 3          | offen  |
| 06 | Корректная сборка .ics (таймзоны, UID, экранирование) | 3          | offen  |
| 07 | Лимит длины текста напоминания/заметки, числа полок   | 2          | teilw. |

## 2. Детали

### [01] Напоминания через внешний cron + /tick — Prio: 5 — Datum: 2026-06-23
- Beschreibung: free web service Render засыпает через 15 мин -> in-process планировщик во сне не сработает.
- Wie umsetzen: хранить `next_fire_at` в БД (Neon); внешний бесплатный cron (cron-job.org / GitHub Actions)
  дёргает эндпоинт `/tick` раз в N минут; эндпоинт выбирает «созревшие» напоминания и отправляет их.
- Was wird geändert: `bot/features/reminders/tick.py`, маршрут webhook-сервера, схема БД.
- Status: offen

### [02] Валидация ввода времени/интервалов — Prio: 4 — Datum: 2026-06-23
- Beschreibung: время/интервал вводится текстом — нужны проверки и понятные ошибки.
- Wie umsetzen: парсинг + валидация в FSM-шаге, повтор запроса при ошибке.
- Was wird geändert: `bot/features/reminders/handlers.py`.
- Status: offen

### [03] FSM-хранилище в БД — Prio: 4 — Datum: 2026-06-23
- Beschreibung: MemoryStorage теряет состояние диалога при засыпании/рестарте free-инстанса.
- Wie umsetzen: БД-бэкенд (Neon) для aiogram FSM-storage.
- Was wird geändert: `bot/main.py`.
- Status: offen

### [04] Retry + обработка ошибок ICS-фида — Prio: 3 — Datum: 2026-06-23
- Beschreibung: фид может временно не скачиваться или приходить битым.
- Wie umsetzen: таймауты, повторы с backoff, безопасный парсинг, лог ошибки без падения воркера.
- Was wird geändert: `bot/features/calendar/sync.py`.
- Status: offen

### [05] URL-подписку не логировать — Prio: 3 — Datum: 2026-06-23
- Beschreibung: по ссылке видно содержимое календаря — нельзя выводить в логи.
- Wie umsetzen: маскировать/исключать поле URL в логировании.
- Was wird geändert: `bot/features/calendar/*`, настройка логов.
- Status: offen

### [06] Корректная сборка .ics — Prio: 3 — Datum: 2026-06-23
- Beschreibung: событие для «добавить в календарь» должно открываться без ошибок на iOS/macOS.
- Wie umsetzen: правильные VEVENT-поля (UID, DTSTART/DTEND, таймзона, экранирование текста) через `icalendar`.
- Was wird geändert: `bot/features/calendar/ics_builder.py`.
- Status: offen

### [07] Лимиты длины/количества — Prio: 2 — Datum: 2026-06-23
- Beschreibung: защита от разрастания данных одного юзера.
- Wie umsetzen: проверка лимитов перед сохранением.
- Was wird geändert: `bot/features/shelves/handlers.py`, `bot/features/reminders/handlers.py`.
- Status: teilweise — для заметок/полок лимиты добавлены (Шаг 3: title ≤255, note ≤4000);
  для напоминаний и лимита числа полок — ещё offen.
