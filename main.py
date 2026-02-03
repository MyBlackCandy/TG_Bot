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
    # เพิ่มตารางเก็บ log การใช้งานเพื่อความละเอียด
    cursor.execute('CREATE TABLE IF NOT EXISTS customers (user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP)')
    cursor.execute('CREATE TABLE IF NOT EXISTS team_members (member_id BIGINT PRIMARY KEY, leader_id BIGINT, allowed_chat_id BIGINT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, chat_id BIGINT, amount INTEGER, user_name TEXT, user_id BIGINT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cursor.execute('CREATE TABLE IF NOT EXISTS used_transactions (tx_id TEXT PRIMARY KEY, user_id BIGINT, amount DECIMAL, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
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

# --- 🔄 AUTO VERIFY (ละเอียดขึ้น: แจ้งยอดจริงที่เข้า) ---
async def auto_verify_task(context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('SELECT user_id, amount FROM pending_payments WHERE expire_at > NOW()')
        pending = cursor.fetchall()
        if pending:
            url = f"https://api.trongrid.io/v1/accounts/{MY_USDT_ADDR}/transactions/trc20"
            headers = {"TRON-PRO-API-KEY": TRON_API_KEY} if TRON_API_KEY else {}
            data = requests.get(url, params={"limit": 20}, headers=headers).json()
            for uid, amt in pending:
                for tx in data.get('data', []):
                    tx_amount = int(tx['value'])/1000000
                    if abs(tx_amount - float(amt)) < 0.0001:
                        tx_id = tx['transaction_id']
                        cursor.execute('SELECT 1 FROM used_transactions WHERE tx_id=%s', (tx_id,))
                        if not cursor.fetchone():
                            cursor.execute('INSERT INTO used_transactions (tx_id, user_id, amount) VALUES (%s, %s, %s)', (tx_id, uid, tx_amount))
                            cursor.execute('SELECT expire_date FROM customers WHERE user_id=%s', (uid,))
                            old = cursor.fetchone()
                            new_exp = (old[0] if old and old[0] > datetime.now() else datetime.now()) + timedelta(days=30)
                            cursor.execute('INSERT INTO customers VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date', (uid, new_exp))
                            cursor.execute('DELETE FROM pending_payments WHERE user_id=%s', (uid,))
                            conn.commit()
                            
                            # แจ้งลูกค้าละเอียดขึ้น
                            success_msg = (
                                "✅ **支付成功 | Payment Confirmed**\n"
                                "━━━━━━━━━━━━━━━\n"
                                f"💰 **入账金额:** `{tx_amount:.2f}` USDT\n"
                                f"📅 **到期时间:** `{new_exp.strftime('%Y-%m-%d %H:%M')}`\n"
                                "🚀 您现在可以在群组中管理成员和账目了。"
                            )
                            await context.bot.send_message(chat_id=uid, text=success_msg, parse_mode='Markdown')
                            if MASTER_ADMIN:
                                await context.bot.send_message(chat_id=MASTER_ADMIN, text=f"💰 **收款通知:** ID `{uid}` 成功支付 `{tx_amount:.2f}` USDT")
        cursor.close(); conn.close()
    except Exception as e: print(f"Error: {e}")

# --- 🤖 HANDLERS (ปรับปรุง UI ให้ละเอียดขึ้น) ---

async def get_my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg = (
        "🆔 **Telegram 详细身份信息**\n"
        "━━━━━━━━━━━━━━━\n"
        f"👤 **用户姓名:** `{user.first_name}`\n"
        f"🏷 **用户名:** @{user.username if user.username else '未设置'}\n"
        f"🔢 **用户 ID:** `{user.id}` (长按复制)\n"
    )
    if chat.type != 'private':
        msg += f"🏰 **群组名称:** `{chat.title}`\n"
        msg += f"🏟 **群组 ID:** `{chat.id}`\n"
    msg += "━━━━━━━━━━━━━━━"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if str(uid) == str(MASTER_ADMIN):
        return await update.message.reply_text("👑 **身份: 系统主管理员**\n🌟 **权限状态: 永久有效 (Lifetime)**")
    
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (uid,))
    res = cursor.fetchone(); cursor.close(); conn.close()
    
    if res:
        days_left = (res[0] - datetime.now()).days
        status = "✅ 正常" if res[0] > datetime.now() else "❌ 已过期"
        msg = (
            "📊 **您的权限详细状态**\n"
            "━━━━━━━━━━━━━━━\n"
            f"👤 **用户 ID:** `{uid}`\n"
            f"🛡 **当前状态:** {status}\n"
            f"📅 **到期时间:** `{res[0].strftime('%Y-%m-%d %H:%M')}`\n"
            f"⏳ **剩余天数:** `{max(0, days_left)}` 天\n"
            "━━━━━━━━━━━━━━━"
        )
        await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ **未查询到您的权限记录**\n请在私聊中输入 /start 进行开通。")

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not check_access(update.message.from_user.id, chat_id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT amount, user_name, timestamp FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
    rows = cursor.fetchall(); cursor.close(); conn.close()
    
    if not rows: return await update.message.reply_text("📋 **当前账目为空**")
    
    total = sum(r[0] for r in rows)
    count = len(rows)
    # แสดงเวลาสั้นๆ ต่อท้ายชื่อเพื่อความละเอียด
    def format_row(i, r, total_count):
        time_str = r[2].strftime('%H:%M')
        return f"{i}. {('+' if r[0]>0 else '')}{r[0]} ({r[1]} | {time_str})"

    if count > 6:
        display = rows[-5:]
        history_text = "...\n" + "\n".join([format_row(count-4+i, r, count) for i, r in enumerate(display)])
    else:
        history_text = "\n".join([format_row(i+1, r, count) for i, r in enumerate(rows)])
        
    res = (
        f"📊 **群组账目汇总 | {update.effective_chat.title}**\n"
        "━━━━━━━━━━━━━━━\n"
        f"{history_text}\n"
        "━━━━━━━━━━━━━━━\n"
        f"📈 **总笔数:** {count} | 💰 **总金额: {total}**"
    )
    await update.message.reply_text(res, parse_mode='Markdown')

# --- RUN BOT ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    if app.job_queue: app.job_queue.run_repeating(auto_verify_task, interval=30, first=10)
    
    # Handlers (เหมือนเดิมแต่เพิ่มความละเอียด)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(CommandHandler("id", get_my_id))
    app.add_handler(CommandHandler("show", show_history))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("remove", remove_member))
    app.add_handler(CommandHandler("reset", reset_history))
    app.add_handler(CommandHandler("undo", undo))
    app.add_handler(CommandHandler("setadmin", set_admin_manual))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    
    app.run_polling()
