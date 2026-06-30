#/start command
from telegram import Update
from telegram.ext import ContextTypes
from DataBase.database import get_or_create_user
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    print(f"/start {user_id}, {user.name}")
    await get_or_create_user(user_id, user.username)
    context.application.bot_data[user_id] = True
    await update.message.reply_text(f"Hi {update.message.from_user.first_name}, I am ShymaBot!")