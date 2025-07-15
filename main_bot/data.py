from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv
import os

# Token Bot from .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Command /start
async def start(update: Update, context):
    await update.message.reply_text(f"Hi {update.message.from_user.first_name}, I am your bot!")

# Command /stop
async def stop(update: Update, context):
    await update.message.reply_text(f"Bye {update.message.from_user.first_name}!")

# Starting bot
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))

    print("Data Bot started...")

    app.run_polling()
