from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from dotenv import load_dotenv, find_dotenv
from telegram import Update
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
import os
#import from handlers
from handlers.start_command import start
from handlers.stop_command import stop
from handlers.handle_message import handle_message
from handlers.support_command import support
from handlers.calendar_command import calendar, calendar_callback, save_time
# Token Bot from .env
load_dotenv(find_dotenv())
BOT_TOKEN = os.getenv("BOT_TOKEN")
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
bot_app.add_handler(CommandHandler("calendar", calendar))
bot_app.add_handler(CallbackQueryHandler(calendar_callback))
bot_app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message, save_time))
bot_app.add_handler(CallbackQueryHandler(calendar_callback))
print("Data Bot started...")

# Build FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs when the application starts
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