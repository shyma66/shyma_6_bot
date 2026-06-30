# changelog.md

> Каждое внедрённое изменение — одна строка, новейшие сверху, с датой.
> Формат: `- ГГГГ-ММ-ДД — Что (кратко) — файлы — Bezug: improvements #NN`

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
