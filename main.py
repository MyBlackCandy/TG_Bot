import os
import re
import psycopg2
import requests
import random
import asyncio
from datetime import datetime, timedelta, timezone
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- ⚙️ CONFIGURATION ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')
MY_USDT_ADDR = os.getenv('USDT_ADDRESS')
TRON_API_KEY = os.getenv('TRONGRID_API_KEY')

# ตั้งค่า Timezone จีน (CST - GMT+8) ให้เป็น Aware object
CN_TZ = timezone(timedelta(hours=8))

def get_now_cn():
    """ดึงเวลาปัจจุบันพร้อมโซนเวลาจีนเสมอ เพื่อป้องกัน TypeError"""
    return datetime.now(CN_TZ)

# --- 🗄️ DATABASE SYSTEM ---
def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS customers (
        user_id BIGINT PRIMARY KEY, 
        expire_date TIMESTAMP WITH TIME ZONE,
        username TEXT,
        first_name TEXT
    )''')
    cursor.execute('CREATE TABLE IF NOT EXISTS team_members (member_id BIGINT PRIMARY KEY, leader_id BIGINT, allowed_chat_id BIGINT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, chat_id BIGINT, amount INTEGER, user_name TEXT, timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)')
    cursor.execute('CREATE TABLE IF NOT EXISTS used_transactions (tx_id TEXT PRIMARY KEY, user_id BIGINT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS pending_payments (user_id BIGINT PRIMARY KEY, amount DECIMAL, expire_at TIMESTAMP WITH TIME ZONE)')
    conn.commit(); cursor.close(); conn.close()

def check_access(user_id, chat_id):
    if str(user_id) == str(MASTER_ADMIN): return True
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM customers WHERE user_id = %s AND expire_date > %s', (user_id, get_now_cn()))
    is_cust = cursor.fetchone()
    if is_cust: 
        cursor.close(); conn.close(); return True
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    res = cursor.fetchone(); cursor.close(); conn.close()
    return True if res else False

# --- 🤖 HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    amt = 100 + (random.randint(1, 99) / 100)
    exp = get_now_cn() + timedelta(minutes=15)
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO pending_payments VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET amount=EXCLUDED.amount, expire_at=EXCLUDED.expire_at', (update.message.from_user.id, amt, exp))
    conn.commit(); cursor.close(); conn.close()
    msg = (f"🚀 **黑糖果机器人管理系统**\n━━━━━━━━━━━━━━━\n"
           f"💳 **权限激活 (USDT-TRC20):**\n"
           f"• **金额:** `{amt:.2f}` USDT\n"
           f"• **地址:** `{MY_USDT_ADDR}`\n"
           f"• **有效期:** 15 分钟 (至 {exp.strftime('%H:%M')})\n"
           "输入 /check 确认状态。")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if str(uid) == str(MASTER_ADMIN):
        return await update.message.reply_text("👑 **身份: 系统主管理员**\n🌟 **状态: 永久有效**")
    
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (uid,))
    res = cursor.fetchone(); cursor.close(); conn.close()
    
    # แก้ไขจุด Crash: บังคับให้การเปรียบเทียบเป็น Aware ทั้งคู่
    if res and res[0]:
        db_time = res[0]
        if db_time.tzinfo is None: db_time = db_time.replace(tzinfo=CN_TZ)
        if db_time > get_now_cn():
            exp_cn = db_time.astimezone(CN_TZ)
            await update.message.reply_text(f"✅ **状态: 正常**\n📅 **到期:** `{exp_cn.strftime('%Y-%m-%d %H:%M')}` (CN)")
            return
    await update.message.reply_text("❌ **权限未激活**\n请私聊 /start 获取支付地址。")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (

        "📖 **黑糖果记账机器人 - 完整使用指南**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 **1. 群组记账指令 (Daily Accounting)**\n"
        "• **记录收入:** 直接输入 `+金额` (例: `+1000`)\n"
        "• **记录支出:** 直接输入 `-金额` (例: `-500`)\n"
        "• **查看账单:** 输入 `/show` (显示最近5条记录及总额)\n"
        "• **撤销记录:** 输入 `/undo` (删除最后一条错误记录)\n"
        "• **清空记录:** 输入 `/reset` (⚠️ 慎用！将清空全群账目)\n\n"
        
        "👥 **2. 成员管理 (Group Management)**\n"
        "**组长需通过回复(Reply)成员消息来操作:**\n"
        "• **授权成员:** 回复成员消息 + `/add` \n"
        "• **取消授权:** 回复成员消息 + `/remove` \n"

       "💳 **3. 个人权限与工具 (Status & Tools)**\n"
        "• **查询到期:** 输入 `/check` 查看权限剩余时间\n"
        "• **查询 ID:** 输入 `/id` 获取用户和群组的 ID\n"
        "• **开通权限:** 私聊发送 `/start` 获取付款地址\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        
        "💡 **温馨提示:** \n"
        "1. 系统采用 **GMT+8 北京时间** 进行计算。\n"
        "2. 转账请务必包含 **精准小数点金额**，系统将自动秒入账，无需截图。"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not check_access(update.message.from_user.id, chat_id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
    rows = cursor.fetchall(); cursor.close(); conn.close()
    if not rows: return await update.message.reply_text("📋 **当前无记录**")
    total = sum(r[0] for r in rows)
    count = len(rows)
    history_text = "\n".join([f"{i+1}. {('+' if r[0]>0 else '')}{r[0]} ({r[1]})" for i, r in enumerate(rows[-5:])])
    await update.message.reply_text(f"📊 **汇总** (最近5条)\n━━━━━━━━━━━━━━━\n{history_text}\n━━━━━━━━━━━━━━━\n💰 **总额: {total}**", parse_mode='Markdown')

async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ **已撤销最后一条记录**")
    await show_history(update, context)

async def reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE chat_id = %s', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("🧹 **已清空所有账目**")

async def get_my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, chat = update.effective_user, update.effective_chat
    msg = f"🆔 **ID 信息**\n👤: {user.first_name}\n🔢: `{user.id}`\n"
    if chat.type != 'private': msg += f"🏰 Chat: `{chat.id}`"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        if not check_access(update.message.from_user.id, update.effective_chat.id): return
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', (update.effective_chat.id, amt, update.message.from_user.first_name))
        conn.commit(); cursor.close(); conn.close()
        await show_history(update, context)

# --- 🚀 RUN BOT ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    
    # Register Commands
    handlers = [
        ("start", start), ("help", help_command), ("check", check_status),
        ("id", get_my_id), ("show", show_history), ("undo", undo),
        ("reset", reset_history), ("add", add_member), ("remove", remove_member),
        ("list", list_customers), ("deladmin", del_admin), ("setadmin", set_admin_manual)
    ]
    for cmd, func in handlers: app.add_handler(CommandHandler(cmd, func))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    
    print("Bot is running...")
    app.run_polling()
