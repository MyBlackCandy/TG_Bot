import os
import re
import psycopg2
import random
import requests
import asyncio
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, redirect, session
from threading import Thread
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- 1. CONFIGURATION ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')
WEB_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin1234')
MY_USDT_ADDR = os.getenv('USDT_ADDRESS')
TRON_API_KEY = os.getenv('TRONGRID_API_KEY')

# สร้าง Flask App สำหรับหน้าเว็บ
app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- 2. DATABASE UTILS ---
def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS paid_users (user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP, is_admin BOOLEAN DEFAULT FALSE)')
    cursor.execute('CREATE TABLE IF NOT EXISTS allowed_groups (chat_id BIGINT PRIMARY KEY, expire_date TIMESTAMP, added_by BIGINT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS pending_payments (user_id BIGINT PRIMARY KEY, expected_amount DECIMAL)')
    cursor.execute('CREATE TABLE IF NOT EXISTS processed_tx (txid TEXT PRIMARY KEY)')
    cursor.execute('CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, user_id BIGINT, chat_id BIGINT, amount INTEGER, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    conn.commit(); cursor.close(); conn.close()

# --- 3. PERMISSION CHECKS ---
def is_admin(user_id):
    if str(user_id) == str(MASTER_ADMIN): return True
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM paid_users WHERE user_id = %s AND expire_date > %s', (user_id, datetime.now()))
    res = cursor.fetchone(); cursor.close(); conn.close()
    return True if res else False

def is_allowed(chat_id, user_id):
    if str(user_id) == str(MASTER_ADMIN): return True
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM allowed_groups WHERE chat_id = %s AND expire_date > %s', (chat_id, datetime.now()))
    res = cursor.fetchone(); cursor.close(); conn.close()
    return True if res else False

# --- 4. BOT COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if str(user_id) == str(MASTER_ADMIN):
        await update.message.reply_text("👑 สวัสดีแอดมินหลัก! คุณใช้งานได้ฟรีทุกคำสั่ง\n/promote [ID] - ตั้งแอดมิน\n/add_time [ID] [วัน] - เพิ่มวัน")
        return
    amt = round(100 + random.uniform(0.01, 0.99), 2)
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO pending_payments VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expected_amount = EXCLUDED.expected_amount', (user_id, amt))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"💰 โอนเงิน `{amt}` USDT (TRC-20)\n🏦 Address: `{MY_USDT_ADDR}`\nเสร็จแล้วพิมพ์ /check", parse_mode='Markdown')

async def check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expected_amount FROM pending_payments WHERE user_id = %s', (user_id,))
    res = cursor.fetchone()
    if not res: return
    expected = float(res[0])
    
    url = f"https://api.trongrid.io/v1/accounts/{MY_USDT_ADDR}/transactions/trc20"
    params = {"limit": 10, "contract_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"}
    txs = requests.get(url, params=params).json().get('data', [])
    
    for tx in txs:
        val = int(tx['value'])/1_000_000
        if abs(val - expected) < 0.001:
            txid = tx['transaction_id']
            cursor.execute('SELECT 1 FROM processed_tx WHERE txid = %s', (txid,))
            if not cursor.fetchone():
                exp = datetime.now() + timedelta(days=30)
                cursor.execute('INSERT INTO processed_tx VALUES (%s)', (txid,))
                cursor.execute('INSERT INTO paid_users VALUES (%s, %s, TRUE) ON CONFLICT (user_id) DO UPDATE SET expire_date = EXCLUDED.expire_date, is_admin = TRUE', (user_id, exp))
                conn.commit()
                await update.message.reply_text("✅ ชำระเงินสำเร็จ! คุณเป็น Admin 30 วันแล้ว")
                return
    await update.message.reply_text("⏳ ไม่พบยอดโอน กรุณารอสักครู่")

async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id, user_id = update.effective_chat.id, update.message.from_user.id
    if not is_allowed(chat_id, user_id) and not is_admin(user_id): return
    
    match = re.match(r'^([+-])(\d+)$', update.message.text.strip())
    if match:
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (user_id, chat_id, amount) VALUES (%s, %s, %s)', (user_id, chat_id, amt))
        cursor.execute('SELECT amount FROM history WHERE user_id = %s AND chat_id = %s ORDER BY timestamp ASC', (user_id, chat_id))
        hist = [r[0] for r in cursor.fetchall()]; conn.commit(); cursor.close(); conn.close()
        
        count = len(hist)
        res = f"📋 记录: {update.message.from_user.first_name}\n"
        items = hist[-10:] if count > 10 else hist
        if count > 10: res += "...\n"
        for i, v in enumerate(items, (count-9 if count > 10 else 1)):
            res += f"{i}. {'+' if v > 0 else ''}{v}\n"
        res += f"----------------\n📊 全部: {count}\n💰 总金额: {sum(hist)}"
        await update.message.reply_text(res)

# --- 5. WEB PANEL (FLASK) ---
@app.route('/')
def dashboard():
    if not session.get('logged_in'): return '<h1>Login Required</h1>'
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT user_id, expire_date FROM paid_users'); users = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template_string('<h1>Dashboard</h1><table border="1">{% for u in users %}<tr><td>{{u[0]}}</td><td>{{u[1]}}</td><td><a href="/del/{{u[0]}}">Delete</a></td></tr>{% endfor %}</table>', users=users)

@app.route('/login', methods=['POST'])
def login():
    if request.form.get('pwd') == WEB_PASSWORD: session['logged_in'] = True
    return redirect('/')

# --- 6. RUNNER ---
def run_bot():
    init_db()
    bot = Application.builder().token(TOKEN).build()
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("check", check_payment))
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    bot.run_polling()

if __name__ == '__main__':
    Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
