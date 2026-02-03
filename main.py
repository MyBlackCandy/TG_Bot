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
MASTER_ADMIN = os.getenv('ADMIN_ID') # ID ของคุณ (แอดมินหลัก)
MY_USDT_ADDR = os.getenv('USDT_ADDRESS')

# --- 🗄️ DATABASE SYSTEM ---
def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS customers (
        user_id BIGINT PRIMARY KEY, 
        expire_date TIMESTAMP,
        username TEXT,
        first_name TEXT
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
            url = f"https://apilist.tronscan.org/api/token_trc20/transfers"
            params = {"limit": 20, "start": 0, "direction": "in", "relatedAddress": MY_USDT_ADDR}
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json().get('token_transfers', [])
                for uid, amt in pending:
                    for tx in data:
                        if tx['to_address'] == MY_USDT_ADDR and tx['tokenInfo']['symbol'] == 'USDT':
                            tx_amount = float(tx['quant']) / (10 ** int(tx['tokenInfo']['decimals']))
                            tx_id = tx['transaction_id']
                            
                            if abs(tx_amount - float(amt)) < 0.001:
                                cursor.execute('SELECT 1 FROM used_transactions WHERE tx_id=%s', (tx_id,))
                                if not cursor.fetchone():
                                    try:
                                        chat = await context.bot.get_chat(uid)
                                        uname, fname = chat.username, chat.first_name
                                    except: uname, fname = None, "User"

                                    cursor.execute('INSERT INTO used_transactions VALUES (%s, %s)', (tx_id, uid))
                                    cursor.execute('SELECT expire_date FROM customers WHERE user_id=%s', (uid,))
                                    old = cursor.fetchone()
                                    base = old[0] if old and old[0] > datetime.now() else datetime.now()
                                    new_exp = base + timedelta(days=30)
                                    
                                    cursor.execute('''INSERT INTO customers (user_id, expire_date, username, first_name) VALUES (%s, %s, %s, %s) 
                                                   ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date, username=EXCLUDED.username, first_name=EXCLUDED.first_name''', 
                                                   (uid, new_exp, uname, fname))
                                    cursor.execute('DELETE FROM pending_payments WHERE user_id=%s', (uid,))
                                    conn.commit()
                                    await context.bot.send_message(chat_id=uid, text=f"✅ **支付成功!** 到期: `{new_exp.strftime('%Y-%m-%d %H:%M')}`")
        cursor.close(); conn.close()
    except Exception as e: print(f"TronScan Error: {e}")

# --- 🤖 HANDLERS ---

async def set_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """คำสั่ง /setadmin [ID] [จำนวนวัน] - สำหรับแอดมินหลักใช้เพิ่มวันเอง"""
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    try:
        user_id = int(context.args[0])
        days = int(context.args[1])
        new_exp = datetime.now() + timedelta(days=days)
        
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('''INSERT INTO customers (user_id, expire_date, first_name) VALUES (%s, %s, %s) 
                       ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date''', 
                       (user_id, new_exp, "Manual_Add"))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"✅ **已手动激活**\nID: `{user_id}`\n天数: {days} 天\n到期: `{new_exp.strftime('%Y-%m-%d %H:%M')}`")
    except: await update.message.reply_text("格式: `/setadmin [ID] [天数]`")

async def add_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return await update.message.reply_text("⚠️ 请回复成员以授权")
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    t = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO team_members VALUES (%s, %s, %s) ON CONFLICT (member_id) DO UPDATE SET allowed_chat_id=EXCLUDED.allowed_chat_id', (t.id, update.message.from_user.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"✅ **授权成功:** {t.first_name}")

async def remove_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return await update.message.reply_text("⚠️ 请回复成员以取消")
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    t = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (t.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"🚫 **已取消授权:** {t.first_name}")

async def list_customers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT user_id, expire_date, username, first_name FROM customers ORDER BY expire_date DESC')
    rows = cursor.fetchall(); cursor.close(); conn.close()
    if not rows: return await update.message.reply_text("📋 **暂无会员记录**")
    msg = "👑 **会员管理列表**\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, row in enumerate(rows):
        st = "✅" if row[1] > datetime.now() else "❌"
        msg += f"{i+1}. {st} **{row[3]}**\n   ID: `{row[0]}` | ถึง: `{row[1].strftime('%Y-%m-%d %H:%M')}`\n\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- (Other Handlers: start, check_status, show_history, undo, reset_history, handle_msg, get_my_id) ---
# ... (ก๊อปปี้จากเวอร์ชันก่อนหน้ามาใส่ให้ครบ) ...

# --- 🚀 RUN BOT ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    if app.job_queue: app.job_queue.run_repeating(auto_verify_task, interval=30, first=10)
    
    # Register Commands - ลำดับความสำคัญ
    app.add_handler(CommandHandler("setadmin", set_admin)) # สำหรับเพิ่มวันกรณีฉุกเฉิน
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("remove", remove_member))
    app.add_handler(CommandHandler("list", list_customers))
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(CommandHandler("undo", undo))
    app.add_handler(CommandHandler("reset", reset_history))
    app.add_handler(CommandHandler("show", show_history))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", get_my_id))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.run_polling()
