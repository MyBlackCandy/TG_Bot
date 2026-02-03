import os
import re
import sys
import logging
import psycopg2
import requests
import random
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- ตั้งค่า Logging ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- ดึงค่าจาก Variables (Railway) ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')
MY_USDT_ADDR = os.getenv('USDT_ADDRESS')
TRON_API_KEY = os.getenv('TRONGRID_API_KEY')

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
        cursor.execute('CREATE TABLE IF NOT EXISTS customers (user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP)')
        cursor.execute('CREATE TABLE IF NOT EXISTS team_members (member_id BIGINT PRIMARY KEY, leader_id BIGINT, allowed_chat_id BIGINT)')
        cursor.execute('CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, chat_id BIGINT, amount INTEGER, user_name TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        cursor.execute('CREATE TABLE IF NOT EXISTS used_transactions (tx_id TEXT PRIMARY KEY, user_id BIGINT)')
        cursor.execute('CREATE TABLE IF NOT EXISTS pending_payments (user_id BIGINT PRIMARY KEY, amount DECIMAL, expire_at TIMESTAMP)')
        conn.commit(); cursor.close(); conn.close()
        print("✅ Database & Systems Ready")
    except Exception as e:
        print(f"❌ DB Error: {e}")

# --- ระบบตรวจสอบ Blockchain ---
def verify_on_chain(expected_amount, user_id):
    url = f"https://api.trongrid.io/v1/accounts/{MY_USDT_ADDR}/transactions/trc20"
    params = {"limit": 20, "contract_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"}
    headers = {"TRON-PRO-API-KEY": TRON_API_KEY} if TRON_API_KEY else {}
    try:
        response = requests.get(url, params=params, headers=headers).json()
        for tx in response.get('data', []):
            amount = int(tx['value']) / 1_000_000
            if abs(amount - float(expected_amount)) < 0.0001:
                tx_id = tx['transaction_id']
                conn = get_db_connection(); cursor = conn.cursor()
                cursor.execute('SELECT 1 FROM used_transactions WHERE tx_id = %s', (tx_id,))
                if not cursor.fetchone():
                    cursor.execute('INSERT INTO used_transactions (tx_id, user_id) VALUES (%s, %s)', (tx_id, user_id))
                    conn.commit(); cursor.close(); conn.close()
                    return True
                cursor.close(); conn.close()
        return False
    except: return False

# --- ระบบแจ้งเตือน Master Admin ---
async def notify_master(context: ContextTypes.DEFAULT_TYPE, message: str):
    if MASTER_ADMIN:
        try: await context.bot.send_message(chat_id=MASTER_ADMIN, text=message, parse_mode='Markdown')
        except: pass

# --- ระบบเช็คสิทธิ์ ---
def check_access(user_id, chat_id):
    if str(user_id) == str(MASTER_ADMIN): return True
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM customers WHERE user_id = %s AND expire_date > %s', (user_id, datetime.now()))
    if cursor.fetchone(): 
        cursor.close(); conn.close(); return True
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    res = cursor.fetchone(); cursor.close(); conn.close()
    return True if res else False

# --- COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    dec = random.randint(1, 99) / 100
    amt = 100 + dec
    exp = datetime.now() + timedelta(minutes=15)
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO pending_payments VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET amount=EXCLUDED.amount, expire_at=EXCLUDED.expire_at', (update.message.from_user.id, amt, exp))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"💳 **ยอดโอน:** `{amt:.2f}` USDT (TRC-20)\n🏦 `{MY_USDT_ADDR}`\n⏰ โอนภายใน 15 นาที แล้วพิมพ์ /verify", parse_mode='Markdown')

async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT amount, expire_at FROM pending_payments WHERE user_id = %s', (user.id,))
    res = cursor.fetchone()
    if not res or datetime.now() > res[1]:
        await update.message.reply_text("❌ ไม่มีรายการโอนที่รอดำเนินการหรือหมดเวลาแล้ว")
        return
    if verify_on_chain(res[0], user.id):
        cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (user.id,))
        old = cursor.fetchone()
        new_exp = (old[0] if old and old[0] > datetime.now() else datetime.now()) + timedelta(days=30)
        cursor.execute('INSERT INTO customers VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date', (user.id, new_exp))
        cursor.execute('DELETE FROM pending_payments WHERE user_id = %s', (user.id,))
        conn.commit()
        await update.message.reply_text(f"✅ ชำระสำเร็จ! ถึง: {new_exp.strftime('%Y-%m-%d')}")
        await notify_master(context, f"💰 **ชำระเงินใหม่!**\n👤 {user.first_name}\n🏷 @{user.username}\n💵 `{res[0]:.2f}` USDT")
    else: await update.message.reply_text("❌ ไม่พบยอดโอนที่ตรงกัน")
    cursor.close(); conn.close()

async def track_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for m in update.message.new_chat_members:
        if m.id == context.bot.id:
            u = update.message.from_user
            await notify_master(context, f"🤖 **บอทเข้ากลุ่มใหม่!**\n🏰 `{update.effective_chat.title}`\n👤 {u.first_name} (@{u.username})")

async def add_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.message.from_user.id, update.effective_chat.id) or not update.message.reply_to_message: return
    t = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO team_members VALUES (%s, %s, %s) ON CONFLICT (member_id) DO UPDATE SET allowed_chat_id=EXCLUDED.allowed_chat_id', (t.id, update.message.from_user.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"✅ เพิ่มลูกทีม `{t.first_name}` เรียบร้อย")

async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    chat_id = update.effective_chat.id
    if not check_access(update.message.from_user.id, chat_id): return
    match = re.match(r'^([+-])(\d+)$', update.message.text.strip())
    if match:
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', (chat_id, amt, update.message.from_user.first_name))
        conn.commit()
        cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
        rows = cursor.fetchall(); cursor.close(); conn.close()
        total = sum(r[0] for r in rows)
        res = f"📋 AK机器人:记录\n" + "\n".join([f"{i+1}. {('+' if r[0]>0 else '')}{r[0]} ({r[1]})" for i, r in enumerate(rows[-10:])]) + f"\n----------------\n💰 总金额: {total}"
        await update.message.reply_text(res)

async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ ยกเลิกรายการล่าสุดแล้ว")

# --- Main Run ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, track_chat))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("verify", verify))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("undo", undo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    app.run_polling()
