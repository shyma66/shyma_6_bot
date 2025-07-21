from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext
from dotenv import load_dotenv
import os
import requests

# Token Bot from .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

# Command /start
async def start(update: Update, context):
    await update.message.reply_text(f"Hi {update.message.from_user.first_name}, I am your bot!")
    await update.message.reply_text("Text me the city and I'll send you the current weather 🌦️")

# Command /stop
async def stop(update: Update, context):
    await update.message.reply_text(f"Bye {update.message.from_user.first_name}!")

# Get weather
def get_weather(city: str):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=en"
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        temp = data["main"]["temp"]
        desc = data["weather"][0]["description"]
        humidity = data["main"]["humidity"]
        wind = data["wind"]["speed"]
        return f"🌍 Weather in {city}:\n🌡 Temp: {temp}°C\n🌥 {desc}\n💧 humidity: {humidity}%\n💨 Wind: {wind} m/s"
    else:
        return "❌ Unable to find weather for this city. Check the name"

# Command /get_weather
async def handle_city(update: Update, context):
    city = update.message.text.strip()
    weather = get_weather(city)
    await update.message.reply_text(weather)


# Starting bot
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_city))

    print("Weather Bot started...")

    app.run_polling()
