from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram_bot_calendar import DetailedTelegramCalendar, LSTEP
import datetime
import json
import os

calendar = DetailedTelegramCalendar()
reminders_file = "reminders.json"

user_steps = {}

if not os.path.exists(reminders_file):
    with open(reminders_file, "w") as f:
        json.dump({}, f)
async def calendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    calendar_markup, step = DetailedTelegramCalendar(
        min_date=datetime.date.today()
    ).build()

    await update.message.reply_text(
        f"Выберите {LSTEP[step]}:",
        reply_markup=calendar_markup
    )


async def calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    result, key, step = DetailedTelegramCalendar(min_date=datetime.date.today()).process(query.data)

    if not result and key:
        user_steps[user_id]["step"] = step
        await query.edit_message_text(
            f"Выберите {LSTEP[step]}:",
            reply_markup=key
        )
    elif result:
        # Когда дата выбрана, просим ввести время
        context.user_data["reminder_date"] = result
        await query.edit_message_text(f"Дата выбрана: {result.strftime('%d.%m.%Y')}\nВведите время в формате ЧЧ:ММ:")