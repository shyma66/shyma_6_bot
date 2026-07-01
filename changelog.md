# changelog.md

> Каждое внедрённое изменение — одна строка, новейшие сверху, с датой.
> Формат: `- ГГГГ-ММ-ДД — Что (кратко) — файлы — Bezug: improvements #NN`

- 2026-07-01 — Напоминания UX инкремент 1: пресеты времени (Через 1/3ч, Сегодня вечером, Завтра утром/вечером, Выходные) + Snooze-кнопки под пришедшим напоминанием (+10м/+1ч/Завтра) — features/reminders/schedule.py, repo.py, handlers.py, tick.py — Bezug: improvements #09 #10
- 2026-07-01 — Фикс «мёртвых кнопок» после засыпания Render: answer() сделан некритичным, добавлены edit_safely/answer_safely (глотают устаревший callback и «message not modified»); держать инстанс тёплым внешним cron на /tick — core/dashboard.py, core/modules.py, features/shelves/handlers.py, features/reminders/handlers.py — Bezug: improvements #08
- 2026-06-30 — Шаг 4: модуль «Напоминания» — таблица Reminder, повторы once/daily/weekly/interval (TZ Europe/Berlin→UTC), редактируемый текст, пауза; эндпоинт /tick (секрет X-Tick-Key) + process_due для внешнего cron (5 мин); +tzdata — DataBase/models.py, features/reminders/*, core/modules.py, bot_start.py, requirements.txt — Bezug: business_plan Schritt 4, improvements #01 #02
- 2026-06-30 — Шаг 3: модуль «Шкаф» — таблицы Shelf/Note + полный CRUD полок/заметок (диалог ввода), изоляция по владельцу, лимиты длины; ssl только для postgres-URL — DataBase/models.py, DataBase/database.py, features/shelves/*, core/modules.py, bot_start.py — Bezug: business_plan Schritt 3, improvements #07
- 2026-06-30 — Шаг 2: скелет дашборда — реестр модулей + инлайн-меню на /start + callback-роутер; 3 модуля-заглушки (Шкаф/Напоминания/Календарь) — core/registry.py, core/dashboard.py, core/modules.py, core/__init__.py, handlers/start_command.py, bot_start.py — Bezug: business_plan Schritt 2
- 2026-06-30 — Фикс БД-URL: нормализация строки Neon под asyncpg (драйвер + убраны sslmode/channel_binding, ssl=True); подключение проверено вживую — DataBase/database.py — —
- 2026-06-30 — Шаг 1: БД-слой (SQLAlchemy async + Neon) + модель User + авто-регистрация юзера на /start (мягкая деградация без DATABASE_URL) — DataBase/models.py, DataBase/database.py, DataBase/__init__.py, bot_start.py, handlers/start_command.py, requirements.txt — Bezug: business_plan Schritt 1
- 2026-06-23 — Стек уточнён по факту: python-telegram-bot 22.3 (не aiogram), БД Neon (Postgres), старт разработки с БД-схемы + регистрации юзера на /start — business_plan.md — —
- 2026-06-23 — В .gitignore добавлены reminders.json (локальные данные) и price_checker.py (проектно-чужой файл) — .gitignore — —
- 2026-06-23 — Репозиторий очищен: добавлен .gitignore, venv/ и __pycache__ убраны из отслеживания (файлы на диске сохранены) — .gitignore, changelog.md — —
- 2026-06-23 — БД-решение закрыто: хранилища в боте нет → заводим Neon (Postgres) с нуля — business_plan.md — —
- 2026-06-23 — Учтено: webhook уже в проде (переиспользуем); /tick-пинг оставлен только для таймера напоминаний; БД — переиспользовать существующую или Neon — business_plan.md — —
- 2026-06-23 — Решения: БД Neon (Render free эфемерен), напоминания через внешний cron+/tick (free-инстанс засыпает), старт с модуля «Шкаф», связь шкаф↔напоминания отложена — business_plan.md, improvements.md — —
- 2026-06-23 — План v2: запись в календарь через .ics с подтверждением юзера + редактируемый текст напоминаний — business_plan.md, improvements.md — —
- 2026-06-23 — Финализирован план: календарь read-only через URL-подписку (убраны Apple ID/CalDAV/шифрование секрета) — business_plan.md, improvements.md — —
- 2026-06-23 — Проектная документация создана (business_plan, improvements, changelog, CLAUDE.md) — — —
