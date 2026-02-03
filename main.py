import os
import re
import psycopg2
import requests
import random
import asyncio
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

# --- [ใหม่] ฟังก์ชันเช็คสิทธิ์และวันหมดอายุ ---
async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (user_id,))
    res = cursor.fetchone()
    cursor.close(); conn.close()

    if res:
        expire_date = res[0]
        if expire_date > datetime.now():
            await update.message.reply_text(
                f"✅ **您的权限状态: 有效**\n📅 **到期时间:** `{expire_date.strftime('%Y-%m-%d %H:%M')}`\n\n"
                "如果您需要延长权限，请在私聊中输入 /start 获取新的转账单。", parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ **您的权限已过期**\n请在私聊中输入 /start 重新续费。")
    else:
        await update.message.reply_text("❓ **您目前没有组长权限**\n请私聊机器人并输入 /start 开通权限。")

# --- [ใหม่] ระบบตรวจสอบยอดอัตโนมัติ (ไม่ต้องรอ /verify) ---
async def auto_verify_task(context: ContextTypes.DEFAULT_TYPE):
    """ฟังก์ชันวนลูปตรวจสอบ Blockchain อัตโนมัติทุก 30 วินาที"""
    while True:
        try:
            conn = get_db_connection(); cursor = conn.cursor()
            cursor.execute('SELECT user_id, amount, expire_at FROM pending_payments WHERE expire_at > NOW()')
            pending_list = cursor.fetchall()

            if pending_list:
                # ดึงข้อมูลธุรกรรมล่าสุดจาก Blockchain
                url = f"https://api.trongrid.io/v1/accounts/{MY_USDT_ADDR}/transactions/trc20"
                params = {"limit": 20, "contract_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"}
                headers = {"TRON-PRO-API-KEY": TRON_API_KEY} if TRON_API_KEY else {}
                response = requests.get(url, params=params, headers=headers).json()
                
                for user_id, expected_amount, expire_at in pending_list:
                    for tx in response.get('data', []):
                        tx_amt = int(tx['value']) / 1_000_000
                        if abs(tx_amt - float(expected_amount)) < 0.0001:
                            tx_id = tx['transaction_id']
                            # เช็คว่า TXID นี้ใช้ไปหรือยัง
                            cursor.execute('SELECT 1 FROM used_transactions WHERE tx_id = %s', (tx_id,))
                            if not cursor.fetchone():
                                # พบรายการโอนที่ถูกต้อง! ทำการเปิดสิทธิ์
                                cursor.execute('INSERT INTO used_transactions VALUES (%s, %s)', (tx_id, user_id))
                                cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (user_id,))
                                old = cursor.fetchone()
                                new_exp = (old[0] if old and old[0] > datetime.now() else datetime.now()) + timedelta(days=30)
                                
                                cursor.execute('INSERT INTO customers VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date', (user_id, new_exp))
                                cursor.execute('DELETE FROM pending_payments WHERE user_id = %s', (user_id,))
                                conn.commit()

                                # แจ้งเตือนลูกค้าอัตโนมัติ
                                await context.bot.send_message(
                                    chat_id=user_id,
                                    text=f"✅ **支付成功！系统已自动确认**\n您的组长权限已开通/续费。\n📅 **有效期至:** `{new_exp.strftime('%Y-%m-%d %H:%M')}`\n\n您可以开始使用机器人管理您的群组了！",
                                    parse_mode='Markdown'
                                )
                                # แจ้งเตือน Master Admin
                                if MASTER_ADMIN:
                                    await context.bot.send_message(chat_id=MASTER_ADMIN, text=f"💰 **系统自动确认收款!**\n🆔 User ID: `{user_id}`\n💵 金额: `{expected_amount:.2f}` USDT")
            
            cursor.close(); conn.close()
        except Exception as e:
            print(f"Auto-Verify Error: {e}")
        
        await asyncio.sleep(30) # เช็คทุก 30 วินาที

# --- 修改 /start (เอาคำแนะนำ /verify ออก เพราะระบบเป็น Auto แล้ว) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    amt = 100 + (random.randint(1, 99) / 100)
    exp = datetime.now() + timedelta(minutes=15)

    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO pending_payments VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET amount=EXCLUDED.amount, expire_at=EXCLUDED.expire_at', (update.message.from_user.id, amt, exp))
    conn.commit(); cursor.close(); conn.close()

    msg = (
        "🚀 **欢迎使用 AK 机器人管理系统**\n"
        "----------------------------------\n"
        f"💰 **待支付金额:** `{amt:.2f}` USDT (TRC-20)\n"
        f"🏦 **收款地址:** `{MY_USDT_ADDR}`\n"
        f"⏰ **请在 15 分钟内完成转账**\n"
        "----------------------------------\n"
        "📢 **无需手动确认:**\n"
        "转账完成后，系统将在 1 分钟内自动通过区块链验证并为您开启权限。\n\n"
        "🔍 **查询状态:** 输入 /check 查看您的到期时间。"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- MAIN ---
if __name__ == '__main__':
    app = Application.builder().token(TOKEN).build()
    
    # เพิ่มระบบวนลูปอัตโนมัติเข้าไปในบอท
    job_queue = app.job_queue
    app.job_queue.run_repeating(auto_verify_task, interval=30, first=10)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_status)) # คำสั่งเช็คสิทธิ์
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("undo", undo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    
    app.run_polling()
