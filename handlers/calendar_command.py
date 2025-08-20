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
            f"Choose {LSTEP[step]}:",
            reply_markup=key
        )
    elif result:
        # Date is chosen, now wait for time input
        context.user_data["reminder_date"] = result
        await query.edit_message_text(f"Date chosen: {result.strftime('%d.%m.%Y')}\nPlease enter time in HH:MM format:")

async def save_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if "reminder_date" not in context.user_data:
        return

    text = update.message.text.strip()

    try:
        reminder_time = datetime.datetime.strptime(text, "%H:%M").time()
    except ValueError:
        await update.message.reply_text("❌ Invalid format. Please use HH:MM")
        return

    reminder_date: datetime.date = context.user_data["reminder_date"]
    reminder_datetime = datetime.datetime.combine(reminder_date, reminder_time)

    # Load existing reminders
    with open(reminders_file, "r") as f:
        reminders = json.load(f)

    # Add reminder for this user
    if str(user_id) not in reminders:
        reminders[str(user_id)] = []
    reminders[str(user_id)].append(reminder_datetime.isoformat())

    # Save back to file
    with open(reminders_file, "w") as f:
        json.dump(reminders, f, indent=2)

    # Clear temporary state
    context.user_data.pop("reminder_date")

    await update.message.reply_text(
        f"✅ Reminder set for {reminder_datetime.strftime('%d.%m.%Y %H:%M')}"
    )