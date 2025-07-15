from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
import requests
import os
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

user_state = {}

main_keyboard = ReplyKeyboardMarkup([["🌦 Погода", "🛒 Amazon"]], resize_keyboard=True)
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
}
# Token Bot from .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

def get_amazon_price(search_url: str) -> str:
    try:
        response = requests.get(search_url, headers=HEADERS)
        soup = BeautifulSoup(response.text, "lxml")
        price_tag = soup.find("span", class_="a-price-whole")
        if price_tag:
            return price_tag.text.strip() + " €"
        return "❌ Цена не найдена"
    except Exception as e:
        return f"⚠️ Ошибка: {e}"


# --- Получить погоду через OpenWeather ---
def get_weather(city: str) -> str:
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
        res = requests.get(url)
        data = res.json()
        if res.status_code == 200:
            temp = data["main"]["temp"]
            desc = data["weather"][0]["description"]
            return f"🌤 В городе {city} сейчас {temp}°C, {desc}"
        return "❗ Город не найден"
    except Exception as e:
        return f"⚠️ Ошибка: {e}"



# Command /start
async def start(update: Update, context):
    await update.message.reply_text(f"Hi {update.message.from_user.first_name}, I am your bot!")

# Command /stop
async def stop(update: Update, context):
    await update.message.reply_text(f"Bye {update.message.from_user.first_name}!")

async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    text = update.message.text.strip()

    if text == "🌦 Погода":
        user_state[user_id] = "weather"
        await update.message.reply_text("✍️ Введи название города:")
    elif text == "🛒 Amazon":
        user_state[user_id] = "amazon"
        await update.message.reply_text("🔍 Введи название товара:")
    else:
        await handle_text_query(update, context)

async def handle_text_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    text = update.message.text.strip()
    state = user_state.get(user_id)

    if state == "weather":
        weather = get_weather(text)
        await update.message.reply_text(weather)
        user_state.pop(user_id, None)

    elif state == "amazon":
        encoded = quote_plus(text)
        url = f"https://www.amazon.de/s?k={encoded}"
        price = get_amazon_price(url)
        await update.message.reply_text(f"🔗 Ссылка: {url}\n💰 Цена: {price}")
        user_state.pop(user_id, None)

    else:
        await update.message.reply_text("Пожалуйста, выбери сначала опцию: 🌦 Погода или 🛒 Amazon", reply_markup=main_keyboard)


# Starting bot
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))

    print("Data2.0 Bot started...")

    app.run_polling()
