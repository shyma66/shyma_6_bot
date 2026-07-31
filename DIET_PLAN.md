# DIET_PLAN.md — Kalorien-Coach (Calorie & Macro Tracker)

> Roadmap для нового модуля Mini App «Калории». Source of truth дизайна —
> `Kalorien Tracker.dc.html` (Nocturne, 14 экранов, light+dark). Правила —
> `CLAUDE.md`. Хронология — `changelog.md`. Идеи/находки — `improvements.md`.
> Статус: **черновик на согласование** (перед кодом). Создан 2026-07-31.

---

## 1. Ziel (что строим)

Трекер калорий и макросов (kcal, белки, жиры, углеводы, сахар) как **новый
модуль** существующего Telegram Mini App. Ядро: онбординг с расчётом TDEE →
дневник питания по приёмам пищи → дашборд с кольцом калорий и макро-барами →
расход (burn) → статистика/графики → premium через Telegram Stars.

**Не** отдельный продукт, а сиблинг к Напоминаниям/Полке/Календарю/Оценкам на
той же дизайн-системе Nocturne.

## 2. Размещение — как пользователь попадает в «Калории»

Идея: приложение = **«меню приложений»**. Открываешь Mini App → видишь список
модулей → один из них «🍎 Калории».

```
Telegram-бот (@shyma_6_bot)
   │  /start  ·  кнопка меню «App»  ·  /app
   ▼
┌───────────────────────────────────────────────────────────┐
│  ГЛАВНОЕ МЕНЮ  (webapp/reminders/index.html, ?v=13)        │
│  «Привет, {имя} 👋»                                        │
│                                                           │
│   🗄  Полка памяти                                         │
│   ⏰  Напоминания                                          │
│   📅  Календарь                                            │
│   🎓  Оценки                                               │
│   ⚙️  Настройки                                            │
│   🛠  Админ-панель (только admin)                          │
│   🍎  Калории          ◄────── НОВЫЙ МОДУЛЬ                │
└───────────────┬───────────────────────────────────────────┘
                │ тап по «🍎 Калории»
                │ (webview переходит на /webapp/diet/, initData
                │  переносится через sessionStorage)
                ▼
┌───────────────────────────────────────────────────────────┐
│  МОДУЛЬ «КАЛОРИИ»  (webapp/diet/index.html, свой ?v=)      │
│                                                           │
│   первый вход  → Онбординг: Welcome → Профиль ×5 → TDEE   │
│   потом        → HOME/Дашборд (кольцо калорий + макросы)  │
│                    ├─ ＋ Добавить еду → Manual → Amount    │
│                    │                       → в Дневник     │
│                    ├─ 📒 Дневник (по приёмам пищи)         │
│                    ├─ 🔥 Расход                            │
│                    ├─ 📊 Статистика ⭐ (v2)                │
│                    └─ ⚙️ Настройки (v2)                    │
│                                                           │
│   «🏠 В меню»  → назад на /webapp/reminders/ (главное меню)│
└───────────────────────────────────────────────────────────┘
```

Итого: остальные модули (Полка/Напоминания/…) живут ВНУТРИ одного файла
`reminders/index.html`. «Калории» — **отдельный файл** `diet/index.html`, но в меню
выглядит как ещё один пункт; переход туда/обратно — навигацией webview, а
аутентификация не теряется благодаря мосту `sessionStorage` (см. ниже).

## 3. Struktur (архитектура и интеграция)

- **Стек:** vanilla JS, один файл — как весь существующий Mini App. **Без** React/
  Vite/новых зависимостей (запрет CLAUDE.md §3).
- **Файл:** `webapp/diet/index.html` — отдельный Mini App (свой `?v=`,
  `_WEBAPP_DIET_VER` в `bot_start.py`). Не раздуваем 1700-строчный reminders-файл.
- **Точка входа:** новая строка модуля **«🍎 Калории»** в главном меню
  (`webapp/reminders/index.html`). Тап → переход webview на `/webapp/diet/?v=N`.
- **Мост initData:** Telegram отдаёт `initData` при запуске; при переходе между
  двумя HTML он теряется. Решение: обе страницы пишут `tg.initData` в
  `sessionStorage` (когда он есть) и читают `tg.initData || sessionStorage`. Так
  аутентификация переживает переход меню↔диета в обе стороны.
- **Возврат:** «🏠 В меню» из диеты → переход на `/webapp/reminders/?v=M`.
- **БД:** новые таблицы в НОВОМ файле `features/diet/models.py`, импортирует
  существующий `Base` → регистрируются в `Base.metadata` → создаются через
  `create_all` (проект без Alembic). **Защищённый `DataBase/models.py` не трогаем.**
  Импорт нового модуля моделей — до `init_db` (через `webapp/api.py`), чтобы
  классы зарегистрировались.
- **API:** новые эндпоинты `/api/diet/*` в `webapp/api.py` (не защищён), та же
  initData-аутентификация `_auth`, серверный `_gate(uid,"diet")` (согласие +
  вкл/prime), учёт согласия как везде.
- **Иконки:** эмодзи (как в остальных модулях), НЕ Phosphor-шрифт из дизайна —
  ради единообразия и без CDN-зависимости.
- **Тема/i18n/кэш:** переиспользуем паттерны существующего app (data-theme,
  DICT ru/en/de/uk, localStorage cache-first мгновенное открытие).
- **Цвета графиков** (единственное исключение из accent-mono, только внутри
  диаграмм): kcal `#F97316`, protein `#F43F5E`, carbs `#3B82F6`, fat `#EAB308`,
  sugar `#A855F7`, success/green `#22C55E`.

## 4. Data model (Postgres, features/diet/models.py)

```
diet_profiles(user_id PK/FK, age, height_cm, weight_kg, goal enum[lose|maintain|gain],
              activity enum[sedentary|light|very], tdee, daily_target_kcal,
              protein_target_g, units enum[metric|imperial], updated_at)
diet_foods(id PK, owner_id FK nullable, source enum[db|manual|barcode], name, brand,
           barcode nullable, kcal_100, protein_100, fat_100, carb_100, sugar_100)
diet_favorites(user_id FK, food_id FK, default_amount_g, created_at)  -- uniq(user,food)
diet_entries(id PK, user_id FK, date, meal enum[breakfast|lunch|dinner|snack],
             food_id FK, amount, unit enum[g|ml|pcs], kcal, protein, fat, carb, sugar,
             logged_at_utc)
diet_expenditure(user_id FK, date, kcal, weight_kg nullable, source enum[estimate|manual])
             -- uniq(user,date)
```
- Изоляция по владельцу везде. Итоги дня пересчитываются на СЕРВЕРЕ из entries —
  клиентским суммам не доверяем. Времена UTC, «сегодня» — в поясе пользователя.

## 5. TDEE / формулы (features/diet/logic.py, чистые)

- BMR: Mifflin-St Jeor. TDEE = BMR × {sedentary 1.2, light 1.375, very 1.55}.
- daily_target = TDEE−500 (lose) / TDEE (maintain) / TDEE+300 (gain), не ниже BMR.
- protein_target = 1.8 г/кг (tunable). Валидация: age 10–120, height 100–250,
  weight 30–300 — и на клиенте, и на сервере.

## 6. Vorgang (инкременты) + Resultat (критерии приёмки)

### Инкремент 1 — MVP (core loop)  ← начинаем отсюда
Экраны: 01 Welcome · 02 Профиль×5 (+summary TDEE) · 03 Home (кольцо+макросы+
инсайт+навигация) · 04 Add-sheet · 07 Manual entry · 08 Amount (сегмент+сетка+
живой результат) · 10 Expenditure · 11 Diary (по приёмам, bulk-удаление).
Backend: `diet_profiles/foods(manual)/entries/expenditure`, логика TDEE,
`POST /api/diet/profile` (GET/PUT), `/api/diet/foods` (POST manual),
`/api/diet/entries` (GET по дате / POST / DELETE / bulk), `/api/diet/expenditure`
(PUT). Плюс строка «🍎 Калории» в меню + мост initData + монтаж `/webapp/diet/`.
**Готово когда:** онбординг создаёт профиль с целью; ручная еда → количество →
запись в дневник нужного приёма и даты; дашборд показывает съедено/осталось,
кольцо и макро-бары из реальных данных; расход сохраняется; удаление записи
(с подтверждением) работает; всё в 4 языках, light+dark; синтаксис PY+JS чист,
прогон vm-харнессом.
**Не входит:** избранное, статистика/графики, поиск по базе, штрихкод, Stars.

### Инкремент 2 — v2 (retention)
09 Favorites (лимит free, ⭐ безлимит) · 12 Statistics (Week/Month/Year, стат-карты,
графики: вес-линия, съедено-vs-сожжено бары, макро-донат — ⭐) · 13 Settings
(цель/таргеты/активность/единицы/язык/политика/удалить данные).
Backend: `/api/diet/favorites`, `/api/diet/stats?range=`, `/api/diet/account` (wipe).
**Открытый вопрос:** графики — свой SVG (как в дизайне), без библиотек.

### Инкремент 3 — v3 (wow)
05 Search по базе еды · 06 Barcode scan (⭐).
**Открытые вопросы (решить перед стартом v3):**
- Источник базы еды: OpenFoodFacts API (внешний, без ключа) vs своя сидированная
  таблица vs отложить. Влияет на приватность/логи/скорость.
- Штрихкод: камера в webview + декодер (напр. ZXing/QuaggaJS = НОВАЯ JS-зависимость,
  нужен разрешённый CDN или вендоринг) + lookup по штрихкоду (OpenFoodFacts).

### Инкремент 4 — v4 (монетизация)
14 Premium paywall + Telegram Stars.
**Открытые вопросы (решить перед стартом v4):**
- Реальные деньги: `sendInvoice`(XTR) / `openInvoice` + обработка
  `pre_checkout_query` и `successful_payment` в вебхуке; хранение статуса prime;
  цена (дизайн: 1200 Stars/год). Тестировать особенно тщательно.

## 7. Guardrails (из build-prompt §8)

- Все деструктивные действия — через подтверждение (диалог по центру).
- Итоги дня/дневника — только серверный пересчёт из entries.
- Валидация всех чисел на сервере (диапазоны §4).
- Prime-гейт на СЕРВЕРЕ (`_gate`/is_prime), не только в UI. Free-лимиты
  (напр. избранное ≤10) — тоже на сервере.
- Полный i18n ru/en/de/uk, включая empty/error/insight-тексты.
- Времена UTC, показ в поясе пользователя; «сегодня» — по поясу.
- initData HMAC-проверка на сервере (как в существующем `verify_init_data`).

## 8. Риски

- **Объём:** 14 экранов + новый бэкенд — многосессионно. Отсюда инкременты.
- **Внешние куски** (база еды, штрихкод, Stars) — каждый со своим решением и,
  возможно, ключами/зависимостями; отложены на v3/v4.
- **Neon CU-hrs:** дневник/дашборд читают БД при открытии — прячем кэшем
  (cache-first) как в остальных модулях; тяжёлого фонового опроса не добавляем.
- **Кэш Telegram:** свой `_WEBAPP_DIET_VER`, бампать при каждом изменении фронта.
