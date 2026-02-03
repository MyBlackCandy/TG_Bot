import os
import re
import psycopg2
import requests
import random
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIG ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')
MY_USDT_ADDR = os.getenv('USDT_ADDRESS')
TRON_API_KEY = os.getenv('TRONGRID_API_KEY')

def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS customers (user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP)')
    cursor.execute('CREATE TABLE IF NOT EXISTS team_members (member_id BIGINT PRIMARY KEY, leader_id BIGINT, allowed_chat_id BIGINT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, chat_id BIGINT, amount INTEGER, user_name TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cursor.execute('CREATE TABLE IF NOT EXISTS used_transactions (tx_id TEXT PRIMARY KEY, user_id BIGINT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS pending_payments (user_id BIGINT PRIMARY KEY, amount DECIMAL, expire_at TIMESTAMP)')
    conn.commit(); cursor.close(); conn.close()

async def notify_master(context, message):
    if MASTER_ADMIN: await context.bot.send_message(chat_id=MASTER_ADMIN, text=message, parse_mode='Markdown')

# --- ชำระเงินส่วนตัว ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    amt = 100 + (random.randint(1, 99) / 100)
    exp = datetime.now() + timedelta(minutes=15)
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO pending_payments VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET amount=EXCLUDED.amount, expire_at=EXCLUDED.expire_at', (update.message.from_user.id, amt, exp))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"💰 ยอดโอน: `{amt:.2f}` USDT\n🏦 `{MY_USDT_ADDR}`\n⏰ โอนภายใน 15 นาที แล้วพิมพ์ /verify", parse_mode='Markdown')

async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT amount, expire_at FROM pending_payments WHERE user_id = %s', (user.id,))
    res = cursor.fetchone()
    if not res or datetime.now() > res[1]:
        await update.message.reply_text("❌ ไม่มีรายการโอนที่รอดำเนินการหรือหมดเวลาแล้ว")
        return
    
    # ตรวจสอบ Blockchain
    url = f"https://api.trongrid.io/v1/accounts/{MY_USDT_ADDR}/transactions/trc20"
    params = {"limit": 20, "contract_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"}
    headers = {"TRON-PRO-API-KEY": TRON_API_KEY} if TRON_API_KEY else {}
    found = False
    try:
        data = requests.get(url, params=params, headers=headers).json()
        for tx in data.get('data', []):
            if abs((int(tx['value'])/1000000) - float(res[0])) < 0.0001:
                cursor.execute('SELECT 1 FROM used_transactions WHERE tx_id=%s', (tx['transaction_id'],))
                if not cursor.fetchone():
                    cursor.execute('INSERT INTO used_transactions VALUES (%s, %s)', (tx['transaction_id'], user.id))
                    found = True; break
    except: pass

    if found:
        cursor.execute('SELECT expire_date FROM customers WHERE user_id=%s', (user.id,))
        old = cursor.fetchone()
        new_exp = (old[0] if old and old[0] > datetime.now() else datetime.now()) + timedelta(days=30)
        cursor.execute('INSERT INTO customers VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date', (user.id, new_exp))
        cursor.execute('DELETE FROM pending_payments WHERE user_id=%s', (user.id,))
        conn.commit()
        await update.message.reply_text(f"✅ ชำระสำเร็จ! ถึง: {new_exp.strftime('%Y-%m-%d')}")
        await notify_master(context, f"💰 **ชำระเงินใหม่!**\n👤 {user.first_name} (@{user.username})")
    else: await update.message.reply_text("❌ ไม่พบยอดโอนที่ตรงกัน")
    cursor.close(); conn.close()

# --- ระบบกลุ่ม ---
async def track_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for m in update.message.new_chat_members:
        if m.id == context.bot.id:
            u = update.message.from_user
            await notify_master(context, f"🤖 **บอทเข้ากลุ่มใหม่!**\n🏰 `{update.effective_chat.title}`\n👤 คนดึง: {u.first_name} (@{u.username})")

if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, track_chat))
    app.add_handler(CommandHandler("start", start)); app.add_handler(CommandHandler("verify", verify))
    # เพิ่ม Handler อื่นๆ (add, undo, handle_calc) ตามเดิม
    app.run_polling()
