import os
import re
import psycopg2
import requests
import random
import asyncio
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- ⚙️ CONFIG ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')
MY_USDT_ADDR = os.getenv('USDT_ADDRESS')
TRON_API_KEY = os.getenv('TRONGRID_API_KEY')

# --- 🗄️ DATABASE & ACCESS ---
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

# --- 🤖 HANDLERS (English Commands Only) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    amt = 100 + (random.randint(1, 99) / 100)
    exp = datetime.now() + timedelta(minutes=15)
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO pending_payments VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET amount=EXCLUDED.amount, expire_at=EXCLUDED.expire_at', (update.message.from_user.id, amt, exp))
    conn.commit(); cursor.close(); conn.close()
    
    msg = (f"🚀 **黑糖果记账机器人**\n━━━━━━━━━━━━━━━\n"
           f"💰 **金额:** `{amt:.2f}` USDT (TRC-20)\n"
           f"🏦 **地址:** `{MY_USDT_ADDR}`\n"
           f"⏰ **有效期:** 15 分钟\n"
           "系统将自动激活。.\n"
           "使用方式：`/help`"
          )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📖 **黑糖果机器人详细使用指南**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 **1. 日常记账 (群组内)**\n"
        "• 记录收入: `+1000` | 支出: `-500` \n"
        "• 查看账单: `/show` \n"
        "• 撤销错误: `/undo` \n\n"
        "👑 **2. 组长管理 **\n"
        "• 授权成员: 先让组员发信息到群里，然后输入`/add`来回复组员信息\n"
        "• 取消授权: 先让组员发信息到群里，然后输入`/remove`来回复组员信息\n"
        "• 清空账目: `/reset` \n\n"
        "💳 **3. 权限查询**\n"
        "• 查询到期: `/check` \n\n"
        "🛠 **Admin:** `/setadmin [ID] [Days]`"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not check_access(update.message.from_user.id, chat_id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
    rows = cursor.fetchall(); cursor.close(); conn.close()
    if not rows: return await update.message.reply_text("📋 **当前无记录 / No Records**")
    
    total = sum(r[0] for r in rows)
    count = len(rows)
    # ระบบย่อรายการ (มากกว่า 6 รายการ)
    if count > 6:
        display = rows[-5:]
        history_text = "...\n" + "\n".join([f"{count-4+i}. {('+' if r[0]>0 else '')}{r[0]} ({r[1]})" for i, r in enumerate(display)])
    else:
        history_text = "\n".join([f"{i+1}. {('+' if r[0]>0 else '')}{r[0]} ({r[1]})" for i, r in enumerate(rows)])
        
    await update.message.reply_text(f"📊 **账目汇总 / Summary**\n━━━━━━━━━━━━━━━\n{history_text}\n━━━━━━━━━━━━━━━\n💰 **总金额/Total: {total}**", parse_mode='Markdown')

async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not check_access(update.message.from_user.id, chat_id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)', (chat_id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ **已撤回最后一条记录 / Undo Done**")
    await show_history(update, context)

# --- 🚀 RUN BOT ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    
    # ลงทะเบียนเฉพาะคำสั่งภาษาอังกฤษ
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(CommandHandler("show", show_history))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("remove", remove_member))
    app.add_handler(CommandHandler("reset", reset_history))
    app.add_handler(CommandHandler("undo", undo))
    app.add_handler(CommandHandler("setadmin", set_admin_manual))
    
    # ระบบคำนวณเงิน
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    
    app.run_polling()
