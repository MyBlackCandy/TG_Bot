import os
import re
import psycopg2
import requests
import random
import asyncio
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- ⚙️ CONFIG & DATABASE ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID') # ใส่ ID ของคุณใน Railway
MY_USDT_ADDR = os.getenv('USDT_ADDRESS')
TRON_API_KEY = os.getenv('TRONGRID_API_KEY')

def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

# --- 🛡️ ACCESS CONTROL (Master Admin ตลอดชีพ) ---
def check_access(user_id, chat_id):
    # สิทธิ์ตลอดชีพสำหรับ Master Admin
    if str(user_id) == str(MASTER_ADMIN): 
        return True
        
    conn = get_db_connection(); cursor = conn.cursor()
    # เช็คสิทธิ์หัวหน้าทีม (ลูกค้า)
    cursor.execute('SELECT 1 FROM customers WHERE user_id = %s AND expire_date > %s', (user_id, datetime.now()))
    if cursor.fetchone(): 
        cursor.close(); conn.close(); return True
    
    # เช็คสิทธิ์ลูกทีม (ต้องตรงกลุ่ม)
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    res = cursor.fetchone(); cursor.close(); conn.close()
    return True if res else False

# --- 🤖 HANDLERS ---

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📖 **AK 机器人指令指南**\n"
        "━━━━━━━━━━━━━━━\n"
        "👤 **通用指令 (所有成员):**\n"
        "• `+金额` : 记录收入 (例: +100)\n"
        "• `-金额` : 记录支出 (例: -50)\n"
        "• `/check` : 查看您的到期时间\n\n"
        "👑 **组长指令 (需权限):**\n"
        "• `/add` : (回复成员消息) 授权记账\n"
        "• `/remove` : (回复成员消息) 取消授权\n"
        "• `/undo` : 撤销最后一条记录\n"
        "• `/reset` : **清空本群所有账目**\n\n"
        "🛠 **管理员指令 (仅限主管理员):**\n"
        "• `/setadmin [ID] [天数]` : 手动授权"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def remove_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    
    target = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (target.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"🚫 已取消 `{target.first_name}` 的记账权限。")

async def reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE chat_id = %s', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("🧹 **本群记录已重置。** 所有账目已清空。")

async def set_admin_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # เฉพาะคุณเท่านั้นที่ใช้คำสั่งนี้ได้
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    
    try:
        uid = int(context.args[0])
        days = int(context.args[1])
        new_exp = datetime.now() + timedelta(days=days)
        
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO customers VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date', (uid, new_exp))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"👑 **手动授权成功**\n🆔 ID: `{uid}`\n📅 到期: `{new_exp.strftime('%Y-%m-%d')}`")
    except:
        await update.message.reply_text("❌ 格式错误! 请使用: `/setadmin [用户ID] [天数]`")

# --- (ฟังก์ชันเดิมที่ต้องคงไว้: init_db, start, check_status, add_member, undo, handle_calc, auto_verify_task) ---
# ... [คัดลอกฟังก์ชันเหล่านั้นจากโค้ดก่อนหน้ามาใส่ให้ครบ] ...

if __name__ == '__main__':
    # init_db()
    app = Application.builder().token(TOKEN).build()
    
    if app.job_queue:
        app.job_queue.run_repeating(auto_verify_task, interval=30, first=10)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("remove", remove_member))
    app.add_handler(CommandHandler("reset", reset_history))
    app.add_handler(CommandHandler("setadmin", set_admin_manual))
    app.add_handler(CommandHandler("undo", undo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    
    app.run_polling()
