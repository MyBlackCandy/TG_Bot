import os
import re
import sys
import logging
import psycopg2
import random
import requests
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ตั้งค่า Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')
MY_USDT_ADDR = os.getenv('USDT_ADDRESS')

def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # ตารางเก็บประวัติการคำนวณ
        cursor.execute('''CREATE TABLE IF NOT EXISTS history (
            id SERIAL PRIMARY KEY, chat_id BIGINT, amount INTEGER, user_name TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        # ตารางเก็บรายชื่อลูกค้าที่ชำระเงินแล้ว
        cursor.execute('''CREATE TABLE IF NOT EXISTS paid_customers (
            user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP)''')
        # ตารางเก็บยอดรอชำระ
        cursor.execute('''CREATE TABLE IF NOT EXISTS pending_payments (
            user_id BIGINT PRIMARY KEY, expected_amount DECIMAL)''')
        conn.commit()
        cursor.close(); conn.close()
        print("✅ Database & Security System Ready")
    except Exception as e:
        print(f"❌ DB Error: {e}")

# ฟังก์ชันเช็คสิทธิ์ลูกค้า
def is_customer(user_id):
    if str(user_id) == str(MASTER_ADMIN): return True # แอดมินหลักใช้ได้ตลอด
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM paid_customers WHERE user_id = %s AND expire_date > %s', (user_id, datetime.now()))
    res = cursor.fetchone()
    cursor.close(); conn.close()
    return True if res else False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if is_customer(user_id):
        await update.message.reply_text("🚀 ยินดีต้อนรับลูกค้า! บอทพร้อมคำนวณยอดให้คุณแล้วครับ")
    else:
        # สุ่มยอดทศนิยมเพื่อให้ตรวจสอบง่าย
        amt = round(100 + random.uniform(0.01, 0.99), 2)
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO pending_payments VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expected_amount = EXCLUDED.expected_amount', (user_id, amt))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(
            f"⚠️ ขออภัย! บอทนี้เปิดให้ใช้งานเฉพาะลูกค้าเท่านั้น\n\n"
            f"💰 ค่าบริการ: `{amt}` USDT (30 วัน)\n"
            f"🏦 กระเป๋า (TRC-20): `{MY_USDT_ADDR}`\n"
            f"โอนเสร็จแล้วกรุณาแจ้งแอดมินเพื่อเปิดระบบครับ", parse_mode='Markdown'
        )

async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user_id = update.message.from_user.id
    
    # ตรวจสอบสิทธิ์ก่อนทำงาน
    if not is_customer(user_id):
        await update.message.reply_text("❌ คุณยังไม่ได้เป็นลูกค้า หรือสิทธิ์การใช้งานหมดอายุแล้ว กรุณาพิมพ์ /start")
        return

    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    user_name = update.message.from_user.first_name

    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        val = int(match.group(2))
        amount = val if match.group(1) == '+' else -val

        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', (chat_id, amount, user_name))
        conn.commit()
        
        cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
        rows = cursor.fetchall(); cursor.close(); conn.close()
        
        total = sum(r[0] for r in rows)
        count = len(rows)
        res = f"📋 AK机器人:记录\n"
        display = rows[-10:] if count > 10 else rows
        if count > 10: res += "...\n"
        for i, (v, name) in enumerate(display, (count-9 if count > 10 else 1)):
            res += f"{i}. {'+' if v > 0 else ''}{v} ({name})\n"
        res += f"----------------\n📊 全部: {count}\n💰 总金额: {total}"
        await update.message.reply_text(res)

# คำสั่งสำหรับคุณ (Master Admin) เพื่อเพิ่มลูกค้าเอง
async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    try:
        target_id = int(context.args[0])
        days = int(context.args[1]) if len(context.args) > 1 else 30
        exp = datetime.now() + timedelta(days=days)
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO paid_customers VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date = EXCLUDED.expire_date', (target_id, exp))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"✅ เพิ่มลูกค้า `{target_id}` เรียบร้อย (ใช้งานได้ถึง {exp.strftime('%Y-%m-%d')})")
    except:
        await update.message.reply_text("❌ รูปแบบ: /add [User_ID] [จำนวนวัน]")

if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_user))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    app.run_polling()
