import os
import re
import psycopg2
import requests
import random
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIG ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')
MY_USDT_ADDR = os.getenv('USDT_ADDRESS')
TRON_API_KEY = os.getenv('TRONGRID_API_KEY')

def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

# --- 1. [ภาษาจีน] คำสั่ง /start ในแชทส่วนตัว ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    
    # สุ่มทศนิยม 100.01 - 100.99
    amt = 100 + (random.randint(1, 99) / 100)
    exp = datetime.now() + timedelta(minutes=15)

    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('''INSERT INTO pending_payments (user_id, amount, expire_at) 
                      VALUES (%s, %s, %s) ON CONFLICT (user_id) 
                      DO UPDATE SET amount = EXCLUDED.amount, expire_at = EXCLUDED.expire_at''', 
                   (update.message.from_user.id, amt, exp))
    conn.commit(); cursor.close(); conn.close()

    msg = (
        "🚀 **欢迎使用 AK 机器人管理系统**\n"
        "----------------------------------\n"
        "💰 **付费开通/续费组长权限:**\n"
        f"• 应付金额: `{amt:.2f}` USDT (TRC-20)\n"
        f"• 收款地址: `{MY_USDT_ADDR}`\n"
        f"• 有效期: 15 分钟内 (至 {exp.strftime('%H:%M')})\n"
        "*(📢 注意：转账金额必须包含精准的小数部分)*\n\n"
        "----------------------------------\n"
        "📖 **详细使用教程:**\n\n"
        "1️⃣ **激活权限:** 转账后等待1分钟，输入 /verify 自动开通30天权限。\n"
        "2️⃣ **管理组员:** 在群组中 **回复(Reply)** 组员消息并输入 `/add` 授权。\n"
        "3️⃣ **快捷记账:** 直接发送 `+金额` 或 `-金额` (例如: +500)。\n"
        "4️⃣ **撤回错误:** 发送 `/undo` 撤销最后一条记录。\n"
        "5️⃣ **数据重置:** 组长发送 `/reset` 可清空全群账目。\n\n"
        "⚠️ 权限到期后机器人将自动退出服务，请及时续费。"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- 2. [ภาษาจีน] คำสั่ง /verify ยืนยันยอดโอน ---
async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT amount, expire_at FROM pending_payments WHERE user_id = %s', (user.id,))
    res = cursor.fetchone()

    if not res:
        await update.message.reply_text("❌ 未找到有效订单，请输入 /start 重新开始。")
        return
    
    if datetime.now() > res[1]:
        await update.message.reply_text("⏰ 订单已超时，请重新输入 /start。")
        return

    await update.message.reply_text("🔍 正在查询区块链确认，请稍候...")
    
    # ตรวจสอบ Blockchain (TRC-20)
    found = False
    url = f"https://api.trongrid.io/v1/accounts/{MY_USDT_ADDR}/transactions/trc20"
    params = {"limit": 20, "contract_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"}
    headers = {"TRON-PRO-API-KEY": TRON_API_KEY} if TRON_API_KEY else {}
    
    try:
        data = requests.get(url, params=params, headers=headers).json()
        for tx in data.get('data', []):
            tx_amt = int(tx['value']) / 1_000_000
            if abs(tx_amt - float(res[0])) < 0.0001:
                tx_id = tx['transaction_id']
                cursor.execute('SELECT 1 FROM used_transactions WHERE tx_id = %s', (tx_id,))
                if not cursor.fetchone():
                    cursor.execute('INSERT INTO used_transactions VALUES (%s, %s)', (tx_id, user.id))
                    found = True; break
    except: pass

    if found:
        cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (user.id,))
        old = cursor.fetchone()
        new_exp = (old[0] if old and old[0] > datetime.now() else datetime.now()) + timedelta(days=30)
        cursor.execute('INSERT INTO customers VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date', (user.id, new_exp))
        cursor.execute('DELETE FROM pending_payments WHERE user_id = %s', (user.id,))
        conn.commit()
        await update.message.reply_text(f"✅ **支付成功！**\n组长权限已开通至: {new_exp.strftime('%Y-%m-%d %H:%M')}")
        if MASTER_ADMIN:
            await context.bot.send_message(chat_id=MASTER_ADMIN, text=f"💰 **新订单已支付!**\n👤 {user.first_name}\n🏷 @{user.username}")
    else:
        await update.message.reply_text(f"❌ 未检测到 `{res[0]:.2f}` USDT 入账，请确认金额是否正确。")
    
    cursor.close(); conn.close()

# --- ส่วนจัดการบอทเข้ากลุ่ม ---
async def track_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for m in update.message.new_chat_members:
        if m.id == context.bot.id:
            u = update.message.from_user
            if MASTER_ADMIN:
                await context.bot.send_message(chat_id=MASTER_ADMIN, text=f"🤖 **机器进入新群组!**\n🏰 `{update.effective_chat.title}`\n👤 操作者: {u.first_name} (@{u.username})")

if __name__ == '__main__':
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, track_chat))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("verify", verify))
    # ... handler อื่นๆ (add, undo, handle_calc) ตามโค้ดเดิม ...
    app.run_polling()
