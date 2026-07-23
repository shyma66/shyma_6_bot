#/start command
from telegram import Update
from telegram.ext import ContextTypes
from DataBase.database import get_or_create_user
from core.dashboard import build_dashboard_markup
from core.i18n import t, user_lang
from features.settings.handlers import is_consented, show_consent
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    print(f"/start {user_id}, {user.name}")
    await get_or_create_user(user_id, user.username)
    context.application.bot_data[user_id] = True
    # жёсткое согласие: без него меню не показываем
    if not await is_consented(update, context):
        await show_consent(update, context)
        return
    lang = await user_lang(update, context)
    await update.message.reply_text(
        f"{t(lang, 'start.greeting', name=user.first_name)}\n\n{t(lang, 'menu.title')}",
        reply_markup=build_dashboard_markup(lang, uid=user_id),
    )
