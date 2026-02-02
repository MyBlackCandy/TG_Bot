import os
import re
import sys
import logging
import psycopg2
import random
import requests
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, redirect, session
from threading import Thread
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- Configuration & Logging ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID') # เลข ID ของคุณที่ตั้งใน Railway
WEB_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin1234')
MY_USDT_ADDR = os.getenv('USDT_ADDRESS')
TRON_API_KEY = os.getenv('TRONGRID_API_KEY')

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- Database Management ---
def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS paid_users (
        user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP, is_admin BOOLEAN DEFAULT FALSE)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS allowed_groups (
        chat_id BIGINT PRIMARY KEY, expire_date TIMESTAMP, added_by BIGINT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS pending_payments (
        user_id BIGINT PRIMARY KEY, expected_amount DECIMAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS processed_tx (txid TEXT PRIMARY KEY)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS history (
        id SERIAL PRIMARY KEY, user_id BIGINT, chat_id BIGINT, amount INTEGER, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    cursor.close()
    conn.close()

# --- Permission Checks (Modified for Master Admin) ---
def is_admin(user_id):
    # แอดมินหลักไม่ต้องชำระเงินและไม่มีวันหมดอายุ
    if str(user_id) == str(MASTER_ADMIN): 
        return True
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT is_admin FROM paid_users WHERE user_id = %s AND expire_date > %s', (user_id, datetime.now()))
    res = cursor.fetchone()
    cursor.close()
    conn.close()
    return True if res else False

def is_group_allowed(chat_id, user_id):
    # ถ้าเป็นแอดมินหลัก ให้ใช้งานได้ทุกที่ทันที
    if str(user_id) == str(MASTER_ADMIN):
        return True
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM allowed_groups WHERE chat_id = %s AND expire_date > %s', (chat_id, datetime.now()))
    res = cursor.fetchone()
    cursor.close()
    conn.close()
    return True if res else False

# --- Web Dashboard & Bot Logic (ส่วนที่เหลือคงเดิม) ---
# ... (ก๊อปปี้ส่วน Flask และ Bot Handler จากเวอร์ชันก่อนหน้ามาวางได้เลยครับ) ...

async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id, user_id = update.effective_chat.id, update.message.from_user.id
    # ตรวจสอบสิทธิ์โดยให้สิทธิ์แอดมินหลักก่อนเสมอ
    if not is_group_allowed(chat_id, user_id) and not is_admin(user_id): 
        return 
    
    txt = update.message.text.strip()
    match = re.match(r'^([+-])(\d+)$', txt)
    if match:
        # ... (ส่วนประมวลผลตัวเลข +/- เหมือนเดิม) ...
        pass

if __name__ == '__main__':
    init_db()
    Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)), use_reloader=False)).start()
    bot = Application.builder().token(TOKEN).build()
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("check", check_payment))
    bot.add_handler(CommandHandler("open", open_group))
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    bot.run_polling()
