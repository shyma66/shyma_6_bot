from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from dotenv import load_dotenv, find_dotenv
from telegram import Update
from fastapi import FastAPI, HTTPException, Request
from contextlib import asynccontextmanager
import os
import traceback
#import from handlers
from handlers.start_command import start
from handlers.stop_command import stop
from handlers.handle_message import handle_message
from handlers.support_command import support
from DataBase.database import init_db
from core.dashboard import register_core
from features.shelves.handlers import setup as setup_shelves
from features.reminders.handlers import setup as setup_reminders
from features.reminders.tick import process_due
from features.calendar.handlers import setup as setup_calendar
from features.calendar.tick import process_calendar
from features.grades.handlers import setup as setup_grades
# from handlers.calendar_command import calendar, calendar_callback, save_time
# Token Bot from .env
load_dotenv(find_dotenv())
BOT_TOKEN = os.getenv("BOT_TOKEN")
TICK_SECRET = os.getenv("TICK_SECRET")  # секрет для эндпоинта /tick (внешний cron)
WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_URL = os.getenv("WEBHOOK_URL") + WEBHOOK_PATH
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
import core.modules  # noqa: F401,E402 — core-модули (🌐 Язык — последним в меню)


async def on_error(update, context) -> None:
    """Глобальный обработчик ошибок: полный traceback в лог Render + короткое
    сообщение в чат (вместо «мёртвой кнопки» пользователь видит текст ошибки)."""
    err = context.error
    print("[error] Exception while handling update:")
    traceback.print_exception(type(err), err, err.__traceback__)
    try:
        if update is not None and getattr(update, "effective_chat", None):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⚠️ Internal error: {err!r}"[:400],
            )
    except Exception:  # noqa: BLE001 — уведомление не должно ронять error handler
        pass


bot_app.add_error_handler(on_error)
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
    await bot_app.initialize()
    await bot_app.bot.set_webhook(url=WEBHOOK_URL)
    yield #additicion for bot stopping
    await bot_app.shutdown()
app = FastAPI(lifespan=lifespan)
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


@app.post("/tick")
async def tick(request: Request):
    """Внешний cron дёргает раз в N минут -> рассылаем созревшие напоминания.

    Защищено секретом: заголовок X-Tick-Key должен совпасть с TICK_SECRET.
    """
    if not TICK_SECRET:
        return {"ok": False, "error": "tick disabled (no TICK_SECRET)"}
    if request.headers.get("X-Tick-Key") != TICK_SECRET:
        raise HTTPException(status_code=403, detail="forbidden")
    sent = await process_due(bot_app.bot)
    cal = await process_calendar(bot_app.bot)  # синк ICS-фидов + напоминания о событиях
    return {"ok": True, "sent": sent, **cal}