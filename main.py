import os
import re
import sys
import logging
import psycopg2
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ตั้งค่า Logging เพื่อดู Error ในหน้า Railway Log
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- ดึงค่าจาก Variables ของ Railway ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

# ตรวจสอบว่าตั้งค่า Variables ครบหรือไม่
if not TOKEN:
    print("❌ ERROR: ไม่พบตัวแปร TOKEN ในหน้า Variables ของ Railway")
    sys.exit(1)

if not DATABASE_URL:
    print("❌ ERROR: ไม่พบตัวแปร DATABASE_URL ในหน้า Variables ของ Railway")
    sys.exit(1)

# --- ส่วนจัดการฐานข้อมูล PostgreSQL ---
def get_db_connection():
    # ปรับแต่ง URL ให้รองรับรูปแบบของ psycopg2
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    
    return psycopg2.connect(url, sslmode='require')

def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                amount INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Database initialized successfully")
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")

def save_transaction(user_id, amount):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO history (user_id, amount) VALUES (%s, %s)', (user_id, amount))
    conn.commit()
    cursor.close()
    conn.close()

def get_history(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT amount FROM history WHERE user_id = %s ORDER BY timestamp ASC', (user_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [row[0] for row in rows]

def clear_history(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE user_id = %s', (user_id,))
    conn.commit()
    cursor.close()
    conn.close()

# --- ส่วนการทำงานของบอท ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '✅ บอทคำนวณพร้อมใช้งาน!\n\n'
        '• พิมพ์ +เลข หรือ -เลข (เช่น +500 หรือ -200)\n'
        '• พิมพ์ /reset เพื่อเริ่มนับใหม่'
    )

async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.message.from_user.id

    # ตรวจจับรูปแบบ +### หรือ -###
    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        operator = match.group(1)
        value = int(match.group(2))
        amount = value if operator == '+' else -value

        save_transaction(user_id, amount)
        history = get_history(user_id)
        
        response = "📋 รายการบันทึกของคุณ:\n"
        for i, val in enumerate(history, 1):
            symbol = "+" if val > 0 else ""
            response += f"{i}. {symbol}{val}\n"
        
        total = sum(history)
        response += f"----------------\n💰 ยอดรวมสุทธิ: {total}"
        await update.message.reply_text(response)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.message.from_user.id)
    await update.message.reply_text("🧹 ล้างข้อมูลประวัติของคุณเรียบร้อยแล้ว!")

# --- ส่วนรันโปรแกรม ---
if __name__ == '__main__':
    init_db()
    
    # สร้าง Application
    application = Application.builder().token(TOKEN).build()
    
    # เพิ่ม Handler
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    
    print("🚀 Bot is running...")
    application.run_polling()
