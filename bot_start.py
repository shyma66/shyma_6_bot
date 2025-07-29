from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from dotenv import load_dotenv, find_dotenv
from telegram import Update
from fastapi import FastAPI, Request
import os
#import from handlers
from handlers.start_command import start
from handlers.stop_command import stop
from handlers.handle_message import handle_message
from handlers.support_command import support
# Token Bot from .env
load_dotenv(find_dotenv())
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_URL = os.getenv("WEBHOOK_URL") + WEBHOOK_PATH
if not BOT_TOKEN:
    raise ValueError("TELEGRAM_TOKEN not found in .env file")
# Starting bot
if __name__ == '__main__':
    app = FastAPI()
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("stop", stop))
    bot_app.add_handler(CommandHandler("support", support))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Data Bot started...")

    @app.get("/")
    def root():
        return {"status": "OK"}

    @app.post(WEBHOOK_PATH)
    async def webhook(request: Request):
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
        return {"ok": True}

    @app.on_event("startup")
    async def startup():
        await bot_app.bot.set_webhook(url=WEBHOOK_URL)
