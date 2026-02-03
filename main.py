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
    if cursor.fetchone(): 
        cursor.close(); conn.close(); return True
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    res = cursor.fetchone(); cursor.close(); conn.close()
    return True if res else False

# --- 🤖 HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    amt = 100 + (random.randint(1, 99) / 100)
    exp = datetime.now() + timedelta(minutes=15)
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO pending_payments VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET amount=EXCLUDED.amount, expire_at=EXCLUDED.expire_at', (update.message.from_user.id, amt, exp))
    conn.commit(); cursor.close(); conn.close()
    msg = (f"🚀 **AK 机器人管理系统**\n━━━━━━━━━━━━━━━\n"
           f"💰 **金额/Amt:** `{amt:.2f}` USDT (TRC-20)\n"
           f"🏦 **地址/Addr:** `{MY_USDT_ADDR}`\n"
           f"⏰ **有效期/Expire:** 15 Min\n"
           "系统将自动激活。 / Auto-Verify enabled.")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📖 **双语指令指南 | Bilingual Guide**\n━━━━━━━━━━━━━━━\n"
        "👤 **通用 / General:**\n"
        "• `+金额/-金额` : 记账 | Record\n"
        "• `/check` (查询) : 到期时间 | Expiry\n"
        "• `/show` (账单) : 查看记录 | Show List\n"
        "• `/help` (帮助) : 帮助菜单 | Help\n\n"
        "👑 **组长 / Leader (Reply):**\n"
        "• `/add` (授权) : 授权成员 | Add Member\n"
        "• `/remove` (取消) : 取消授权 | Remove Member\n"
        "• `/undo` (撤回) : 撤销最后记录 | Undo\n"
        "• `/reset` (重置) : 清空群记录 | Reset Group"
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
    conn.commit()
    cursor.close(); conn.close()
    await show_history(update, context)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    # รองรับการบันทึกยอด +100 / -50
    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        if not check_access(update.message.from_user.id, chat_id): return
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', (chat_id, amt, update.message.from_user.first_name))
        conn.commit(); cursor.close(); conn.close()
        await show_history(update, context)
    # รองรับคำสั่งภาษาจีน (Chinese Command Alias)
    elif text.startswith('/'):
        cmd = text[1:]
        if cmd == '帮助': await help_command(update, context)
        elif cmd == '账单': await show_history(update, context)
        elif cmd == '撤回': await undo(update, context)
        # เพิ่มคำสั่งจีนอื่นๆ ได้ที่นี่

async def auto_verify_task(context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('SELECT user_id, amount FROM pending_payments WHERE expire_at > NOW()')
        pending = cursor.fetchall()
        if pending:
            url = f"https://api.trongrid.io/v1/accounts/{MY_USDT_ADDR}/transactions/trc20"
            data = requests.get(url, params={"limit": 20}, headers={"TRON-PRO-API-KEY": TRON_API_KEY} if TRON_API_KEY else {}).json()
            for uid, amt in pending:
                for tx in data.get('data', []):
                    if abs((int(tx['value'])/1000000) - float(amt)) < 0.0001:
                        tx_id = tx['transaction_id']
                        cursor.execute('SELECT 1 FROM used_transactions WHERE tx_id=%s', (tx_id,))
                        if not cursor.fetchone():
                            cursor.execute('INSERT INTO used_transactions VALUES (%s, %s)', (tx_id, uid))
                            cursor.execute('SELECT expire_date FROM customers WHERE user_id=%s', (uid,))
                            old = cursor.fetchone()
                            new_exp = (old[0] if old and old[0] > datetime.now() else datetime.now()) + timedelta(days=30)
                            cursor.execute('INSERT INTO customers VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date', (uid, new_exp))
                            cursor.execute('DELETE FROM pending_payments WHERE user_id=%s', (uid,))
                            conn.commit()
                            await context.bot.send_message(chat_id=uid, text=f"✅ **支付成功 / Success!**\nExpiry: `{new_exp.strftime('%Y-%m-%d %H:%M')}`")
        cursor.close(); conn.close()
    except: pass

if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    if app.job_queue: app.job_queue.run_repeating(auto_verify_task, interval=30, first=10)
    
    # ลงทะเบียนคำสั่งภาษาอังกฤษ (Standard)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("show", show_history))
    app.add_handler(CommandHandler("undo", undo))
    # MessageHandler ตัวเดียวรองรับทั้งการบันทึกเงินและคำสั่งภาษาจีน
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    # เพิ่ม MessageHandler พิเศษสำหรับจับคำสั่งที่ขึ้นต้นด้วย / ที่เป็นภาษาจีน
    app.add_handler(MessageHandler(filters.Regex(r'^/(帮助|账单|撤回|查询|授权|取消|重置)'), handle_text))
    
    app.run_polling()
