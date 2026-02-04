import os
import re
import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from database import init_db, get_db_connection

# ตั้งค่าพื้นฐาน
logging.basicConfig(level=logging.INFO)
MASTER_ADMIN = os.getenv('ADMIN_ID') # ไอดีแอดมินสูงสุด

# --- ⚙️ ฟังก์ชันจัดการเวลา (Timezone) ---
def get_now(chat_id):
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT timezone FROM chat_settings WHERE chat_id = %s', (chat_id,))
    res = cursor.fetchone()
    offset = res[0] if res else 0
    cursor.close(); conn.close()
    return datetime.utcnow() + timedelta(hours=offset)

# --- 🛡️ การตรวจสอบสิทธิ์ ---
async def is_allowed(update: Update):
    uid = update.effective_user.id
    if str(uid) == str(MASTER_ADMIN): return True
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM admins WHERE user_id = %s', (uid,))
    res = cursor.fetchone()
    if res and res[0] > datetime.utcnow():
        cursor.close(); conn.close(); return True
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND chat_id = %s', (uid, update.effective_chat.id))
    is_team = cursor.fetchone(); cursor.close(); conn.close()
    return True if is_team else False

# --- 📊 ฟังก์ชันแสดงสรุปยอด ---
async def send_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, show_all=False):
    chat_id = update.effective_chat.id
    now = get_now(chat_id)
    today_str = now.strftime('%Y-%m-%d')
    
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("""
        SELECT amount, user_name FROM history 
        WHERE chat_id = %s 
        AND TO_CHAR(timestamp AT TIME ZONE 'UTC' + (SELECT timezone || ' hours' FROM chat_settings WHERE chat_id = %s), 'YYYY-MM-DD') = %s 
        ORDER BY timestamp ASC
    """, (chat_id, chat_id, today_str))
    rows = cursor.fetchall(); total = sum(r[0] for r in rows); count = len(rows)
    
    if show_all:
        display_rows = rows
        history_text = "📋 รายการทั้งหมดของวันนี้:\n"
    else:
        display_rows = rows[-6:] if count > 6 else rows
        history_text = "...\n" if count > 6 else ""

    for i, r in enumerate(display_rows):
        num = (count - len(display_rows) + i + 1)
        history_text += f"{num}. {'+' if r[0] > 0 else ''}{r[0]} ({r[1]})\n"
    
    cursor.close(); conn.close()
    await update.message.reply_text(
        f"🍎 **今日账目 ({today_str})**\n━━━━━━━━━━━━━━━\n{history_text}━━━━━━━━━━━━━━━\n💰 **总额 (ยอดรวม): {total}**",
        parse_mode='Markdown'
    )

# --- 🤖 คำสั่งบอท (Commands) ---

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = ("📖 **วิธีใช้งานบอท Black Candy (ฉบับละเอียด)**\n"
           "━━━━━━━━━━━━━━━\n"
           "💰 **การบันทึก:** พิมพ์ `+จำนวน` หรือ `-จำนวน` ได้ทันที เช่น `+100` หรือ `-50` (จดแยกตามชื่อคนพิมพ์)\n\n"
           "⚙️ **คำสั่งจัดการบัญชี:**\n"
           "• `/bot` : เริ่มต้นบันทึกของวันใหม่ / ดูยอดสรุปปัจจุบัน\n"
           "• `/undo` : ลบรายการล่าสุดที่เพิ่งจดไป และโชว์ยอดใหม่\n"
           "• `/reset` : ล้างรายการจดทั้งหมดของวันนี้ (ระวัง! กู้คืนไม่ได้)\n"
           "• `/showall` : แสดงรายการทั้งหมดที่จดในวันนี้แบบไม่ย่อ\n"
           "• `/settime [+/-เลข]` : ตั้งเวลาให้ตรงกับเครื่องคุณ เช่น `/settime +7` หรือ `/settime -8` \n\n"
           "👥 **จัดการทีม (Admin/Team):**\n"
           "• `/add` : เพิ่มคนบันทึก (พิมพ์ต่อท้าย หรือ Reply @username)\n"
           "• `/addlist` : ดูรายชื่อคนที่สามารถช่วยบันทึกได้\n"
           "• `/resetadd` : ล้างรายชื่อคนช่วยบันทึกทั้งหมด\n\n"
           "👑 **Admin สูงสุด:**\n"
           "• `/check` : แสดงไอดีตนเอง และเวลาใช้งานที่เหลือ\n"
           "• `/setadmin [วัน]` : เพิ่มเวลาใช้งานแอดมิน (Reply หรือ @username)\n"
           "• `/setlist` : เรียกดูรายชื่อแอดมินและวันหมดอายุทั้งหมด")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def set_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update): return
    try:
        tz = int(context.args[0].replace('+', ''))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO chat_settings (chat_id, timezone) VALUES (%s, %s) ON CONFLICT (chat_id) DO UPDATE SET timezone = EXCLUDED.timezone", (update.effective_chat.id, tz))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"✅ ตั้งค่าเวลาเป็น: `{tz:+} ชั่วโมง` เรียบร้อย")
    except: await update.message.reply_text("วิธีใช้: `/settime +7` หรือ `/settime -8` ")

async def undo_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ **ลบรายการล่าสุดแล้ว**")
    await send_summary(update, context)

async def reset_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update): return
    chat_id = update.effective_chat.id
    now = get_now(chat_id)
    today_str = now.strftime('%Y-%m-%d')
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM history 
        WHERE chat_id = %s 
        AND TO_CHAR(timestamp AT TIME ZONE 'UTC' + (SELECT timezone || ' hours' FROM chat_settings WHERE chat_id = %s), 'YYYY-MM-DD') = %s
    """, (chat_id, chat_id, today_str))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"🗑️ ล้างรายการทั้งหมดของวันที่ {today_str} เรียบร้อย")

async def set_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(MASTER_ADMIN): return
    try:
        days = int(context.args[-1])
        target_id = None
        if update.message.reply_to_message:
            target_id = update.message.reply_to_message.from_user.id
        else:
            for ent in update.message.entities:
                if ent.type == 'text_mention': target_id = ent.user.id
            if not target_id: target_id = int(context.args[0])

        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO admins (user_id, expire_date) 
            VALUES (%s, CURRENT_TIMESTAMP + interval '%s day') 
            ON CONFLICT (user_id) 
            DO UPDATE SET expire_date = GREATEST(admins.expire_date, CURRENT_TIMESTAMP) + interval '%s day'
        """, (target_id, days, days))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"👑 เพิ่มวันใช้งาน ID `{target_id}` อีก `{days}` วัน (สะสมเพิ่มจากของเดิม)")
    except: await update.message.reply_text("วิธีใช้: `/setadmin @username [วัน]` หรือ Reply แล้วพิมพ์ `/setadmin [วัน]`")

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM admins WHERE user_id = %s', (uid,))
    res = cursor.fetchone(); cursor.close(); conn.close()
    if str(uid) == str(MASTER_ADMIN): 
        msg = f"🆔 ID: `{uid}`\n👑 สถานะ: แอดมินหลัก (ถาวร)"
    elif res:
        remain = res[0] - datetime.utcnow()
        days = remain.days
        hours = remain.seconds // 3600
        msg = f"🆔 ID: `{uid}`\n⏳ เหลือเวลาใช้งาน: `{days} วัน {hours} ชั่วโมง`"
    else: msg = f"🆔 ID: `{uid}`\n❌ คุณไม่มีสิทธิ์เข้าถึงแอดมิน"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def handle_accounting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip(); match = re.match(r'^([+-])(\d+)$', text)
    if match:
        if not await is_allowed(update): return
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', 
                       (update.effective_chat.id, amt, update.message.from_user.first_name))
        conn.commit(); cursor.close(); conn.close()
        await send_summary(update, context)

# --- 🚀 เริ่มต้นบอท ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(os.getenv('TOKEN')).build()
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("start", help_command))
    app.add_handler(CommandHandler("bot", send_summary))
    app.add_handler(CommandHandler("settime", set_timezone))
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(CommandHandler("undo", undo_last))
    app.add_handler(CommandHandler("reset", reset_today))
    app.add_handler(CommandHandler("showall", lambda u, c: send_summary(u, c, show_all=True)))
    app.add_handler(CommandHandler("setadmin", set_admin))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_accounting))
    app.run_polling()
