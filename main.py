import os
import re
import sys
import logging
import psycopg2
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ตั้งค่า Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
ADMIN_ID = os.getenv('ADMIN_ID') 

# --- จัดการฐานข้อมูล ---
def get_db_connection():
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # ตารางสมาชิก: เก็บ ID, สถานะ และ Username ล่าสุดไว้ดู
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY, 
        username TEXT, 
        is_paid BOOLEAN DEFAULT TRUE)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS history (
        id SERIAL PRIMARY KEY, user_id BIGINT, amount INTEGER, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    cursor.close()
    conn.close()

def update_user_info(user_id, username):
    """อัปเดต Username ล่าสุดในฐานข้อมูล"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''INSERT INTO users (user_id, username) VALUES (%s, %s) 
                      ON CONFLICT (user_id) DO UPDATE SET username = %s''', (user_id, username, username))
    conn.commit()
    cursor.close()
    conn.close()

def is_user_allowed(user_id):
    if str(user_id) == str(ADMIN_ID): return True
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT is_paid FROM users WHERE user_id = %s', (user_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result[0] if result else False

# --- ส่วนคำสั่งบอท ---

# [ADMIN] ดูรายชื่อผู้ใช้งานทั้งหมดที่ได้รับสิทธิ์
async def user_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(ADMIN_ID): return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username FROM users WHERE is_paid = TRUE')
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    
    if not rows:
        await update.message.reply_text("🌑 ยังไม่มีผู้ใช้งานในระบบ")
        return
        
    res = "👥 รายชื่อผู้ได้รับสิทธิ์:\n"
    for i, row in enumerate(rows, 1):
        res += f"{i}. {row[1] if row[1] else 'ไม่มีชื่อ'} (ID: `{row[0]}`)\n"
    await update.message.reply_text(res, parse_mode='Markdown')

async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    username = update.message.from_user.username
    
    # อัปเดตข้อมูลผู้ใช้ (เพื่อให้แอดมินเห็นชื่อล่าสุด)
    if is_user_allowed(user_id):
        update_user_info(user_id, username)
    else:
        await update.message.reply_text(f"⚠️ ❌ 仅限付费用户。\nID: `{user_id}`", parse_mode='Markdown')
        return

    # ... ส่วน Logic การคำนวณเดิม (เหมือนที่เคยเขียนไว้) ...
