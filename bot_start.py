from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv, find_dotenv
import os

#import from handlers
from handlers.start_command import start
from handlers.stop_command import stop
from handlers.handle_message import handle_message

# Token Bot from .env
load_dotenv(find_dotenv())
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Starting bot
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Data Bot started...")

    app.run_polling()
