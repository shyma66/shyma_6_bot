import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import asyncio


# 🔑 Вставь свой токен от BotFather
BOT_TOKEN = '7747997349:AAH38imZerb0y3ylJMHbQtr3ngaIE7BFYhw'

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
        return "❗ Цена не найдена. Возможно, страница изменилась или товар недоступен."
    except Exception as e:
        return f"⚠️ Ошибка при получении цены: {e}"


# Обработчик сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if "amazon." not in url:
        await update.message.reply_text("Пожалуйста, отправь ссылку на товар с Amazon.")
        return

    await update.message.reply_text("🔍 Проверяю цену...")

    price = get_amazon_price(url)
    await update.message.reply_text(f"💰 Цена: {price}")


# Запуск бота
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Бот запущен.")
    app.run_polling()
