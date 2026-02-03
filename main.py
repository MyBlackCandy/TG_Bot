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

# ตั้งค่า Timezone จีน (CST - GMT+8)
CN_TZ = timezone(timedelta(hours=8))

def get_now_cn():
    """ดึงเวลาปัจจุบันของประเทศจีน"""
    return datetime.now(CN_TZ)

# --- 🗄️ DATABASE SYSTEM ---
def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection(); cursor = conn.cursor()
    # ตารางลูกค้าหลัก (มีฟิลด์เก็บชื่อและ Username)
    cursor.execute('''CREATE TABLE IF NOT EXISTS customers (
        user_id BIGINT PRIMARY KEY, 
        expire_date TIMESTAMP WITH TIME ZONE,
        username TEXT,
        first_name TEXT
    )''')
    # ตารางลูกทีม
    cursor.execute('CREATE TABLE IF NOT EXISTS team_members (member_id BIGINT PRIMARY KEY, leader_id BIGINT, allowed_chat_id BIGINT)')
    # ตารางประวัติบัญชี
    cursor.execute('CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, chat_id BIGINT, amount INTEGER, user_name TEXT, timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)')
    # ตารางป้องกัน TxID ซ้ำ
    cursor.execute('CREATE TABLE IF NOT EXISTS used_transactions (tx_id TEXT PRIMARY KEY, user_id BIGINT)')
    # ตารางรายการรอชำระเงิน
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

# --- 🔄 AUTO VERIFY (BLOCKCHAIN) ---
async def auto_verify_task(context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection(); cursor = conn.cursor()
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
                            try:
                                chat = await context.bot.get_chat(uid)
                                uname, fname = chat.username, chat.first_name
                            except:
                                uname, fname = None, "User"
                            
                            cursor.execute('INSERT INTO used_transactions VALUES (%s, %s)', (tx_id, uid))
                            cursor.execute('SELECT expire_date FROM customers WHERE user_id=%s', (uid,))
                            old = cursor.fetchone()
                            base = old[0] if old and old[0] > get_now_cn() else get_now_cn()
                            new_exp = base + timedelta(days=30)
                            
                            cursor.execute('''INSERT INTO customers (user_id, expire_date, username, first_name) VALUES (%s, %s, %s, %s) 
                                           ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date, username=EXCLUDED.username, first_name=EXCLUDED.first_name''', 
                                           (uid, new_exp, uname, fname))
                            cursor.execute('DELETE FROM pending_payments WHERE user_id=%s', (uid,))
                            conn.commit()
                            await context.bot.send_message(chat_id=uid, text=f"✅ **支付成功!** 到期时间 (CN): `{new_exp.strftime('%Y-%m-%d %H:%M')}`")
        cursor.close(); conn.close()
    except: pass

# --- 🤖 COMMAND HANDLERS ---

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
           "系统将自动秒入账。输入 /check 查看状态，输入 /help 查看指令。")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if str(uid) == str(MASTER_ADMIN):
        return await update.message.reply_text("👑 **身份: 系统主管理员**\n🌟 **状态: 永久有效**")
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (uid,))
    res = cursor.fetchone(); cursor.close(); conn.close()
    if res and res[0] > get_now_cn():
        exp_cn = res[0].astimezone(CN_TZ)
        await update.message.reply_text(f"✅ **您的权限状态: 正常**\n📅 **到期时间:** `{exp_cn.strftime('%Y-%m-%d %H:%M')}` (CN)")
    else:
        await update.message.reply_text("❌ **权限状态: 未激活**\n━━━━━━━━━━━━━━━━━━━━\n您目前没有使用权限。请私聊发送 /start 获取地址。")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_master = str(update.message.from_user.id) == str(MASTER_ADMIN)
    msg = (
        "📖 **黑糖果记账机器人 - 完整指南**\n━━━━━━━━━━━━━━━━━━━━\n"
        "📊 **1. 记账指令 (群内):** `+金额` / `-金额` \n"
        "📈 **2. 查看账单:** `/show` / `/undo` (撤销)\n"
        "👥 **3. 成员管理:** `/add` / `/remove` (回复人)\n"
        "💳 **4. 权限查询:** `/check` / `/id` \n"
    )
    if is_master:
        msg += "━━━━━━━━━━━━━━━━━━━━\n👑 **Admin Only:**\n• `/list` : 会员列表\n• `/setadmin [ID] [天]` : 开通\n• `/deladmin [ID]` : 彻底删除"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def list_customers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT user_id, expire_date, username, first_name FROM customers WHERE expire_date > %s ORDER BY expire_date ASC', (get_now_cn(),))
    rows = cursor.fetchall(); cursor.close(); conn.close()
    if not rows: return await update.message.reply_text("📋 **目前没有活跃会员**")
    msg = "👑 **活跃会员列表:**\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, row in enumerate(rows):
        uname = f"@{row[2]}" if row[2] else "无"
        msg += f"{i+1}. 👤 **{row[3]}** ({uname})\n   🆔: `{row[0]}` | 📅: `{row[1].astimezone(CN_TZ).strftime('%m-%d %H:%M')}`\n\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def del_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    try:
        uid = int(context.args[0])
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('DELETE FROM customers WHERE user_id = %s', (uid,))
        cursor.execute('DELETE FROM team_members WHERE leader_id = %s', (uid,))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"🗑 **已从数据库彻底删除 ID:** `{uid}`")
    except: await update.message.reply_text("格式: `/deladmin [ID]`")

async def set_admin_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    try:
        uid, days = int(context.args[0]), int(context.args[1])
        new_exp = get_now_cn() + timedelta(days=days)
        try:
            chat = await context.bot.get_chat(uid)
            uname, fname = chat.username, chat.first_name
        except: uname, fname = "Manual", "User"
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO customers VALUES (%s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date, username=EXCLUDED.username, first_name=EXCLUDED.first_name', (uid, new_exp, uname, fname))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"👑 **手动开通成功**\n👤: {fname} | 到期: `{new_exp.strftime('%Y-%m-%d')}`")
    except: await update.message.reply_text("格式: `/setadmin [ID] [天数]`")

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not check_access(update.message.from_user.id, chat_id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
    rows = cursor.fetchall(); cursor.close(); conn.close()
    if not rows: return await update.message.reply_text("📋 **当前无记录**")
    total, count = sum(r[0] for r in rows), len(rows)
    history_text = "...\n" + "\n".join([f"{count-4+i}. {('+' if r[0]>0 else '')}{r[0]} ({r[1]})" for i, r in enumerate(rows[-5:])]) if count > 6 else "\n".join([f"{i+1}. {('+' if r[0]>0 else '')}{r[0]} ({r[1]})" for i, r in enumerate(rows)])
    await update.message.reply_text(f"📊 **账目汇总**\n━━━━━━━━━━━━━━━\n{history_text}\n━━━━━━━━━━━━━━━\n💰 **总额: {total}**", parse_mode='Markdown')

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

# --- (Functions: get_my_id, undo, reset, add/remove_member omitted for brevity, but should be included) ---
async def get_my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg = f"🆔 **Telegram ID 信息**\n━━━━━━━━━━━━━━━\n👤 **用户:** {user.first_name}\n🔢 **User ID:** `{user.id}`\n"
    if chat.type != 'private': msg += f"🏰 **Chat ID:** `{chat.id}`\n"
    await update.message.reply_text(msg + "━━━━━━━━━━━━━━━\n💡 *长按 ID 可复制*", parse_mode='Markdown')

async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ **已撤销记录**")
    await show_history(update, context)

async def reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE chat_id = %s', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("🧹 **账目已清空**")

async def add_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return await update.message.reply_text("⚠️ 请回复成员以授权")
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    t = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO team_members VALUES (%s, %s, %s) ON CONFLICT (member_id) DO UPDATE SET allowed_chat_id=EXCLUDED.allowed_chat_id', (t.id, update.message.from_user.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"✅ **授权成功:** {t.first_name}")

async def remove_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return await update.message.reply_text("⚠️ 请回复成员以取消")
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    t = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (t.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"🚫 **已取消授权:** {t.first_name}")

# --- 🚀 RUN BOT ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    if app.job_queue: app.job_queue.run_repeating(auto_verify_task, interval=30, first=10)
    
    # Register Commands
    for cmd, func in [("start", start), ("help", help_command), ("check", check_status), ("id", get_my_id), 
                     ("show", show_history), ("undo", undo), ("reset", reset_history), ("add", add_member), 
                     ("remove", remove_member), ("list", list_customers), ("deladmin", del_admin), ("setadmin", set_admin_manual)]:
        app.add_handler(CommandHandler(cmd, func))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.run_polling()
