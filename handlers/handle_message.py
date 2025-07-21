# message from user
from telegram import Update
import os
async def handle_message(update: Update, context):
    user = update.effective_user
    user_id = user.id
    text = update.message.text
    print(f"message from: {user.id}, {user.name} ")
    # Path to user file (eg: user_12345678.txt)
    filename = f"user_{user_id}.txt"
    folder = "user_logs"
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)

    # Save the message to a file
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(text + "\n")
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
