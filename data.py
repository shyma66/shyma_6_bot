from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Твой токен, полученный от BotFather
BOT_TOKEN = '7747997349:AAH38imZerb0y3ylJMHbQtr3ngaIE7BFYhw'

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я твой бот!")

# Запуск бота
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    print("Бот запущен...")
    app.run_polling()
