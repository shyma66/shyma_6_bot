#/start command
from telegram import Update
from telegram.ext import ContextTypes
from DataBase.database import get_or_create_user
from core.dashboard import build_dashboard_markup
from core.i18n import t, user_lang
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    print(f"/start {user_id}, {user.name}")
    await get_or_create_user(user_id, user.username)
    lang = await user_lang(update, context)
    context.application.bot_data[user_id] = True
    await update.message.reply_text(
        f"{t(lang, 'start.greeting', name=user.first_name)}\n\n{t(lang, 'menu.title')}",
        reply_markup=build_dashboard_markup(lang, uid=user_id),
    )
