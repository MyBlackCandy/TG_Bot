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
    """ตรวจสอบสิทธิ์: MASTER_ADMIN | สมาชิกที่ยังไม่หมดอายุ | ลูกทีมในกลุ่มนั้น"""
    if str(user_id) == str(MASTER_ADMIN): return True
    
    conn = get_db_connection(); cursor = conn.cursor()
    # 1. เช็กสมาชิกหลัก (ผู้จ่ายเงิน)
    cursor.execute('SELECT 1 FROM customers WHERE user_id = %s AND expire_date > CURRENT_TIMESTAMP', (user_id,))
    if cursor.fetchone(): 
        cursor.close(); conn.close(); return True
    
    # 2. เช็กสิทธิ์ลูกทีมในกลุ่มที่กำหนด
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    res = cursor.fetchone()
    cursor.close(); conn.close()
    return True if res else False

# --- 📊 ACCOUNTING DISPLAY (ระบบย่อรายการเมื่อเกิน 6) ---
async def send_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
    rows = cursor.fetchall()
    total = sum(r[0] for r in rows)
    count = len(rows)
    
    if count == 0:
        return await update.message.reply_text("📋 **当前无记录 (ยังไม่มีรายการ)**")

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

# --- 🤖 COMMAND HANDLERS (ฟังก์ชันคำสั่งทั้งหมด) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start - ขอรับยอดโอนและที่อยู่กระเป๋า (ทศนิยมคงที่)"""
    if update.effective_chat.type != 'private': return
    uid = update.effective_user.id
    amt = await generate_payment_amount(uid)
    await update.message.reply_text(
        f"🚀 **激活系统 (ระบบเปิดสิทธิ์อัตโนมัติ)**\n\n"
        f"💳 ยอดโอน: `{amt:.3f}` USDT\n"
        f"📍 ที่อยู่ TRC20: `{os.getenv('USDT_ADDRESS')}`\n\n"
        f"⚠️ 请务必转账**精确金额** (โปรดโอนยอดให้ตรงทศนิยมเป๊ะๆ)"
    )

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/check - ตรวจสอบวันหมดอายุสมาชิกและสถานะสิทธิ์"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if str(user_id) == str(MASTER_ADMIN):
        return await update.message.reply_text("👑 **สถานะ: MASTER ADMIN**\n∞ อายุการใช้งาน: ถาวร")

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
            status_msg += f"✅ **สถานะ:** ปกติ\n📅 **หมดอายุ:** `{exp.strftime('%Y-%m-%d %H:%M')}`"
        else:
            status_msg += f"❌ **สถานะ:** หมดอายุแล้ว `{exp.strftime('%Y-%m-%d %H:%M')}`"
    else:
        status_msg += "❓ **สถานะ:** ยังไม่ได้เปิดสิทธิ์สมาชิก (ทักส่วนตัว /start)"
    
    if is_team: status_msg += "\n👥 **ในกลุ่มนี้:** คุณได้รับสิทธิ์เป็นลูกทีม"
    await update.message.reply_text(status_msg, parse_mode='Markdown')

async def add_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/add - มอบสิทธิ์ให้ลูกทีม (Reply คนนั้น)"""
    if not update.message.reply_to_message:
        return await update.message.reply_text("⚠️ โปรด Reply ข้อความของคนที่ต้องการให้สิทธิ์")
    
    if not await check_access(update.message.from_user.id, update.effective_chat.id): return

    target = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('''INSERT INTO team_members (member_id, allowed_chat_id) 
                   VALUES (%s, %s) ON CONFLICT DO NOTHING''', (target.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"✅ เพิ่มผู้ช่วย {target.first_name} ในกลุ่มนี้เรียบร้อย")

async def remove_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/remove - ยกเลิกสิทธิ์ลูกทีม (Reply คนนั้น)"""
    if not update.message.reply_to_message: return
    if not await check_access(update.message.from_user.id, update.effective_chat.id): return

    target = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', 
                   (target.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"🚫 ยกเลิกสิทธิ์ {target.first_name} แล้ว")

async def reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/reset - ล้างบัญชีทั้งหมดในกลุ่มนี้"""
    if not await check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE chat_id = %s', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("🧹 ล้างข้อมูลบัญชีในกลุ่มนี้เรียบร้อย (Reset Success)")

async def undo_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/undo - ยกเลิกรายการล่าสุดและโชว์ยอดใหม่ทันที"""
    if not await check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('''DELETE FROM history WHERE id = (
        SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1
    )''', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ ยกเลิกรายการล่าสุดแล้ว")
    await send_summary(update, context)

async def set_admin_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/setadmin [ID] [Days] - เพิ่มวันใช้งาน (แอดมินหลักเท่านั้น)"""
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    try:
        user_id, days = int(context.args[0]), int(context.args[1])
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('''INSERT INTO customers (user_id, expire_date) 
                       VALUES (%s, CURRENT_TIMESTAMP + interval '%s day')
                       ON CONFLICT (user_id) DO UPDATE SET expire_date = EXCLUDED.expire_date''', (user_id, days))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"👑 มอบสิทธิ์ ID {user_id} จำนวน {days} วัน")
    except:
        await update.message.reply_text("รูปแบบ: `/setadmin [ID] [วัน]`")

async def handle_accounting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """รับข้อความ +เลข หรือ -เลข เพื่อจดบัญชี"""
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        if not await check_access(update.message.from_user.id, update.effective_chat.id): return
        amount = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', 
                       (update.effective_chat.id, amount, update.message.from_user.first_name))
        conn.commit(); cursor.close(); conn.close()
        await send_summary(update, context)

# --- 🚀 RUN BOT ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(os.getenv('TOKEN')).build()
    
    # รัน Job ตรวจสอบชำระเงินอัตโนมัติเบื้องหลัง
    if app.job_queue:
        app.job_queue.run_repeating(auto_verify_payment, interval=60)

    # ลงทะเบียน Handler (ลำดับฟังก์ชันถูกต้อง)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("remove", remove_member))
    app.add_handler(CommandHandler("reset", reset_history))
    app.add_handler(CommandHandler("undo", undo_last))
    app.add_handler(CommandHandler("setadmin", set_admin_manual))
    app.add_handler(CommandHandler("show", send_summary))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_accounting))
    
    print("Bot is fully armed and ready!")
    app.run_polling()
