import os
import re
import sys
import logging
import psycopg2
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ตั้งค่า Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- ดึงค่าจาก Variables ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
ADMIN_ID = os.getenv('ADMIN_ID') 

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
        cursor.execute('''CREATE TABLE IF NOT EXISTS history (
            id SERIAL PRIMARY KEY, user_id BIGINT, amount INTEGER, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY, is_paid BOOLEAN DEFAULT TRUE)''')
        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Database & Whitelist initialized")
    except Exception as e:
        print(f"❌ Database error: {e}")

# ฟังก์ชันจัดการสิทธิ์
def is_user_allowed(user_id):
    if str(user_id) == str(ADMIN_ID): return True
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT is_paid FROM users WHERE user_id = %s', (user_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result[0] if result else False

def add_paid_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO users (user_id) VALUES (%s) ON CONFLICT (user_id) DO UPDATE SET is_paid = TRUE', (user_id,))
    conn.commit()
    cursor.close()
    conn.close()

def remove_paid_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM users WHERE user_id = %s', (user_id,))
    conn.commit()
    cursor.close()
    conn.close()

# ฟังก์ชันจัดการตัวเลข
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

# --- ส่วนคำสั่งบอท ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('✅ AK机器人: 准备就绪\n输入 +数字 或 -数字\n/reset 清理数据')

# [ADMIN] เพิ่มสิทธิ์
async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(ADMIN_ID): return
    try:
        target_id = int(context.args[0])
        add_paid_user(target_id)
        await update.message.reply_text(f"✅ 已授权 User ID: {target_id}")
    except:
        await update.message.reply_text("❌ 格式错误: /add [User_ID]")

# [ADMIN] ลบสิทธิ์
async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(ADMIN_ID): return
    try:
        target_id = int(context.args[0])
        remove_paid_user(target_id)
        await update.message.reply_text(f"🚫 已取消 User ID: {target_id} 的访问权限")
    except:
        await update.message.reply_text("❌ 格式错误: /remove [User_ID]")

async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not is_user_allowed(user_id):
        await update.message.reply_text(f"⚠️ 抱歉，该机器人仅限付费用户使用。\n您的 ID: `{user_id}`\n请联系管理员开通。", parse_mode='Markdown')
        return

    text = update.message.text.strip()
    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        operator, value = match.group(1), int(match.group(2))
        amount = value if operator == '+' else -value
        save_transaction(user_id, amount)
        history = get_history(user_id)
        total = sum(history)
        count = len(history)
        
        response = "📋 AK机器人: 记录\n"
        if count > 10:
            response += "...\n"
            display_items = history[-10:]
            start_num = count - 9
        else:
            display_items = history
            start_num = 1

        for i, val in enumerate(display_items, start_num):
            symbol = "+" if val > 0 else ""
            response += f"{i}. {symbol}{val}\n"
        
        response += f"----------------\n📊 全部: {count} 项目\n💰 总金额: {total}"
        await update.message.reply_text(response)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_user_allowed(update.message.from_user.id): return
    clear_history(update.message.from_user.id)
    await update.message.reply_text("🧹 已清理数据!")

# --- รันโปรแกรม ---
if __name__ == '__main__':
    init_db()
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add", add))
    application.add_handler(CommandHandler("remove", remove)) # เพิ่ม Handler สำหรับลบสิทธิ์
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    application.run_polling()
