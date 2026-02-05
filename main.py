import os
import re
import logging
import random
import requests
import psycopg2
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- ⚙️ 1. Configuration & Logging ---
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv('TOKEN')
MASTER_ADMIN = os.getenv('ADMIN_ID')
DATABASE_URL = os.getenv('DATABASE_URL')
# *** สำคัญ: ใส่เลขกระเป๋า USDT (TRC-20) ของคุณที่นี่ ***
MY_WALLET = "YOUR_TRON_WALLET_ADDRESS" 
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
TRONSCAN_API = "https://apilist.tronscan.org/api/token_trc20_transfer"

# --- 🔄 2. Database Connection ---
def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

async def get_role(uid, chat_id):
    if str(uid) == str(MASTER_ADMIN): return "master"
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM admins WHERE user_id = %s', (uid,))
    res = cursor.fetchone()
    if res and res[0] > datetime.utcnow():
        cursor.close(); conn.close(); return "admin"
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND chat_id = %s', (uid, chat_id))
    res_team = cursor.fetchone(); cursor.close(); conn.close()
    return "team" if res_team else None

# --- 📈 3. Accounting System (UI & Logic) ---
async def send_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, show_all=False):
    chat_id = update.effective_chat.id
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT timezone FROM chat_settings WHERE chat_id = %s", (chat_id,))
    res_tz = cursor.fetchone(); tz = res_tz[0] if res_tz else 0
    
    now_local = datetime.utcnow() + timedelta(hours=tz)
    today_str = now_local.strftime('%Y-%m-%d')
    
    cursor.execute("""
        SELECT amount, user_name, (timestamp + (%s || ' hours')::interval) as local_ts 
        FROM history WHERE chat_id = %s 
        AND TO_CHAR(timestamp + (%s || ' hours')::interval, 'YYYY-MM-DD') = %s 
        ORDER BY timestamp ASC
    """, (tz, chat_id, tz, today_str))
    
    rows = cursor.fetchall(); total = sum(r[0] for r in rows); count = len(rows)
    display_rows = rows if show_all else (rows[-6:] if count > 6 else rows)
    
    text = "```\n"
    text += f"{'#'.ljust(3)} {'时间'.ljust(5)} {'金额'.ljust(8)} {'姓名'}\n--------------------------\n"
    for i, r in enumerate(display_rows):
        idx = str((count - len(display_rows) + i + 1)).ljust(3)
        t_str = r[2].strftime('%H:%M').ljust(5)
        a_str = f"{'+' if r[0] > 0 else ''}{r[0]}".ljust(8)
        text += f"{idx} {t_str} {a_str} {r[1]}\n"
    text += "```"
    cursor.close(); conn.close()
    await update.message.reply_text(f"🍎 **今日账目 ({today_str})**\n{text}💰 **总额: `{total}`**", parse_mode='MarkdownV2')

# --- 💳 4. USDT Auto-Payment (TronScan) ---
async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    unique_amt = 10.0 + (random.randint(1, 999) / 1000.0) # สุ่มเศษ 3 ตำแหน่ง (เช่น 10.123)
    expire = datetime.utcnow() + timedelta(minutes=30)
    
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("INSERT INTO pending_payments (user_id, amount_expected, expire_at) VALUES (%s, %s, %s)", 
                   (uid, unique_amt, expire))
    conn.commit(); cursor.close(); conn.close()
    
    msg = (f"💳 **USDT-TRC20 支付订单**\n"
           f"━━━━━━━━━━━━━━━\n"
           f"请转账**精确金额** (含小数点):\n"
           f"💰 金额: `{unique_amt}` USDT\n"
           f"📍 地址: `{MY_WALLET}`\n"
           f"⏳ 有效期: 30 分钟\n"
           f"━━━━━━━━━━━━━━━\n"
           f"✅ 转账后系统将自动通过 TronScan 确认")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def payment_monitor(context: ContextTypes.DEFAULT_TYPE):
    params = {"limit": 30, "direction": "in", "relatedAddress": MY_WALLET, "token_address": USDT_CONTRACT}
    try:
        data = requests.get(TRONSCAN_API, params=params).json()
        for tx in data.get('token_transfers', []):
            amt = float(tx['quant']) / 1000000
            tx_h = tx['transaction_id']
            
            conn = get_db_connection(); cursor = conn.cursor()
            cursor.execute("SELECT id, user_id FROM pending_payments WHERE amount_expected = %s AND status = 'PENDING'", (amt,))
            order = cursor.fetchone()
            
            if order:
                oid, uid = order
                cursor.execute("UPDATE pending_payments SET status = 'SUCCESS', tx_hash = %s WHERE id = %s", (tx_h, oid))
                cursor.execute("SELECT expire_date FROM admins WHERE user_id = %s", (uid,))
                res = cursor.fetchone()
                start = max(res[0], datetime.utcnow()) if res else datetime.utcnow()
                new_exp = start + timedelta(days=30)
                
                if res: cursor.execute("UPDATE admins SET expire_date = %s WHERE user_id = %s", (new_exp, uid))
                else: cursor.execute("INSERT INTO admins (user_id, expire_date) VALUES (%s, %s)", (uid, new_exp))
                conn.commit()
                await context.bot.send_message(chat_id=uid, text=f"✅ 支付成功！已增加 30 天权限。\n📅 到期日: {new_exp.strftime('%Y-%m-%d')}")
            cursor.close(); conn.close()
    except: pass

# --- 👮 5. Admin & Team Management ---
async def add_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = await get_role(update.effective_user.id, update.effective_chat.id)
    if role not in ['master', 'admin']: return
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO team_members (member_id, chat_id, username) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", 
                       (target.id, update.effective_chat.id, target.first_name))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"✅ 已添加 {target.first_name} 为本群操作员")

# --- 📥 6. Message Handlers ---
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    chat_id, uid = update.effective_chat.id, update.effective_user.id
    text = update.message.text.strip(); match = re.match(r'^([+-])(\d+)$', text)
    
    if match:
        role = await get_role(uid, chat_id)
        if not role: return
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)", 
                       (chat_id, amt, update.message.from_user.first_name))
        conn.commit(); cursor.close(); conn.close()
        await send_summary(update, context)

# --- 🚀 7. Main Runner (Fixes Crashed issue) ---
def main():
    app = Application.builder().token(TOKEN).build()
    
    # Handlers
    app.add_handler(CommandHandler(["bot", "start"], send_summary))
    app.add_handler(CommandHandler("showall", lambda u, c: send_summary(u, c, show_all=True)))
    app.add_handler(CommandHandler("buy", buy_cmd))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("check", lambda u, c: u.message.reply_text(f"🆔 ID: `{u.effective_user.id}`")))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    
    # Background Job: ตรวจสอบ TronScan ทุก 60 วินาที
    app.job_queue.run_repeating(payment_monitor, interval=60, first=10)
    
    print("🚀 Black Candy Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()
