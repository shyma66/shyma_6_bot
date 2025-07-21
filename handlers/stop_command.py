# Command /stop
from telegram import Update
from telegram.ext import ContextTypes
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    print(f"/stop and logs deleted {user.id}, {user.name}")

    # clear user_data
    context.user_data.clear()

    # Delete the user log file
    # filename = f"user_{user_id}.txt"
    # folder = "user_logs"
    # filepath = os.path.join(folder, filename)
    #
    # if os.path.exists(filepath):
    #     os.remove(filepath)
    # await update.message.reply_text(f"Bye {update.message.from_user.first_name}!")