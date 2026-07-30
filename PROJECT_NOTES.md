# PROJECT_NOTES.md — справочник по проекту shyma_6_bot

> Назначение: «холодный старт» для новой сессии Claude Code (когда контекст/кэш
> очищен). Здесь то, что НЕ выводится за минуту из кода: карта фич, защищённые
> файлы, ловушки, как тестировать без полного стека, инфраструктура.
> Правила поведения — в `CLAUDE.md`. Обзор для человека — в `info.txt`.
> Хронология изменений — `changelog.md`. Открытые идеи — `improvements.md`.
> Последнее обновление: 2026-07-31.

---

## 1. Что это

Мультиязычный Telegram-бот — личный помощник: заметки, напоминания, календарь
(ICS), калькулятор оценок. Уровни доступа + админ-панель. Плюс **Telegram Mini App**
— полноценный веб-интерфейс со ВСЕМИ модулями (главное меню + Полка/Напоминания/
Календарь/Оценки/Настройки/Админ), раздаётся тем же сервисом.

**Стек:** python-telegram-bot 22.3 + FastAPI (вебхук). Хостинг **Render** (free tier,
холодный старт ~30–60 с). БД **Neon Postgres** (SQLAlchemy async + asyncpg), с горячим
резервом. **Python 3.11.9** (`runtime.txt`). Язык ответов ассистента — **русский**.

---

## 2. Карта репозитория

```
bot_start.py            ← точка входа: FastAPI app + PTB, вебхук, /tick, монтаж Mini App  [ЗАЩИЩЁН]
core/
  admin.py              ← уровни доступа (admin/prime/common), флаги модулей, журнал ошибок
  dashboard.py          ← дашборд/меню, edit_safely, CALLBACK_PREFIX, HOME_KEY
  i18n.py               ← словарь переводов ru/en/de/uk, t(), user_lang()
  registry.py           ← реестр модулей (register/Module/MODULES)
  modules.py            ← core-модули (🌐 Язык последним в меню)
DataBase/
  database.py           ← движки, выбор активной БД, зеркалирование, CRUD профиля/consent/prime
  models.py             ← ORM-модели (таблицы)                                            [ЗАЩИЩЁН по духу]
features/
  reminders/            ← handlers.py, repo.py, schedule.py (тайм-математика), tick.py
  calendar/             ← handlers.py, repo.py, sync.py (ICS fetch/parse), tick.py
  grades/               ← handlers.py, repo.py, logic.py (формулы средних)
  shelves/              ← «Шкаф памяти»: handlers.py, repo.py
  settings/             ← согласие + настройки (язык, политика, удалить данные)
  admin/                ← handlers.py: админ-панель + prime-заявки
  backup/               ← service.py: суточное зеркалирование активной БД в резерв
webapp/
  api.py                ← JSON-API для Mini App (initData-аутентификация): все модули
  reminders/index.html  ← сам Mini App (vanilla JS, один файл): меню + ВСЕ 5 модулей
handlers/               ← /start, /stop, /support, handle_message (+ старый неиспользуемый код)
```

`handlers/calendar_command.py`, `handlers/guiz_game.py` — легаси, не подключены в
`bot_start.py`. Не трогать без причины.

---

## 3. Фичи (кратко; подробности для человека — в info.txt)

**Команды:** `/start /stop /support /whoami /prime /cancel /app` (`/app` — кнопка
запуска Mini App).

**Уровни доступа:** `common < prime < admin`.
- **admin** — по числовому `ADMIN_ID` из env (НЕ по нику). Опознаётся `core.admin.is_admin`.
- **prime** — членство в БД (таблица `prime_users`), переживает рестарт, попадает в резерв.
- Заявки на prime: кнопка/‹/prime› → очередь в админ-панели → одобрение/отклонение
  или добавление по ID. Кэш prime в `core.admin` (при удалении данных чистится
  `forget_prime`).

**Модули меню:**
- 🗄 **Шкаф памяти** (shelves): полки + заметки, CRUD. Лимиты: полка ≤255, заметка ≤4000.
- ⏰ **Напоминания**: папки «через N часов» (в котором часу 00–23 / через N),
  «через N дней» (1–30 + неделя/месяц/полгода/год), «точное/повтор» (once/daily/
  weekly/monthly/interval), выбор минут сеткой шага 5. Snooze-кнопки только у разовых.
  Время местное (`REMINDER_TZ`, дефолт Europe/Berlin), хранится в UTC.
- 📅 **Календарь**: подписка на ОДИН публичный ICS-фид (пользователь НЕ создаёт события
  вручную — только ссылка). Синк по /tick + вручную. Настраиваемый lead-time. URL не
  логируется целиком (только домен).
- 🎓 **Оценки**: предметы + оценки. Две шкалы: points 0–15 (больше=лучше) и marks 1–6.
  Типы SA/KA/Mündlich. Формулы средних — `features/grades/logic.py`. Лимиты: 30 предметов,
  60 оценок/предмет.
- ⚙️ **Настройки**: язык, перечитать политику, «удалить все мои данные» (стирает контент
  + профиль из ОБЕИХ БД).
- 🛠 **Админ-панель** (только admin): вкл/выкл модулей + уровень (всем/prime), prime-доступ,
  статус БД (только просмотр), журнал ошибок.

**Согласие (Datenschutz):** жёсткий гейт — без «✅ Согласен» меню недоступно (и в боте, и
в Mini App).

**Языки:** ru/en/de/uk (uk — шутливый стиль). Автоопределение по языку Telegram при первом
входе, дальше — по выбору. Переводы в `core/i18n.py` (бот) и в inline-`DICT` в `index.html`
(Mini App) — держать синхронными вручную.

---

## 4. Mini App (webapp/) — важные детали

- **Аутентификация:** фронт шлёт `X-Telegram-Init-Data`; сервер проверяет HMAC-SHA256
  (secret = HMAC("WebAppData", BOT_TOKEN)) в `webapp/api.py::verify_init_data`, отбрасывает
  initData старше 24 ч. Изоляция по владельцу, проверка `has_consent`. Реальная защита
  admin/prime — на сервере, скрытие экрана в UI защитой НЕ считается.
- **Все 5 модулей РАБОЧИЕ** (не заглушки; дизайн Nocturne, инкременты июль 2026). Один
  плоский `S.screen` + стек `S.history`; экраны каждого модуля с префиксом. `modstub`
  остался как fallback, но по факту не используется.
  - Полка (Notes): `nshelves/nshelf/nnote/nnoteedit/nnewshelf/nrenameshelf`.
  - Напоминания: `list/when/hours/days/exact/calendar/time/text/detail`.
  - Календарь: `calmod` (пусто/подключено) `/calconnect/callead/calcustom`.
  - Оценки: `gsubjects/gsubject/gnewname/gnewscale/gaddgrade/gdelgrade/grename`.
  - Настройки: `settings/settingspolicy`. Админ: `adminhome/adminmods/adminprime/
    adminaddid/adminerrors/admindb`. Плюс `home` · `consent`. Старт: `consent` если нет
    согласия, иначе `home`.
- **Роли/флаги в меню** приходят из `GET /api/me` (name, lang, role, modules[disabled,
  prime_only]). Дизейбл/prime-only модуль у common даёт шторку (maint/prime). Серверный
  гейт `_gate(uid, reg_key)` (согласие + вкл/prime) на КАЖДОМ модульном эндпоинте; Админ —
  строгий `is_admin`. Фронтовый `api()` различает 403-«нет согласия» и 403-«модуль off/prime».
- **API (webapp/api.py, ~41 маршрутов):**
  - общее: `/api/me`, `/api/consent`, `/api/lang`, `/api/prime_request`.
  - напоминания: `/api/reminders` (GET/POST), `/{id}` (PATCH/DELETE), `/{id}/schedule`,
    `/{id}/toggle`, `/bulk_delete`, `/delete_all`.
  - полка: `/api/shelves` (GET/POST), `/{id}` (PATCH/DELETE), `/bulk_delete`,
    `/{id}/notes` (GET/POST), `/api/notes/{id}` (PATCH/DELETE).
  - настройки: `/api/settings/delete_data` (= erase_user во всех БД + forget_prime).
  - календарь: `/api/calendar` (GET/DELETE), `/connect`, `/sync`, `/lead`.
  - оценки: `/api/grades` (GET), `/grades/subjects` (POST), `/{id}` (PATCH/DELETE),
    `/{id}/grades` (POST), `/api/grades/grades/{id}` (DELETE). Средние считаются на
    СЕРВЕРЕ (`features/grades/logic`), в JS формулу не дублируем.
  - админ: `/api/admin` (GET), `/module/{key}/toggle|tier`, `/prime/allow|deny|add`,
    `/prime/{id}` (DELETE), `/errors/clear` — обёртки над core.admin + DataBase.
- **Кэш Mini App:** Telegram агрессивно кэширует. При КАЖДОМ изменении фронта бампать
  `_WEBAPP_VER` в `bot_start.py` (сейчас `"12"`) — он идёт в URL как `?v=`. Пользователю:
  полностью закрыть и переоткрыть Mini App.
- **Мгновенное открытие (perf):** профиль (`/api/me`) и напоминания кэшируются в
  `localStorage` (`cache.me`/`cache.reminders`); `bootFromCache()` рисует главный экран
  сразу, сервер обновляет в фоне (прячем холодный старт Render ~30–60 с). Кэш чистится при
  «удалить данные». Роль в кэше влияет только на UI — сервер всё равно проверяет `is_admin`.
- **Тема:** Настройки → Тема Авто/Светлая/Тёмная (`S.themePref`, localStorage); light-палитра
  в CSS, применяется ко всем экранам через `data-theme` на `.app`. Auto следит за Telegram.
- **Политика приватности:** ДОСЛОВНО как в боте — `policyFull` в DICT = `core/i18n.py
  "policy.text"` (4 языка), держать синхронным. Экран согласия + Настройки→Политика.
- **Ввод чисел/времени:** только тап-сетки (`numberGrid`/`.ncell`). НЕ возвращать нативные
  `<select>`/`<input type=time>`/самодельные колёса — колесо ломало скролл (render()
  пересобирает DOM), нативные пикеры схлопывались сами. Одна кнопка внизу (свой футер;
  `tg.MainButton.hide()`), guard() от двойного сабмита.
- **Safe-area:** фуллскрин (`requestFullscreen`); `--tg-safe-top`/`--tg-safe-bottom` из
  Telegram-инсетов (в фуллскрине `env(safe-area-*)` не приходит), иначе шапка/нижняя кнопка
  налезали на края.
- **Кнопка запуска** (`/app` инлайн + меню-кнопка бота) называется «App» (i18n
  `menu.open_app`), не «Reminders» — приложение мультимодульное.
- **Ограничение:** доставка шагом ~5 мин (cron раз в 5 мин) — точные «через 4 минуты»
  недостижимы; на экранах времени есть предупреждение `gran5`.

---

## 5. ⚠️ Ловушки (на чём легко обжечься)

1. **Защищённый core (CLAUDE.md §3):** `bot_start.py`, `DataBase/models.py`, `core/*`
   критичные части — менять только с явного разрешения. `webapp/api.py` и `index.html`
   не в списке защиты, но затрагивают безопасность — аккуратно.
2. **Git — split commits:** несколько раз выборочный `git add` разрывал фичу между
   коммитами (осиротевшие функции ломали деплой). ВСЕГДА проверять `git status` на
   «хвосты» перед тем как считать коммит завершённым; для цельной фичи — `git add -A`.
3. **CRLF/LF:** Windows — git ругается «LF will be replaced by CRLF». Это норма, не ошибка.
4. **Commit message в Bash:** PowerShell here-string синтаксис ломает сообщение. Использовать
   heredoc `git commit -F - <<'EOF' … EOF`. Заканчивать `Co-Authored-By: Claude…`.
5. **Секреты:** `.env`, `BOT_TOKEN`, `DATABASE_URL(_2)`, `TICK_SECRET`, `ADMIN_ID` — только
   в env/Render, НИКОГДА в коде/логах/этом файле. Ассистент `.env` не редактирует.
6. **i18n рассинхрон:** ключ, общий для бота и Mini App, добавлять И в `core/i18n.py`,
   И в `DICT` в `index.html`, во всех 4 языках. Экраны, которые есть ТОЛЬКО в Mini App
   (Полка/Календарь/Оценки/Настройки/Админ), живут в `DICT` — в `core/i18n.py` их нет.
   Исключение — `policyFull` в DICT обязан совпадать с `core/i18n.py "policy.text"`.
7. **Навигация (CLAUDE.md §10):** «‹ Назад» = один шаг назад к родителю; «🏠 Домой» =
   стартовый экран. Применять в КАЖДОМ экране.
8. **info.txt устарел** местами (напр. «через N часов 1–24» → сейчас 0–23; про Mini App
   там ничего нет). При расхождении — верить коду и этому файлу.

---

## 6. Как тестировать без полного стека (локально)

Полный стек локально НЕ запускается: `asyncpg` не установлен, `pydantic_core` сломан
(FastAPI не импортируется), Telegram/Neon недоступны. Проверять точечно:
- **Python-синтаксис:** `python -m py_compile <файлы>`.
- **JS-синтаксис фронта:** извлечь `<script>` из `index.html`, `node --check` / `new vm.Script`.
- **Чистые Python-функции:** извлечь через ast и прогнать (schedule, grades/logic).
- **Логика фронта:** vm-песочница с заглушками DOM/tg/fetch/localStorage — извлечь
  последний `<script>` из `index.html`, прогнать в `vm.createContext`, кликать по
  элементам с обработчиками (собрать дерево, найти по тексту), мокать fetch по URL. Так
  прогнаны все модули end-to-end (создание/правка/удаление, гейтинг, тема, кэш-старт).
  Ловушка теста: свой `let`-переменной в мок-fetch не конфликтовать с внешними (TDZ);
  клик по тексту брать самый ГЛУБОКИЙ элемент (иначе попадёшь в родителя-оверлей).
- **БД-логика:** через `aiosqlite` (не asyncpg). Помнить: SQLite не делает FK-каскады —
  `erase_user` удаляет явно в FK-безопасном порядке.

---

## 7. Инфраструктура

- **Вебхук:** Telegram шлёт апдейты на `POST /{BOT_TOKEN}`; поллинга нет.
- **Keep-warm:** `GET /healthz` (и `/`) — 200 без обращения к БД; внешний cron пингует
  раз в ~10 мин, чтобы Render не засыпал (free-tier спит после ~15 мин → холодный старт
  ~30–60 с при открытии Mini App). Neon НЕ будим этим пингом (бережём CU-hrs; его греет
  `/tick`).
- **/tick:** внешний cron (cron-job.org) раз в ~5–10 мин, защищён заголовком
  `X-Tick-Key == TICK_SECRET`. Отвечает **200 сразу**, работу делает в фоне
  (`_run_tick`, `_tick_busy` guard) — иначе cron отваливался по таймауту (30/70 с).
  За тик: рассылка созревших напоминаний + синк ICS + суточное зеркалирование БД +
  метка свежести активной БД.
- **Экономия Neon:** `NullPool` (соединение закрывается сразу) — иначе compute-часы
  выгорают от простаивающих соединений (был инцидент «110/100 CU-hrs»).
- **Горячий резерв БД:** `DATABASE_URL` (основная) + `DATABASE_URL_2` (резерв), одинаковая
  схема. При старте активной выбирается достижимая с самыми свежими данными (при равенстве
  — основная): авто-failover на резерв и авто-возврат. Раз в сутки активная копируется в
  резерв (макс. потеря — сутки). Переключение вручную из панели УБРАНО намеренно (только
  статус).
- **Ошибки:** полный traceback → лог Render; обычный юзер видит «идут технические работы»;
  админ получает текст в личку (антифлуд ≤1/мин на тип) + журнал в панели. Недоступность БД
  не роняет старт — сервис поднимается, БД-функции деградируют мягко.

---

## 8. Переменные окружения (.env / Render)

| Переменная | Назначение |
|---|---|
| `BOT_TOKEN` | Токен Telegram-бота (обяз.) |
| `WEBHOOK_URL` | Базовый https-адрес сервиса (обяз.; из него же строится URL Mini App) |
| `TICK_SECRET` | Секрет для `/tick` (заголовок `X-Tick-Key`) |
| `DATABASE_URL` | Основная база Neon |
| `DATABASE_URL_2` | Резервная база (горячий резерв) |
| `ADMIN_ID` | Числовой Telegram ID админа (узнать через `/whoami`) |
| `REMINDER_TZ` | Пояс напоминаний (дефолт `Europe/Berlin`) |
| `CALENDAR_LEAD_MINUTES` | Дефолтный lead-time календаря |

Контакт в политике конфиденциальности: **@shyma_6**.

---

## 9. Таблицы БД

`users` · `shelves`/`notes` · `reminders` · `calendar_feeds`/`calendar_events` ·
`grade_subjects`/`grade_entries` · `prime_users` · `prime_requests` · `app_settings`
(флаги модулей, уровни, метки свежести БД).

---

## 10. Что дальше (открытые направления)

- Все 5 модулей Mini App уже рабочие (июль 2026). Возможные улучшения: SVG-иконки как в
  дизайне (сейчас эмодзи ради единообразия с ботом), обновление кэша `cache.reminders`
  после мутаций (сейчас перезаписывается только на `loadList` → возможен краткий показ
  устаревших данных до фонового обновления).
- Следить за `improvements.md` (приоритеты 1–5) — туда падают идеи и security-находки.
