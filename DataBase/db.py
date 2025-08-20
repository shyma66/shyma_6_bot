import aiosqlite

DB_PATH = "reminders.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                reminder_time TEXT
            )
        """)
        await db.commit()

async def add_reminder(user_id: int, reminder_time: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO reminders (user_id, reminder_time) VALUES (?, ?)", (user_id, reminder_time))
        await db.commit()

async def get_user_reminders(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT reminder_time FROM reminders WHERE user_id = ?", (user_id,))
        rows = await cursor.fetchall()
        return [row[0] for row in rows]