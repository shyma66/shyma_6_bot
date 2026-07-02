# message from user
from telegram import Update
from telegram.ext import ContextTypes
from dotenv import load_dotenv
import os

from core.i18n import t, user_lang

load_dotenv()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    is_active = context.application.bot_data.get(user_id, True)
    if not is_active:
        return
    user_message = update.message.text
    print(f"message from: {user_id}, {user.name} , message: {user_message} ")
    # Path to user file (eg: user_12345678.txt)
    filename = f"user_{user_id}.txt"
    folder = "user_logs"
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    # Save the message to a file
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(user_message + "\n")

    lang = await user_lang(update, context)
    await update.message.reply_text(t(lang, "msg.received"))









