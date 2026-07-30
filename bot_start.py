from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from dotenv import load_dotenv, find_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, MenuButtonWebApp
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import asyncio
import os
import traceback
#import from handlers
from handlers.start_command import start
from handlers.stop_command import stop
from handlers.handle_message import handle_message
from handlers.support_command import support
from DataBase.database import init_db
from core import admin
from core.i18n import t, user_lang
from core.dashboard import register_core
from features.admin.handlers import setup as setup_admin
from features.shelves.handlers import setup as setup_shelves
from features.reminders.handlers import setup as setup_reminders
from features.reminders.tick import process_due
from features.calendar.handlers import setup as setup_calendar
from features.calendar.tick import process_calendar
from features.grades.handlers import setup as setup_grades
from features.settings.handlers import setup as setup_settings
from features.backup.service import run_periodic
from webapp.api import router as webapp_router
# from handlers.calendar_command import calendar, calendar_callback, save_time
# Token Bot from .env
load_dotenv(find_dotenv())
BOT_TOKEN = os.getenv("BOT_TOKEN")
TICK_SECRET = os.getenv("TICK_SECRET")  # секрет для эндпоинта /tick (внешний cron)
WEBHOOK_PATH = f"/{BOT_TOKEN}"
_WEBHOOK_BASE = os.getenv("WEBHOOK_URL") or ""
WEBHOOK_URL = _WEBHOOK_BASE + WEBHOOK_PATH
# URL Mini App «Напоминания» (раздаётся этим же сервисом на /webapp/reminders/).
# ?v=... бампаем при изменении фронта, чтобы Telegram сбросил кэш Mini App.
_WEBAPP_VER = "10"
WEBAPP_URL = (_WEBHOOK_BASE + "/webapp/reminders/?v=" + _WEBAPP_VER) if _WEBHOOK_BASE.startswith("https") else ""
if not BOT_TOKEN:
    raise ValueError("TELEGRAM_TOKEN not found in .env file")


# Starting bot
# if __name__ == '__main__':
bot_app = ApplicationBuilder().token(BOT_TOKEN).build()
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("stop", stop))
bot_app.add_handler(CommandHandler("support", support))
register_core(bot_app)  # callback-роутер дашборда (кнопки модулей)
setup_shelves(bot_app)  # модуль «Шкаф» (регистрирует кнопку + handlers)
setup_reminders(bot_app)  # модуль «Напоминания» (кнопка + handlers)
setup_calendar(bot_app)  # модуль «Календарь» (ICS-фид -> напоминания о событиях)
setup_grades(bot_app)  # модуль «Оценки» (Notenrechner: SA/KA/Mündlich, баллы 0–15)
setup_admin(bot_app)  # ⚙️ Админ-панель (только ADMIN_ID: вкл/выкл модулей + журнал ошибок)
setup_settings(bot_app)  # ⚙️ Настройки (согласие Datenschutz, язык, политика, удалить данные)
import core.modules  # noqa: F401,E402 — core-модули (🌐 Язык — последним в меню)


def _err_where(update) -> str:
    """Короткая метка места ошибки для журнала: модуль/действие, без данных юзера."""
    if update is None:
        return "background"
    q = getattr(update, "callback_query", None)
    if q is not None and getattr(q, "data", None):
        return f"callback {q.data}"
    msg = getattr(update, "effective_message", None)
    if msg is not None and getattr(msg, "text", None) and msg.text.startswith("/"):
        return f"command {msg.text.split()[0]}"
    return "message"


async def on_error(update, context) -> None:
    """Глобальный обработчик ошибок.

    Полный traceback — в лог Render. Обычный юзер видит нейтральные «техработы»
    (внутренние детали провайдера ему ничего не говорят и не должны утекать).
    Админ получает настоящий текст ошибки в личку (с антифлудом) и видит журнал
    в админ-панели.
    """
    err = context.error
    print("[error] Exception while handling update:")
    traceback.print_exception(type(err), err, err.__traceback__)

    rec = admin.record_error(_err_where(update), err)

    # Уведомление админа в личку — если ADMIN_ID задан и это не он сам споткнулся
    # (админу ответят в его же чате ниже настоящим текстом).
    admin_id = admin.ADMIN_ID
    user = getattr(update, "effective_user", None) if update is not None else None
    is_admin_user = user is not None and admin.is_admin(user.id)
    if admin_id is not None and not is_admin_user and admin.should_notify(rec):
        try:
            await context.bot.send_message(
                chat_id=admin_id, text=f"⚠️ {rec.where}\n{rec.text}"[:1000]
            )
        except Exception:  # noqa: BLE001
            pass

    chat = getattr(update, "effective_chat", None) if update is not None else None
    if chat is None:
        return
    try:
        lang = await user_lang(update, None)
    except Exception:  # noqa: BLE001 — язык не критичен, падать в error handler нельзя
        lang = "en"
    text = f"⚠️ {rec.text}"[:400] if is_admin_user else t(lang, "err.maintenance")
    try:
        await context.bot.send_message(chat_id=chat.id, text=text)
    except Exception:  # noqa: BLE001 — уведомление не должно ронять error handler
        pass


bot_app.add_error_handler(on_error)


async def app_command(update, context) -> None:
    """/app — кнопка запуска Mini App «Напоминания»."""
    lang = await user_lang(update, None)
    if not WEBAPP_URL:
        await update.message.reply_text("Mini App не настроен (нет WEBHOOK_URL).")
        return
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton(t(lang, "menu.open_app"), web_app=WebAppInfo(url=WEBAPP_URL))]]
    )
    await update.message.reply_text(t(lang, "menu.title"), reply_markup=kb)


bot_app.add_handler(CommandHandler("app", app_command))
# bot_app.add_handler(CommandHandler("calendar", calendar))
# bot_app.add_handler(CallbackQueryHandler(calendar_callback))
# bot_app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message, save_time))
# bot_app.add_handler(CallbackQueryHandler(calendar_callback))
print("Data Bot started...")


# Build FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Недоступная БД (исчерпанная квота Neon, таймаут, сеть) не должна ронять весь
    # сервис: без этого старт падал с «Application startup failed. Exiting.» и бот
    # не отвечал вообще. Так же мягко, как случай «DATABASE_URL не задан».
    try:
        await init_db()
    except Exception as e:  # noqa: BLE001 — старт важнее, детали уйдут в лог
        print(f"[DB] init_db failed: {e!r} — стартую без БД, функции с БД будут падать точечно.")
    await admin.load_flags()  # выключенные модули из БД в кэш (сам обрабатывает сбой БД)
    await bot_app.initialize()
    await bot_app.bot.set_webhook(url=WEBHOOK_URL)
    if WEBAPP_URL:  # кнопка меню открывает Mini App «Напоминания»
        try:
            await bot_app.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="App", web_app=WebAppInfo(url=WEBAPP_URL))
            )
        except Exception as e:  # noqa: BLE001
            print(f"[webapp] set_chat_menu_button failed: {e!r}")
    yield #additicion for bot stopping
    await bot_app.shutdown()
app = FastAPI(lifespan=lifespan)
app.include_router(webapp_router)  # /api/... для Mini App «Напоминания»
app.mount("/webapp/reminders", StaticFiles(directory="webapp/reminders", html=True), name="webapp")
@app.get("/")
def root():
    return {"status": "OK"}

@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
    except Exception as e:
        print(f"[Webhook ERROR] {e}")
    return {"ok": True}


_tick_busy = False  # защита от наложения: пока прошлый /tick работает, новый не запускаем
_tick_tasks: set = set()  # держим ссылки на фоновые задачи, иначе их соберёт GC


async def _run_tick() -> None:
    """Тяжёлая работа /tick в фоне: рассылка напоминаний + синк календаря + бэкап.

    Вынесено из HTTP-обработчика, чтобы эндпоинт отвечал мгновенно и внешний cron
    не отваливался по таймауту (медленный ICS-фид/пачка напоминаний могли занять
    >30 с и cron-job.org отключал джоб за серию неудач)."""
    global _tick_busy
    if _tick_busy:
        print("[tick] предыдущий запуск ещё выполняется — пропускаю")
        return
    _tick_busy = True
    try:
        sent = await process_due(bot_app.bot)
        cal = await process_calendar(bot_app.bot)
        backup = await run_periodic()
        print(f"[tick] готово: sent={sent} {cal} {backup}")
    except Exception as e:  # noqa: BLE001
        print(f"[tick ERROR] {e!r}")
    finally:
        _tick_busy = False


@app.post("/tick")
async def tick(request: Request):
    """Внешний cron дёргает раз в N минут. Отвечаем 200 СРАЗУ, работу делаем в фоне.

    Защищено секретом: заголовок X-Tick-Key должен совпасть с TICK_SECRET.
    """
    if not TICK_SECRET:
        return {"ok": False, "error": "tick disabled (no TICK_SECRET)"}
    if request.headers.get("X-Tick-Key") != TICK_SECRET:
        raise HTTPException(status_code=403, detail="forbidden")
    task = asyncio.create_task(_run_tick())  # fire-and-forget: cron не ждёт завершения
    _tick_tasks.add(task)
    task.add_done_callback(_tick_tasks.discard)
    return {"ok": True, "started": True}