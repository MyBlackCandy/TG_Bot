import os
import re
import sys
import logging
import psycopg2
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ตั้งค่า Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

if not TOKEN or not DATABASE_URL:
    print("❌ ERROR: TOKEN or DATABASE_URL is missing")
    sys.exit(1)

def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # สร้างตารางใหม่ที่มีคอลัมน์ครบถ้วน (chat_id และ user_name)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT,
                amount INTEGER,
                user_name TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Database Ready")
    except Exception as e:
        print(f"❌ DB Error: {e}")

async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    user_name = update.message.from_user.first_name

    # ตรวจจับ + หรือ - ตามด้วยตัวเลข
    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        val = int(match.group(2))
        amount = val if match.group(1) == '+' else -val

        # บันทึกลงฐานข้อมูล
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', (chat_id, amount, user_name))
        conn.commit()
        
        # ดึงประวัติมาแสดง
        cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
        rows = cursor.fetchall(); cursor.close(); conn.close()
        
        total = sum(r[0] for r in rows)
        count = len(rows)
        res = "📋 AK机器人:记录\n"
        
        display = rows[-10:] if count > 10 else rows
        if count > 10: res += "...\n"
        for i, (v, name) in enumerate(display, (count-9 if count > 10 else 1)):
            res += f"{i}. {'+' if v > 0 else ''}{v} ({name})\n"
        
        res += f"----------------\n📊 全部: {count}\n💰 总金额: {total}"
        await update.message.reply_text(res)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE chat_id = %s', (chat_id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("🧹 已清理数据!")

if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    app.run_polling()
