import os
import re
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from database import init_db, get_db_connection
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# ดึงค่าแอดมินหลักจาก Environment Variable (ต้องตั้งใน Railway)
MASTER_ADMIN = os.getenv('ADMIN_ID')

# --- 🛡️ ฟังก์ชันตรวจสอบสิทธิ์ ---
async def check_access(user_id, chat_id):
    if str(user_id) == str(MASTER_ADMIN): return True
    conn = get_db_connection(); cursor = conn.cursor()
    # เช็กสมาชิกที่ยังไม่หมดอายุ
    cursor.execute('SELECT 1 FROM customers WHERE user_id = %s AND expire_date > CURRENT_TIMESTAMP', (user_id,))
    if cursor.fetchone(): 
        cursor.close(); conn.close(); return True
    # เช็กสิทธิ์ลูกทีมในกลุ่มนี้
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    res = cursor.fetchone(); cursor.close(); conn.close()
    return True if res else False

# --- 📊 ฟังก์ชันสรุปยอด (ย่อรายการเมื่อเกิน 6) ---
async def send_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
    rows = cursor.fetchall(); total = sum(r[0] for r in rows); count = len(rows)
    
    if count == 0:
        return await update.message.reply_text("📋 **当前无记录 (ยังไม่มีรายการ)**")

    # ✅ ระบบย่อรายการ: แสดงแค่ 6 รายการล่าสุด
    history_text = "...\n" if count > 6 else ""
    display_rows = rows[-6:] if count > 6 else rows
    start_num = max(1, count - 5) if count > 6 else 1
    
    for i, r in enumerate(display_rows):
        sign = "+" if r[0] > 0 else ""
        history_text += f"{start_num + i}. {sign}{r[0]} ({r[1]})\n"
    
    # ✅ ปุ่มกดดูรายงานออนไลน์ (ส่ง Chat ID ไปทาง URL)
    keyboard = [[InlineKeyboardButton("📊 点击跳转完整账单 (ดูรายงานฉบับเต็ม)", url=f"{BASE_WEB_URL}/index.php?c={chat_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    cursor.close(); conn.close()
    await update.message.reply_text(
        f"📊 **账目汇总**\n━━━━━━━━━━━━━━━\n{history_text}━━━━━━━━━━━━━━━\n💰 **总额: {total}**",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# --- 🤖 คำสั่งบอท ---

async def help_command(update, context):
    msg = ("📖 **黑糖果机器人使用说明**\n"
           "━━━━━━━━━━━━━━━\n"
           "💰 **จดบัญชี:** พิมพ์ `+100` หรือ `-50` ในกลุ่ม\n"
           "📋 **คำสั่งพื้นฐาน:**\n"
           "• `/show` : ดูสรุปยอดปัจจุบัน\n"
           "• `/undo` : ยกเลิกรายการล่าสุด (และโชว์ยอดใหม่)\n"
           "• `/reset` : ล้างบัญชีทั้งหมดในกลุ่ม\n"
           "• `/check` : เช็กวันหมดอายุและ ID\n\n"
           "👥 **จัดการทีม:**\n"
           "• Reply + `/add` : เพิ่มคนช่วยจด\n"
           "• Reply + `/remove` : ลบคนช่วยจด")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def undo_last(update, context):
    if not await check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ **已撤销上一条记录 (ยกเลิกแล้ว)**")
    await send_summary(update, context) # ✅ ส่งสรุปยอดใหม่ทันที

async def add_member(update, context):
    if not update.message.reply_to_message:
        return await update.message.reply_text("⚠️ 请回复操作者的信息 (โปรด Reply ข้อความคนที่ต้องการเพิ่ม)")
    if not await check_access(update.message.from_user.id, update.effective_chat.id): return
    target = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO team_members (member_id, allowed_chat_id) VALUES (%s, %s) ON CONFLICT DO NOTHING', (target.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"✅ 已增加操作者: {target.first_name}")

async def reset_history(update, context):
    if not await check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE chat_id = %s', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("🧹 **已清除所有数据 (Reset แล้ว)**")

async def check_status(update, context):
    uid = update.effective_user.id
    if str(uid) == str(MASTER_ADMIN): return await update.message.reply_text("👑 **MASTER ADMIN**")
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (uid,))
    res = cursor.fetchone(); cursor.close(); conn.close()
    msg = f"👤 ID: `{uid}`\n📅 到期: `{res[0].strftime('%Y-%m-%d %H:%M')}`" if res else f"👤 ID: `{uid}`\n❌ 未开通 (ยังไม่เปิดสมาชิก)"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def set_admin_manual(update, context):
    """/setadmin [ID] [Days] - แอดมินหลักใช้เพิ่มวันสมาชิก"""
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    try:
        uid, days = int(context.args[0]), int(context.args[1])
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO customers (user_id, expire_date) VALUES (%s, CURRENT_TIMESTAMP + interval '%s day') ON CONFLICT (user_id) DO UPDATE SET expire_date = EXCLUDED.expire_date", (uid, days))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"👑 **Admin Set:** ID {uid} (+{days} วัน)")
    except: await update.message.reply_text("รูปแบบ: `/setadmin [ID] [วัน]`")

async def handle_accounting(update, context):
    if not update.message or not update.message.text: return
    text = update.message.text.strip(); match = re.match(r'^([+-])(\d+)$', text)
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
    
    # ⚠️ เรียงลำดับคำสั่ง (CommandHandler ต้องอยู่ก่อน MessageHandler)
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("show", send_summary))
    app.add_handler(CommandHandler("undo", undo_last))
    app.add_handler(CommandHandler("reset", reset_history))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(CommandHandler("setadmin", set_admin_manual))
    
    # ดักจับตัวเลขจดบัญชี
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_accounting))
    
    print("Bot is ready (Accounting Stable Mode)")
    app.run_polling()
