import os
import re
import psycopg2
import requests
import random
import asyncio
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- ⚙️ CONFIGURATION ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')
MY_USDT_ADDR = os.getenv('USDT_ADDRESS')

# --- 🗄️ DATABASE SYSTEM ---
def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS customers (
        user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP, username TEXT, first_name TEXT
    )''')
    cursor.execute('CREATE TABLE IF NOT EXISTS team_members (member_id BIGINT PRIMARY KEY, leader_id BIGINT, allowed_chat_id BIGINT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, chat_id BIGINT, amount INTEGER, user_name TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cursor.execute('CREATE TABLE IF NOT EXISTS used_transactions (tx_id TEXT PRIMARY KEY, user_id BIGINT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS pending_payments (user_id BIGINT PRIMARY KEY, amount DECIMAL, expire_at TIMESTAMP)')
    conn.commit(); cursor.close(); conn.close()

def check_access(user_id, chat_id):
    if str(user_id) == str(MASTER_ADMIN): return True
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM customers WHERE user_id = %s AND expire_date > %s', (user_id, datetime.now()))
    is_cust = cursor.fetchone()
    if is_cust: 
        cursor.close(); conn.close(); return True
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    res = cursor.fetchone(); cursor.close(); conn.close()
    return True if res else False

# --- 🔄 AUTO VERIFY (TRONSCAN) ---
async def auto_verify_task(context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('SELECT user_id, amount FROM pending_payments WHERE expire_at > %s', (datetime.now(),))
        pending = cursor.fetchall()
        if pending:
            url = "https://apilist.tronscan.org/api/token_trc20/transfers"
            params = {"limit": 30, "direction": "in", "relatedAddress": MY_USDT_ADDR}
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json().get('token_transfers', [])
                for uid, amt in pending:
                    for tx in data:
                        token_info = tx.get('tokenInfo', {})
                        if tx.get('to_address') == MY_USDT_ADDR and token_info.get('symbol') == 'USDT':
                            tx_amount = float(tx.get('quant', 0)) / (10 ** int(token_info.get('decimals', 6)))
                            tx_id = tx.get('transaction_id')
                            if abs(tx_amount - float(amt)) < 0.001:
                                cursor.execute('SELECT 1 FROM used_transactions WHERE tx_id=%s', (tx_id,))
                                if not cursor.fetchone():
                                    cursor.execute('INSERT INTO used_transactions VALUES (%s, %s)', (tx_id, uid))
                                    cursor.execute('SELECT expire_date FROM customers WHERE user_id=%s', (uid,))
                                    old = cursor.fetchone()
                                    base = old[0] if old and old[0] > datetime.now() else datetime.now()
                                    new_exp = base + timedelta(days=30)
                                    cursor.execute('''INSERT INTO customers (user_id, expire_date) VALUES (%s, %s) 
                                                   ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date''', (uid, new_exp))
                                    cursor.execute('DELETE FROM pending_payments WHERE user_id=%s', (uid,))
                                    conn.commit()
                                    await context.bot.send_message(chat_id=uid, text=f"✅ **支付成功!** 到期: `{new_exp.strftime('%Y-%m-%d %H:%M')}`")
        cursor.close(); conn.close()
    except Exception as e: print(f"TronScan Error: {e}")

# --- 🤖 HANDLERS ---
async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ **已撤销记录 (ยกเลิกรายการล่าสุดแล้ว)**")

async def reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE chat_id = %s', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("🧹 **账目已清空 (ล้างบัญชีทั้งหมดเรียบร้อยแล้ว)**")

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        if not check_access(update.message.from_user.id, update.effective_chat.id): return
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', (update.effective_chat.id, amt, update.message.from_user.first_name))
        conn.commit()
        cursor.execute('SELECT SUM(amount) FROM history WHERE chat_id = %s', (update.effective_chat.id,))
        total = cursor.fetchone()[0] or 0
        cursor.close(); conn.close()
        await update.message.reply_text(f"📝 记录: {text} | 💰 总额: {total}")

# --- (Handlers อื่นๆ: start, check_status, set_admin, add_member, remove_member ก๊อปปี้จากเวอร์ชันก่อนหน้า) ---

if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    if app.job_queue: app.job_queue.run_repeating(auto_verify_task, interval=30, first=10)
    
    # ลงทะเบียนคำสั่ง
    app.add_handler(CommandHandler("undo", undo))
    app.add_handler(CommandHandler("reset", reset_history))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("remove", remove_member))
    app.add_handler(CommandHandler("setadmin", set_admin))
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(CommandHandler("start", start))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.run_polling()
