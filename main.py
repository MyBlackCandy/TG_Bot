import os
import re
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# นำเข้าฟังก์ชันจากไฟล์แยก (ต้องมั่นใจว่ามีไฟล์ database.py และ payment.py)
from database import init_db, get_db_connection
from payment import generate_payment_amount, auto_verify_payment

# ดึงค่าแอดมินหลัก
MASTER_ADMIN = os.getenv('ADMIN_ID')

# --- 🛡️ ACCESS CONTROL ---
def check_access(user_id, chat_id):
    if str(user_id) == str(MASTER_ADMIN): return True
    conn = get_db_connection(); cursor = conn.cursor()
    # เช็กสมาชิกหลัก
    cursor.execute('SELECT 1 FROM customers WHERE user_id = %s AND expire_date > CURRENT_TIMESTAMP', (user_id,))
    if cursor.fetchone(): 
        cursor.close(); conn.close(); return True
    # เช็กสิทธิ์ลูกทีม
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    res = cursor.fetchone()
    cursor.close(); conn.close()
    return True if res else False

# --- 📊 ACCOUNTING LOGIC (With Shortening Logic) ---

async def send_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ฟังก์ชันกลางสำหรับส่งยอดสรุปแบบย่อรายการ"""
    chat_id = update.effective_chat.id
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
    rows = cursor.fetchall()
    total = sum(r[0] for r in rows)
    count = len(rows)
    
    if count == 0:
        return await update.message.reply_text("📋 **当前无记录**")

    # ส่วนของ Logic การย่อรายการ (แสดง 6 รายการล่าสุด)
    if count > 6:
        display_rows = rows[-6:]
        history_text = "...\n"
        start_num = count - 5
    else:
        display_rows = rows
        history_text = ""
        start_num = 1
        
    for i, r in enumerate(display_rows):
        sign = "+" if r[0] > 0 else ""
        history_text += f"{start_num + i}. {sign}{r[0]} ({r[1]})\n"
    
    cursor.close(); conn.close()
    response = (f"📊 **账目汇总**\n━━━━━━━━━━━━━━━\n{history_text}━━━━━━━━━━━━━━━\n💰 **总额: {total}**")
    await update.message.reply_text(response, parse_mode='Markdown')

# --- 🤖 HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    uid = update.effective_user.id
    amt = await generate_payment_amount(uid)
    await update.message.reply_text(
        f"🚀 **激活系统**\n💳 金额: `{amt:.3f}` USDT\n"
        f"地址: `{os.getenv('USDT_ADDRESS')}`\n"
        f"⚠️ 请务必转账**精确金额**"
    )

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if str(user_id) == str(MASTER_ADMIN):
        return await update.message.reply_text("👑 **สถานะ: MASTER**\n∞ อายุการใช้งาน: ถาวร")

    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (user_id,))
    cust = cursor.fetchone()
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    is_team = cursor.fetchone()
    cursor.close(); conn.close()

    status_msg = f"👤 **ID:** `{user_id}`\n"
    if cust:
        exp = cust[0]
        if exp > datetime.now():
            status_msg += f"✅ **权限:** 正常\n📅 **到期:** `{exp.strftime('%Y-%m-%d %H:%M')}`"
        else:
            status_msg += f"❌ **权限:** 已过期 `{exp.strftime('%Y-%m-%d %H:%M')}`"
    else:
        status_msg += "❓ **权限:** 未开通 (私聊 /start)"
    
    if is_team: status_msg += "\n👥 **สถานะกลุ่มนี้:** เป็นลูกทีม"
    await update.message.reply_text(status_msg, parse_mode='Markdown')

async def handle_accounting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        if not check_access(update.message.from_user.id, update.effective_chat.id): return
        amount = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', 
                       (update.effective_chat.id, amount, update.message.from_user.first_name))
        conn.commit(); cursor.close(); conn.close()
        await send_summary(update, context)

async def undo_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ 已撤销上一条记录")
    await send_summary(update, context)

async def reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE chat_id = %s', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("🧹 已清除所有数据")

# --- (รวม Handler อื่นๆ /add, /remove, /setadmin, /help จากโค้ดเดิมของคุณ) ---
# ... [ใส่ฟังก์ชัน help_command, add_member, remove_member, set_admin_manual ที่นี่] ...

if __name__ == '__main__':
    init_db()
    app = Application.builder().token(os.getenv('TOKEN')).build()
    
    if app.job_queue:
        app.job_queue.run_repeating(auto_verify_payment, interval=60)

    # ลงทะเบียนคำสั่ง (จัดลำดับให้ถูก)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("remove", remove_member))
    app.add_handler(CommandHandler("reset", reset_history))
    app.add_handler(CommandHandler("undo", undo_last))
    app.add_handler(CommandHandler("show", send_summary))
    app.add_handler(CommandHandler("setadmin", set_admin_manual))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_accounting))
    
    print("Bot is running...")
    app.run_polling()
