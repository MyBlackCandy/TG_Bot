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

# --- 🚀 [ภาษาจีน] คำสั่ง /start: ใบสั่งซื้อและคู่มือเบื้องต้น ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    amt = 100 + (random.randint(1, 99) / 100)
    exp = datetime.now() + timedelta(minutes=15)

    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO pending_payments VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET amount=EXCLUDED.amount, expire_at=EXCLUDED.expire_at', (update.message.from_user.id, amt, exp))
    conn.commit(); cursor.close(); conn.close()

    msg = (
        "🚀 **欢迎使用 AK 机器人管理系统**\n"
        "━━━━━━━━━━━━━━━\n"
        "💳 **付费开通/续费组长权限:**\n"
        f"• 应付金额: `{amt:.2f}` USDT (TRC-20)\n"
        f"• 收款地址: `{MY_USDT_ADDR}`\n"
        f"• 有效期: 15 分钟内 (至 {exp.strftime('%H:%M')})\n"
        "*(📢 注意：转账金额必须包含精准的小数点后两位)*\n\n"
        "🤖 **激活流程:**\n"
        "转账后无需任何操作，系统将在 1 分钟内通过区块链自动验证并为您开启 30 天权限。\n\n"
        "📜 **功能列表:** 请输入 /help 查看详细指令。"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- 📖 [ภาษาจีน] คำสั่ง /help: สรุปคำสั่งทั้งหมดอย่างละเอียด ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📖 **AK 机器人完整指令指南**\n"
        "━━━━━━━━━━━━━━━\n"
        "👤 **[通用指令 - 所有人]**\n"
        "• `+金额` : 记录收入 (如: +1000)\n"
        "• `-金额` : 记录支出 (如: -500)\n"
        "• `/check` : 查看个人权限及到期时间\n"
        "• `/help` : 显示此帮助菜单\n\n"
        "👑 **[组长指令 - 权限用户]**\n"
        "• `/add` : (回复组员消息) 授权其在群内记账\n"
        "• `/remove` : (回复组员消息) 取消其记账权限\n"
        "• `/undo` : 撤销最后一次记账记录\n"
        "• `/reset` : 清空当前群组所有历史记录\n\n"
        "💡 **温馨提示:**\n"
        "如果您是新用户，请先在私聊中输入 /start 完成支付以获得组长权限。"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- 🔍 [ภาษาจีน] คำสั่ง /check: ตรวจสอบสถานะและวันหมดอายุ ---
async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (user_id,))
    res = cursor.fetchone(); cursor.close(); conn.close()
    
    if res and res[0] > datetime.now():
        await update.message.reply_text(
            f"✅ **权限状态: 正常有效**\n"
            f"📅 **到期时间:** `{res[0].strftime('%Y-%m-%d %H:%M')}`\n"
            "💡 如需续费，请在私聊中发送 /start", parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ **权限状态: 未开通或已过期**\n请发送 /start 重新获取权限。")

# --- ⚙️ ฟังก์ชันช่วยเหลืออื่นๆ (add_member, undo, handle_calc, auto_verify_task) ---
# (ใส่โค้ดเดิมที่คุณมีไว้ที่นี่)

if __name__ == '__main__':
    # init_db()
    app = Application.builder().token(TOKEN).build()
    
    # ระบบตรวจสอบยอดเงินอัตโนมัติ
    if app.job_queue:
        app.job_queue.run_repeating(auto_verify_task, interval=30, first=10)
    
    # ลงทะเบียนคำสั่ง
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command)) # เพิ่มคำสั่งช่วยเหลือ
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("undo", undo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    
    app.run_polling()
