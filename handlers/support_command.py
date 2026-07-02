#support command
from telegram.ext import ContextTypes
from telegram import Update
from core.i18n import t, user_lang
async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    is_active = context.application.bot_data.get(user_id, True)
    if not is_active:
        return
    print(f"/support {user_id}, {user.name}")
    lang = await user_lang(update, context)
    await update.message.reply_text(
        t(lang, "support.text", name=update.message.from_user.first_name)
    )
