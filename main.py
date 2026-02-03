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

# --- 修改 /start 为中文详细版 ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    
    # 随机生成 100.01 - 100.99 USDT
    random_decimal = random.randint(1, 99) / 100
    final_amount = 100 + random_decimal
    expire_time = datetime.now() + timedelta(minutes=15)

    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('''INSERT INTO pending_payments (user_id, amount, expire_at) 
                      VALUES (%s, %s, %s) ON CONFLICT (user_id) 
                      DO UPDATE SET amount = EXCLUDED.amount, expire_at = EXCLUDED.expire_at''', 
                   (update.message.from_user.id, final_amount, expire_time))
    conn.commit(); cursor.close(); conn.close()

    msg = (
        "🚀 **欢迎使用 AK 机器人管理系统**\n"
        "----------------------------------\n"
        "💰 **付费开通/续费组长权限:**\n"
        f"• 应付金额: `{final_amount:.2f}` USDT (TRC-20)\n"
        f"• 收款地址: `{MY_USDT_ADDR}`\n"
        f"• 有效期: 15 分钟内完成 (至 {expire_time.strftime('%H:%M')})\n"
        "*(注意：请务必转账精准的小数部分)*\n\n"
        "----------------------------------\n"
        "📖 **使用方法说明:**\n\n"
        "1️⃣ **激活权限:** 转账后请等待1分钟，输入 /verify 自动激活30天权限。\n"
        "2️⃣ **添加组员:** 在群组中 **回复(Reply)** 组员的消息并输入 `/add`。\n"
        "3️⃣ **记录账目:** 直接输入 `+金额` 或 `-金额` (如: +1000)。\n"
        "4️⃣ **撤回记录:** 输入 `/undo` 可删除最后一条记录。\n"
        "5️⃣ **清理数据:** 组长输入 `/reset` 可清空全群记录。\n\n"
        "⚠️ **提示:** 组长权限到期后机器人将停止服务，请及时续费。"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- 验证支付 /verify (保持原逻辑但修改反馈为中文) ---
async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT amount, expire_at FROM pending_payments WHERE user_id = %s', (user.id,))
    res = cursor.fetchone()

    if not res:
        await update.message.reply_text("❌ 未找到待支付订单，请输入 /start 重新发起。")
        return

    if datetime.now() > res[1]:
        await update.message.reply_text("⏰ 订单已超时，请重新输入 /start 获取新的转账金额。")
        return

    # 验证区块链 (verify_on_chain 逻辑同前)
    if verify_on_chain(res[0], user.id):
        cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (user.id,))
        old_exp = cursor.fetchone()
        base = old_exp[0] if old_exp and old_exp[0] > datetime.now() else datetime.now()
        new_expire = base + timedelta(days=30)

        cursor.execute('INSERT INTO customers VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date', (user.id, new_expire))
        cursor.execute('DELETE FROM pending_payments WHERE user_id = %s', (user.id,))
        conn.commit()
        
        await update.message.reply_text(f"✅ **支付成功！**\n权限已延长至: {new_expire.strftime('%Y-%m-%d %H:%M')}")
        await notify_master(context, f"💰 **新付款通知**\n👤 {user.first_name}\n🏷 @{user.username}\n💵 `{res[0]:.2f}` USDT")
    else:
        await update.message.reply_text(f"❌ 未检测到账: `{res[0]:.2f}` USDT\n请确认转账金额准确无误，稍后再试。")
    cursor.close(); conn.close()

# ... 其余 handle_calc, add_member 逻辑保持不变 ...
