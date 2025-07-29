#support command
from telegram.ext import ContextTypes
from telegram import Update
async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    is_active = context.application.bot_data.get(user_id, True)
    if not is_active:
        return
    print(f"/support {user_id}, {user.name}")
    await update.message.reply_text(f"Dear {update.message.from_user.first_name} contact please with our support: @shyma_6")