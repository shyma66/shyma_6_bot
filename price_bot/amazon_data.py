import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
import os
import aiogram
from urllib.parse import quote_plus

# Token Bot from .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
# Заголовки для запроса к Amazon
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
}


# Функция парсинга цены
def get_amazon_price(url: str) -> str:
    try:
        response = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(response.content, 'lxml')

        # Возможные ID с ценами
        price = (
                soup.find(id="priceblock_ourprice")
                or soup.find(id="priceblock_dealprice")
                or soup.find("span", {"class": "a-offscreen"})
        )

        if price:
            return price.text.strip()
        return "❗ Price not found. The page may have changed or the product may not be available"
    except Exception as e:
        return f"⚠️ Error getting price: {e}"


# Обработчик сообщений
async def handle_message(update: Update, context):
    url = update.message.text.strip()

    if "amazon." not in url:
        await update.message.reply_text("Please send a link to the product from Amazon")
        return

    await update.message.reply_text("🔍 Checking the price...")

    price = get_amazon_price(url)
    await update.message.reply_text(f"💰 Price: {price}")

async def handle_message(update: Update, context):
    user_query = update.message.text
    encoded_query = quote_plus(user_query)
    amazon_url = f"https://www.amazon.de/s?k={encoded_query}"
    await update.message.reply_text(f"🔎 Вот ссылка на Amazon.de:\n{amazon_url}")




if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Amazon data bot started.")
    app.run_polling()