import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder ,CommandHandler , MessageHandler, filters, ContextTypes
import asyncio
import json
import logging
import re

# 🔑 Вставь свой токен от BotFather
BOT_TOKEN = '7747997349:AAH38imZerb0y3ylJMHbQtr3ngaIE7BFYhw'
PRODUCTS_FILE = "products.json"
CHECK_INTERVAL = 4 * 60 * 60

def load_products():
    try:
        with open(PRODUCTS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_products(data):
    with open(PRODUCTS_FILE, "w") as f:
        json.dump(data, f)

async def start(update, context):
    await update.message.reply_text("Hi, I am your bot!")

async def stop(update, context):
    user_id = str(update.effective_chat.id)
    data = load_products()
    if user_id in data:
        del data[user_id]
        save_products(data)
        await update.message.reply_text("Monitoring has been stopped")
    else:
        await update.message.reply_text("You don't track anything. See you!")



# Функция парсинга цены
def get_price(product_name):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9"
    }

    search_url = f"https://www.amazon.com/s?k={product_name.replace(' ', '+')}"
    response = requests.get(search_url, headers=headers)

    soup = BeautifulSoup(response.text, "lxml")

    # Ищем блоки с товарами
    product = soup.find("div", {"data-component-type": "s-search-result"})
    if not product:
        return "❌ Product not found"

    price_whole = product.find("span", class_="a-price-whole")
    price_fraction = product.find("span", class_="a-price-fraction")

    if price_whole and price_fraction:
        return f"{price_whole.text.strip()}.{price_fraction.text.strip()} USD"
    elif price_whole:
        return f"{price_whole.text.strip()} USD"
    else:
        return "❌ Price not found"

def is_url(text):
    return re.match(r'https?://', text)


# Обработчик сообщений
async def add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    product_text = update.message.text.strip()

    data = load_products()
    data[user_id] = product_text
    save_products(data)

    await update.message.reply_text(f"I'll track: {product_text}")

    # Проверяем: ссылка или просто название
    if is_url(product_text):
        await update.message.reply_text("Links are not supported yet, just the product name.")
        return

    price = get_price(product_text)
    await update.message.reply_text(f"Current price: {price}")

async def monitor_prices(app):
    while True:
        data = load_products()
        for user_id, product_name in data.items():
            try:
                price = get_price(product_name)
                await app.bot.send_message(chat_id=int(user_id), text=f"⏰ Price update for '{product_name}': {price}")
            except Exception as e:
                logging.warning(f"Error sending {user_id}: {e}")
        await asyncio.sleep(CHECK_INTERVAL)




# Запуск бота

async def on_startup(app):
    app.create_task(monitor_prices(app))

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_product))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))

    print("✅ Bot started")

    await app.run_polling()

if __name__ == '__main__':
    import nest_asyncio

    nest_asyncio.apply()

    asyncio.get_event_loop().run_until_complete(main())

