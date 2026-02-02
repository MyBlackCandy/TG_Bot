import os
import re
import sys
import logging
import psycopg2
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ตั้งค่า Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- ดึงค่าจาก Variables ของ Railway ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

if not TOKEN or not DATABASE_URL:
    print("❌ ERROR: TOKEN หรือ DATABASE_URL หายไปจากหน้า Variables")
    sys.exit(1)

# --- ส่วนจัดการฐานข้อมูล PostgreSQL ---
def get_db_connection():
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
        print("✅ Database initialized")
    except Exception as e:
        print(f"❌ Database error: {e}")

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
    await update.message.reply_text('✅ 输入+ 数字 后者 - 数字\n/reset 去除所有数据')

async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.message.from_user.id

    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        operator, value = match.group(1), int(match.group(2))
        amount = value if operator == '+' else -value

        save_transaction(user_id, amount)
        history = get_history(user_id)
        
        total = sum(history)
        count = len(history)
        
        response = "📋 AK机器人:记录\n"
        
        # จัดการการย่อรายการ (แสดงแค่ 10 อันล่าสุด)
        if count > 10:
            response += "...\n"
            display_items = history[-10:]  # เอา 10 ตัวสุดท้าย
            start_num = count - 9        # คำนวณเลขลำดับเริ่มต้น
        else:
            display_items = history
            start_num = 1

        for i, val in enumerate(display_items, start_num):
            symbol = "+" if val > 0 else ""
            response += f"{i}. {symbol}{val}\n"
        
        response += f"----------------\n"
        response += f"📊 全部: {count} 项目\n"
        response += f"💰 总金额: {total}"
        
        await update.message.reply_text(response)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.message.from_user.id)
    await update.message.reply_text("🧹 已清理数据!")

# --- รันโปรแกรม ---
if __name__ == '__main__':
    init_db()
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    application.run_polling()
