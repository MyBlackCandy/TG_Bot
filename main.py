import os
import re
import sys
import logging
import psycopg2
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- ตั้งค่า Logging ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- ดึงค่าจาก Variables (Railway) ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')

if not TOKEN or not DATABASE_URL:
    print("❌ ERROR: TOKEN หรือ DATABASE_URL หายไป")
    sys.exit(1)

# --- ส่วนจัดการฐานข้อมูล ---
def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        # ตารางหัวหน้าทีม (ลูกค้าหลัก)
        cursor.execute('CREATE TABLE IF NOT EXISTS customers (user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP)')
        # ตารางลูกทีม (จำกัดกลุ่ม)
        cursor.execute('CREATE TABLE IF NOT EXISTS team_members (member_id BIGINT PRIMARY KEY, leader_id BIGINT, allowed_chat_id BIGINT)')
        # ตารางประวัติการคำนวณ
        cursor.execute('CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, chat_id BIGINT, amount INTEGER, user_name TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        conn.commit(); cursor.close(); conn.close()
        print("✅ Database & Security System Ready")
    except Exception as e:
        print(f"❌ DB Error: {e}")

# --- ระบบเช็คสิทธิ์ ---
def check_access(user_id, chat_id):
    if str(user_id) == str(MASTER_ADMIN): return True
    conn = get_db_connection(); cursor = conn.cursor()
    # เช็คหัวหน้าทีม (ใช้ได้ทุกที่)
    cursor.execute('SELECT 1 FROM customers WHERE user_id = %s AND expire_date > %s', (user_id, datetime.now()))
    if cursor.fetchone(): 
        cursor.close(); conn.close(); return True
    # เช็คลูกทีม (ต้องตรงกลุ่ม)
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    res = cursor.fetchone(); cursor.close(); conn.close()
    return True if res else False

# --- [วิธีที่ 1] สำหรับ Master Admin: ตั้งหัวหน้าทีมโดยการ Reply ---
async def set_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    if not update.message.reply_to_message:
        await update.message.reply_text("💡 **วิธีใช้:** Reply ข้อความลูกค้าแล้วพิมพ์ `/setadmin 30` (เลขคือจำนวนวัน)")
        return
    try:
        target = update.message.reply_to_message.from_user
        days = int(context.args[0]) if context.args else 30
        exp = datetime.now() + timedelta(days=days)
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO customers VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date = EXCLUDED.expire_date', (target.id, exp))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"👑 ตั้ง `{target.first_name}` เป็นหัวหน้าทีมสำเร็จ!\n📅 หมดอายุ: {exp.strftime('%Y-%m-%d')}")
    except: await update.message.reply_text("❌ ใส่จำนวนวันให้ถูกต้อง เช่น /setadmin 30")

# --- สำหรับหัวหน้าทีม: เพิ่มลูกทีมโดยการ Reply ในกลุ่ม ---
async def add_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leader_id = update.message.from_user.id
    chat_id = update.effective_chat.id
    if not check_access(leader_id, chat_id): return
    if not update.message.reply_to_message:
        await update.message.reply_text("💡 **วิธีใช้:** Reply ข้อความลูกทีมในกลุ่มแล้วพิมพ์ /add")
        return
    target = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO team_members VALUES (%s, %s, %s) ON CONFLICT (member_id) DO UPDATE SET allowed_chat_id = EXCLUDED.allowed_chat_id', (target.id, leader_id, chat_id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"✅ เพิ่ม `{target.first_name}` เป็นลูกทีมในกลุ่มนี้เรียบร้อย!")

# --- ระบบคำนวณเงิน ---
async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    chat_id = update.effective_chat.id
    user_id = update.message.from_user.id
    if not check_access(user_id, chat_id): return

    text = update.message.text.strip()
    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        val = int(match.group(2))
        amount = val if match.group(1) == '+' else -val
        user_name = update.message.from_user.first_name
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', (chat_id, amount, user_name))
        conn.commit()
        cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
        rows = cursor.fetchall(); cursor.close(); conn.close()
        total = sum(r[0] for r in rows); count = len(rows)
        res = "📋 AK机器人:记录\n"
        display = rows[-10:] if count > 10 else rows
        if count > 10: res += "...\n"
        for i, (v, name) in enumerate(display, (count-9 if count > 10 else 1)):
            res += f"{i}. {'+' if v > 0 else ''}{v} ({name})\n"
        res += f"----------------\n📊 全部: {count} | 💰 总金额: {total}"
        await update.message.reply_text(res)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE chat_id = %s', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("🧹 已清理数据!")

# --- รันโปรแกรม ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("setadmin", set_admin))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    app.run_polling()
