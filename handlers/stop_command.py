# Command /stop
from telegram import Update
import os
from core.i18n import t, user_lang
async def stop(update: Update, context):
    user = update.effective_user
    user_id = user.id
    print(f"/stop and logs deleted {user_id}, {user.name}")
    lang = await user_lang(update, context)
    # clear user_data
    context.user_data.clear()
    # user press stop therefore inactive
    context.application.bot_data[user_id] = False

    #Delete the user log file
    filename = f"user_{user_id}.txt"
    folder = "user_logs"
    filepath = os.path.join(folder, filename)

    if os.path.exists(filepath):
        os.remove(filepath)
    await update.message.reply_text(t(lang, "stop.bye", name=update.message.from_user.first_name))
