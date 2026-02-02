import os
import re
import sys
import requests
import psycopg2
import random
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- Variables ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')
MY_USDT_ADDR = os.getenv('USDT_ADDRESS')
TRON_API_KEY = os.getenv('TRONGRID_API_KEY')

def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # ตารางสมาชิก (Admin รายบุคคล)
    cursor.execute('''CREATE TABLE IF NOT EXISTS paid_users (
        user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP, is_admin BOOLEAN DEFAULT FALSE)''')
    # ตารางสิทธิ์ของกลุ่ม (ที่ Admin ไปเพิ่มให้)
    cursor.execute('''CREATE TABLE IF NOT EXISTS allowed_groups (
        chat_id BIGINT PRIMARY KEY, expire_date TIMESTAMP, added_by BIGINT)''')
    # ตารางเก็บยอดสุ่มที่รอการชำระ
    cursor.execute('''CREATE TABLE IF NOT EXISTS pending_payments (
        user_id BIGINT PRIMARY KEY, expected_amount DECIMAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS processed_tx (txid TEXT PRIMARY KEY)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS history (
        id SERIAL PRIMARY KEY, user_id BIGINT, chat_id BIGINT, amount INTEGER, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    cursor.close()
    conn.close()

# --- เช็คสิทธิ์ ---
def is_admin(user_id):
    if str(user_id) == str(MASTER_ADMIN): return True
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT is_admin FROM paid_users WHERE user_id = %s AND expire_date > %s', (user_id, datetime.now()))
    res = cursor.fetchone()
    cursor.close()
    conn.close()
    return True if res else False

def is_group_allowed(chat_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM allowed_groups WHERE chat_id = %s AND expire_date > %s', (chat_id, datetime.now()))
    res = cursor.fetchone()
    cursor.close()
    conn.close()
    return True if res else False

# --- ระบบเช็ค Blockchain ---
def check_usdt_payment():
    url = f"https://api.trongrid.io/v1/accounts/{MY_USDT_ADDR}/transactions/trc20"
    params = {"limit": 15, "contract_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"}
    headers = {"TRON-PRO-API-KEY": TRON_API_KEY} if TRON_API_KEY else {}
    try:
        return requests.get(url, params=params, headers=headers).json().get('data', [])
    except:
        return []

# --- คำสั่งบอท ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    # สุ่มทศนิยม 0.01 - 0.99
    random_decimal = round(random.uniform(0.01, 0.99), 2)
    final_amount = 100 + random_decimal

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO pending_payments (user_id, expected_amount) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expected_amount = EXCLUDED.expected_amount', (user_id, final_amount))
    conn.commit()
    cursor.close()
    conn.close()

    await update.message.reply_text(
        f"🤖 **AK บอทคำนวณอัตโนมัติ**\n\n"
        f"⚠️ **ยอดที่ต้องโอนเป๊ะๆ:** `{final_amount}` USDT\n"
        f"🏦 **Network:** TRC-20\n"
        f"📍 **Address:** `{MY_USDT_ADDR}`\n\n"
        "เมื่อโอนแล้วรอ 1 นาที แล้วพิมพ์ `/check` เพื่อรับสิทธิ์ Admin ทันที!"
    )

async def check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT expected_amount FROM pending_payments WHERE user_id = %s', (user_id,))
    res = cursor.fetchone()
    
    if not res:
        await update.message.reply_text("❌ ไม่พบรายการค้างชำระ พิมพ์ /start เพื่อขอรับยอด")
        return

    expected = float(res[0])
    payments = check_usdt_payment()
    found = False

    for tx in payments:
        amount = int(tx['value']) / 1_000_000
        txid = tx['transaction_id']
        # เช็คยอดโอนให้ตรงกับที่สุ่มไว้ (เผื่อค่า Diff เล็กน้อย)
        if abs(amount - expected) < 0.001:
            cursor.execute('SELECT 1 FROM processed_tx WHERE txid = %s', (txid,))
            if not cursor.fetchone():
                expire = datetime.now() + timedelta(days=30)
                cursor.execute('INSERT INTO processed_tx (txid) VALUES (%s)', (txid,))
                cursor.execute('INSERT INTO paid_users (user_id, expire_date, is_admin) VALUES (%s, %s, TRUE) ON CONFLICT (user_id) DO UPDATE SET expire_date = EXCLUDED.expire_date, is_admin = TRUE', (user_id, expire))
                cursor.execute('DELETE FROM pending_payments WHERE user_id = %s', (user_id,))
                conn.commit()
                found = True
                break
    
    cursor.close()
    conn.close()
    if found:
        await update.message.reply_text(f"✅ **ชำระเงินสำเร็จ!**\nคุณเป็น Admin แล้ว 30 วัน\n\n💡 **วิธีเพิ่มสิทธิ์ให้กลุ่ม:**\nนำบอทเข้ากลุ่มแล้วพิมพ์ `/open` ในกลุ่มนั้นได้เลย!")
    else:
        await update.message.reply_text(f"⏳ ยังไม่พบยอดโอน `{expected}` USDT เข้ามา กรุณารอสักครู่")

async def open_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    chat_id = update.effective_chat.id
    
    if update.effective_chat.type == "private":
        await update.message.reply_text("❌ คำสั่งนี้ต้องใช้ในกลุ่มเท่านั้น")
        return

    if is_admin(user_id):
        expire = datetime.now() + timedelta(days=30)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO allowed_groups (chat_id, expire_date, added_by) VALUES (%s, %s, %s) ON CONFLICT (chat_id) DO UPDATE SET expire_date = EXCLUDED.expire_date', (chat_id, expire, user_id))
        conn.commit()
        cursor.close()
        conn.close()
        await update.message.reply_text(f"✅ **เปิดใช้งานกลุ่มนี้สำเร็จ!**\nโดย Admin: {update.message.from_user.first_name}\n📅 หมดอายุ: {expire.strftime('%Y-%m-%d')}")
    else:
        await update.message.reply_text("❌ เฉพาะ Admin (ผู้ชำระเงิน) เท่านั้นที่เปิดสิทธิ์กลุ่มได้")

async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.message.from_user.id

    # ตรวจสอบว่ากลุ่มนี้ได้รับสิทธิ์หรือยัง (หรือคนพิมพ์เป็น Admin เอง)
    if not is_group_allowed(chat_id) and not is_admin(user_id):
        return # ไม่ตอบโต้ในกลุ่มที่ไม่มีสิทธิ์

    text = update.message.text.strip()
    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        operator, value = match.group(1), int(match.group(2))
        amount = value if operator == '+' else -value
        # ... (ส่วนบันทึกและแสดงผลเหมือนเดิมของคุณ) ...
