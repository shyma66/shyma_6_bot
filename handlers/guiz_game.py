import random
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes


# Datenbank initialisieren
def init_db():
    conn = sqlite3.connect('vocabulary.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS words
                 (id INTEGER PRIMARY KEY, english TEXT, german TEXT)''')
    conn.commit()
    conn.close()


# Vokabeln zur Datenbank hinzufügen
def add_word(english, german):
    conn = sqlite3.connect('vocabulary.db')
    c = conn.cursor()
    c.execute("INSERT INTO words (english, german) VALUES (?, ?)", (english, german))
    conn.commit()
    conn.close()


# Zufällige Vokabel mit falschen Antworten holen
def get_quiz_question():
    conn = sqlite3.connect('vocabulary.db')
    c = conn.cursor()

    # Richtige Antwort holen
    c.execute("SELECT english, german FROM words ORDER BY RANDOM() LIMIT 1")
    correct_answer = c.fetchone()

    # 3 falsche Antworten holen
    c.execute("SELECT german FROM words WHERE german != ? ORDER BY RANDOM() LIMIT 3", (correct_answer[1],))
    wrong_answers = [row[0] for row in c.fetchall()]

    conn.close()

    # Antworten mischen
    all_answers = wrong_answers + [correct_answer[1]]
    random.shuffle(all_answers)

    return {
        'question': f"Was bedeutet '{correct_answer[0]}'?",
        'correct_answer': correct_answer[1],
        'answers': all_answers
    }