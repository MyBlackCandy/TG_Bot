import os
import re
import psycopg2
import requests
import random
import asyncio
# เพิ่มโมดูล timezone
from datetime import datetime, timedelta, timezone
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- ⚙️ CONFIG ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')
MY_USDT_ADDR = os.getenv('USDT_ADDRESS')
TRON_API_KEY = os.getenv('TRONGRID_API_KEY')

# ตั้งค่า Timezone ประเทศจีน (CST - GMT+8)
CN_TZ = timezone(timedelta(hours=8))

def get_now_cn():
    """ฟังก์ชันดึงเวลาปัจจุบันของจีน"""
    return datetime.now(CN_TZ)

# --- 🗄️ DATABASE & ACCESS ---
def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS customers (user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP WITH TIME ZONE)')
    cursor.execute('CREATE TABLE IF NOT EXISTS team_members (member_id BIGINT PRIMARY KEY, leader_id BIGINT, allowed_chat_id BIGINT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, chat_id BIGINT, amount INTEGER, user_name TEXT, timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)')
    cursor.execute('CREATE TABLE IF NOT EXISTS used_transactions (tx_id TEXT PRIMARY KEY, user_id BIGINT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS pending_payments (user_id BIGINT PRIMARY KEY, amount DECIMAL, expire_at TIMESTAMP WITH TIME ZONE)')
    conn.commit(); cursor.close(); conn.close()

def check_access(user_id, chat_id):
    if str(user_id) == str(MASTER_ADMIN): return True
    conn = get_db_connection(); cursor = conn.cursor()
    # ตรวจสอบโดยใช้เวลาปัจจุบันของจีน
    cursor.execute('SELECT 1 FROM customers WHERE user_id = %s AND expire_date > %s', (user_id, get_now_cn()))
    is_cust = cursor.fetchone()
    cursor.close(); conn.close()
    if is_cust: return True
    
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    res = cursor.fetchone(); cursor.close(); conn.close()
    return True if res else False

# --- 🔄 AUTO VERIFY TASK ---
async def auto_verify_task(context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        # เช็ครายการที่ยังไม่หมดอายุตามเวลาจีน
        cursor.execute('SELECT user_id, amount FROM pending_payments WHERE expire_at > %s', (get_now_cn(),))
        pending = cursor.fetchall()
        if pending:
            url = f"https://api.trongrid.io/v1/accounts/{MY_USDT_ADDR}/transactions/trc20"
            headers = {"TRON-PRO-API-KEY": TRON_API_KEY} if TRON_API_KEY else {}
            data = requests.get(url, params={"limit": 20}, headers=headers).json()
            for uid, amt in pending:
                for tx in data.get('data', []):
                    if abs((int(tx['value'])/1000000) - float(amt)) < 0.0001:
                        tx_id = tx['transaction_id']
                        cursor.execute('SELECT 1 FROM used_transactions WHERE tx_id=%s', (tx_id,))
                        if not cursor.fetchone():
                            cursor.execute('INSERT INTO used_transactions VALUES (%s, %s)', (tx_id, uid))
                            cursor.execute('SELECT expire_date FROM customers WHERE user_id=%s', (uid,))
                            old = cursor.fetchone()
                            
                            # คำนวณวันหมดอายุใหม่ (เวลาจีน)
                            current_now = get_now_cn()
                            base_date = old[0] if old and old[0] > current_now else current_now
                            new_exp = base_date + timedelta(days=30)
                            
                            cursor.execute('INSERT INTO customers VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date', (uid, new_exp))
                            cursor.execute('DELETE FROM pending_payments WHERE user_id=%s', (uid,))
                            conn.commit()
                            await context.bot.send_message(chat_id=uid, text=f"✅ **支付成功 / Success!**\n到期时间 (北京时间): `{new_exp.strftime('%Y-%m-%d %H:%M')}`")
        cursor.close(); conn.close()
    except: pass

# --- 🤖 HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    amt = 100 + (random.randint(1, 99) / 100)
    # หมดอายุใน 15 นาที (เวลาจีน)
    exp = get_now_cn() + timedelta(minutes=15)
    
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO pending_payments VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET amount=EXCLUDED.amount, expire_at=EXCLUDED.expire_at', (update.message.from_user.id, amt, exp))
    conn.commit(); cursor.close(); conn.close()
    
    msg = (
        f"🚀 **黑糖果机器人管理系统**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💳 **权限激活 (续费/开通):**\n"
        f"• **金额:** `{amt:.2f}` USDT (TRC-20)\n"
        f"• **地址:** `{MY_USDT_ADDR}`\n"
        f"• **有效期至:** `{exp.strftime('%H:%M')}` (北京时间)\n\n"
        f"• **查询状态:** `/check` \n\n"
        f"📖 **使用方法简述:**\n"
        f"1️⃣ **记账:** 直接发送 `+100` 或 `-50` \n"
        f"2️⃣ **查询:** 输入 `/show` \n"
        f"3️⃣ **授权:** 回复成员并输入 `/add` \n\n"
        f"4️⃣ **帮助:** 输入 `/help` 查看所有详细指令\n\n"
        f"🆔 **您的 ID:** `{update.message.from_user.id}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ *请务必精准转账，包含小数点，系统将自动识别。*"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if str(uid) == str(MASTER_ADMIN):
        return await update.message.reply_text("👑 **身份: 主管理员 (永久有效)**")
    
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (uid,))
    res = cursor.fetchone(); cursor.close(); conn.close()
    
    if res and res[0] > get_now_cn():
        # แสดงเวลาหมดอายุเป็นเวลาจีน
        exp_cn = res[0].astimezone(CN_TZ)
        await update.message.reply_text(f"✅ **状态: 正常 / Active**\n📅 **到期时间:** `{exp_cn.strftime('%Y-%m-%d %H:%M')}` (北京时间)")
    else: 
        await update.message.reply_text("❌ **权限已过期 / Unauthorized**")

# ฟังก์ชันอื่นๆ (show_history, handle_calc, add_member, remove_member, undo, reset, setadmin) 
# ให้ใช้ get_now_cn() และ astimezone(CN_TZ) ในลักษณะเดียวกัน

async def set_admin_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    try:
        uid, days = int(context.args[0]), int(context.args[1])
        new_exp = get_now_cn() + timedelta(days=days)
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO customers VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date', (uid, new_exp))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"👑 **手动授权成功**\nID: `{uid}`\n到期时间: `{new_exp.strftime('%Y-%m-%d %H:%M')}` (CN)")
    except: await update.message.reply_text("Format: `/setadmin [ID] [Days]`")

# --- 🚀 RUN BOT (คงส่วนเดิมของคุณไว้) ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    if app.job_queue:
        app.job_queue.run_repeating(auto_verify_task, interval=30, first=10)
    
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
