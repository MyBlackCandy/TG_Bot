import os
import re
import psycopg2
import random
import requests
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, redirect, session
from threading import Thread
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURATION ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')
WEB_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin1234')
MY_USDT_ADDR = os.getenv('USDT_ADDRESS')

# --- DATABASE UTILS ---
def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

# --- MASTER ADMIN COMMANDS ---

# 1. แต่งตั้ง Admin
async def promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    try:
        target_id = int(context.args[0])
        exp = datetime.now() + timedelta(days=30)
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO paid_users VALUES (%s, %s, TRUE) ON CONFLICT (user_id) DO UPDATE SET is_admin = TRUE, expire_date = %s', (target_id, exp, exp))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"👑 แต่งตั้ง User `{target_id}` เป็น Admin เรียบร้อย (30 วัน)")
    except: await update.message.reply_text("❌ รูปแบบ: /promote [User_ID]")

# 2. ลบสิทธิ์ Admin
async def demote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    try:
        target_id = int(context.args[0])
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('DELETE FROM paid_users WHERE user_id = %s', (target_id,))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"🚫 ลบสิทธิ์ User `{target_id}` เรียบร้อย")
    except: await update.message.reply_text("❌ รูปแบบ: /demote [User_ID]")

# 3. เพิ่มวันใช้งาน (บวกเพิ่มจากของเดิม)
async def add_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    try:
        target_id = int(context.args[0])
        days = int(context.args[1])
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('SELECT expire_date FROM paid_users WHERE user_id = %s', (target_id,))
        res = cursor.fetchone()
        base_time = res[0] if res and res[0] > datetime.now() else datetime.now()
        new_exp = base_time + timedelta(days=days)
        cursor.execute('INSERT INTO paid_users VALUES (%s, %s, TRUE) ON CONFLICT (user_id) DO UPDATE SET expire_date = %s', (target_id, new_exp, new_exp))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"⏳ เพิ่มเวลาให้ `{target_id}` อีก {days} วัน\n📅 หมดอายุ: {new_exp.strftime('%Y-%m-%d')}")
    except: await update.message.reply_text("❌ รูปแบบ: /add_time [User_ID] [จำนวนวัน]")

# --- การทำงานหลักอื่นๆ (คงเดิม) ---

if __name__ == '__main__':
    # ... (ส่วน init_db และ Flask เหมือนเดิม) ...
    bot = Application.builder().token(TOKEN).build()
    
    # คำสั่งสำหรับ Master Admin
    bot.add_handler(CommandHandler("promote", promote))
    bot.add_handler(CommandHandler("demote", demote))
    bot.add_handler(CommandHandler("add_time", add_time))
    
    # คำสั่งทั่วไป
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("open", open_group))
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    
    bot.run_polling()
