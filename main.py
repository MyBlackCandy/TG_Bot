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
    print("❌ ERROR: TOKEN หรือ DATABASE_URL หายไป")
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
        # เพิ่มคอลัมน์ user_name เพื่อเก็บชื่อคนพิมพ์
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
        print("✅ Database initialized")
    except Exception as e:
        print(f"❌ Database error: {e}")

def save_transaction(chat_id, amount, user_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', (chat_id, amount, user_name))
    conn.commit()
    cursor.close()
    conn.close()

def get_history(chat_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows # คืนค่าทั้งยอดเงินและชื่อ

def clear_history(chat_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE chat_id = %s', (chat_id,))
    conn.commit()
    cursor.close()
    conn.close()

# --- ส่วนการทำงานของบอท ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('✅ AK บอทคำนวณกลุ่ม (แสดงชื่อคนพิมพ์) พร้อมใช้งาน!\nพิมพ์ +เลข หรือ -เลข เพื่อบันทึกยอดรวม\n/reset ล้างข้อมูลกลุ่ม')

async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    user_name = update.message.from_user.first_name # ดึงชื่อเล่นของผู้ใช้

    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        operator, value = match.group(1), int(match.group(2))
        amount = value if operator == '+' else -value

        save_transaction(chat_id, amount, user_name)
        history_data = get_history(chat_id)
        
        total = sum(item[0] for item in history_data)
        count = len(history_data)
        
        response = "📋 AK机器人:记录 (ยอดรวมกลุ่ม)\n"
        
        if count > 10:
            response += "...\n"
            display_items = history_data[-10:]
            start_num = count - 9
        else:
            display_items = history_data
            start_num = 1

        for i, (val, name) in enumerate(display_items, start_num):
            symbol = "+" if val > 0 else ""
            response += f"{i}. {symbol}{val} ({name})\n" # แสดงชื่อคนพิมพ์ในวงเล็บ
        
        response += f"----------------\n"
        response += f"📊 全部: {count} 项目\n"
        response += f"💰 总金额: {total}"
        
        await update.message.reply_text(response)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    clear_history(chat_id)
    await update.message.reply_text("🧹 已清理数据! ")

# --- รันโปรแกรม ---
if __name__ == '__main__':
    init_db()
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    application.run_polling()
