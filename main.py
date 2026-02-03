import os
import re
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# นำเข้าฟังก์ชันจากไฟล์แยกที่เตรียมไว้
from database import init_db, get_db_connection
from payment import generate_payment_amount, auto_verify_payment

# ดึงค่าแอดมินหลักจาก Environment Variable
MASTER_ADMIN = os.getenv('ADMIN_ID')

# --- 🛡️ ACCESS CONTROL (ระบบตรวจสอบสิทธิ์) ---
async def check_access(user_id, chat_id):
    if str(user_id) == str(MASTER_ADMIN): return True
    conn = get_db_connection(); cursor = conn.cursor()
    # 1. เช็กสมาชิกหลัก (เจ้าของสิทธิ์)
    cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (user_id,))
    res = cursor.fetchone()
    if res and res[0] > datetime.now():
        cursor.close(); conn.close(); return True
    # 2. เช็กสิทธิ์ลูกทีมในกลุ่มนี้
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    is_team = cursor.fetchone()
    cursor.close(); conn.close()
    return True if is_team else False

# --- 📊 ACCOUNTING LOGIC (แสดง 6 รายการล่าสุด) ---
async def send_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
    rows = cursor.fetchall()
    total = sum(r[0] for r in rows)
    count = len(rows)
    
    if count == 0:
        return await update.message.reply_text("📋 **当前无记录 (ยังไม่มีรายการ)**")

    # ✅ ย่อรายการเมื่อเกิน 6 รายการ
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
    response = (f"📊 **账目汇总 (สรุปบัญชี)**\n━━━━━━━━━━━━━━━\n{history_text}━━━━━━━━━━━━━━━\n💰 **总额: {total}**")
    await update.message.reply_text(response, parse_mode='Markdown')

# --- 🤖 COMMAND HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    amt = await generate_payment_amount(update.effective_user.id)
    await update.message.reply_text(f"🚀 **激活系统**\n💳 金额: `{amt:.3f}` USDT\nที่อยู่: `{os.getenv('USDT_ADDRESS')}`\n⚠️ 请务必转账**精确金额**")

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
        status_msg += f"{'✅ ปกติ' if exp > datetime.now() else '❌ หมดอายุ'}\n📅 到期: `{exp.strftime('%Y-%m-%d %H:%M')}`"
    else:
        status_msg += "❓ 未开通 (พิมพ์ /start)"
    
    if is_team: status_msg += "\n👥 คุณได้รับสิทธิ์ลูกทีมในกลุ่มนี้"
    await update.message.reply_text(status_msg, parse_mode='Markdown')

async def add_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("⚠️ โปรด Reply ข้อความคนที่ต้องการเพิ่ม")
    if not await check_access(update.message.from_user.id, update.effective_chat.id): return
    target = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO team_members (member_id, allowed_chat_id) VALUES (%s, %s) ON CONFLICT DO NOTHING', (target.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"✅ เพิ่ม {target.first_name} เป็นผู้ช่วยเรียบร้อย")

async def remove_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return
    if not await check_access(update.message.from_user.id, update.effective_chat.id): return
    target = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (target.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"🚫 ลบสิทธิ์ {target.first_name} แล้ว")

async def reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE chat_id = %s', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("🧹 已清除所有数据 (ล้างบัญชีเรียบร้อย)")

async def undo_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ 已撤销 (ยกเลิกรายการล่าสุด)")
    await send_summary(update, context) # สรุปยอดใหม่ทันที

async def set_admin_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    try:
        uid, days = int(context.args[0]), int(context.args[1])
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO customers (user_id, expire_date) VALUES (%s, CURRENT_TIMESTAMP + interval '%s day') ON CONFLICT (user_id) DO UPDATE SET expire_date = EXCLUDED.expire_date", (uid, days))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"👑 เปิดสิทธิ์ ID {uid} จำนวน {days} วัน")
    except: await update.message.reply_text("`/setadmin [ID] [วัน]`")

async def handle_accounting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        if not await check_access(update.message.from_user.id, update.effective_chat.id): return
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', (update.effective_chat.id, amt, update.message.from_user.first_name))
        conn.commit(); cursor.close(); conn.close()
        await send_summary(update, context)

# --- 🚀 RUN BOT ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(os.getenv('TOKEN')).build()
    if app.job_queue: app.job_queue.run_repeating(auto_verify_payment, interval=60)
    
    # ลงทะเบียน Handler (ลำดับฟังก์ชันถูกต้อง)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("remove", remove_member))
    app.add_handler(CommandHandler("reset", reset_history))
    app.add_handler(CommandHandler("undo", undo_last))
    app.add_handler(CommandHandler("show", send_summary))
    app.add_handler(CommandHandler("setadmin", set_admin_manual))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_accounting))
    app.run_polling()
