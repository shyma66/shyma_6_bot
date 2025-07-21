#/start command
from telegram import Update
from telegram.ext import ContextTypes
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    print(f"/start {user.id}, {user.name}")
    await update.message.reply_text(f"Hi {update.message.from_user.first_name}, I am your bot!")