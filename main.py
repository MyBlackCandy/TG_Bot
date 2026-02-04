import os
import re
import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from database import init_db, get_db_connection

# ตั้งค่า Logging เพื่อดูสถานะการทำงาน
logging.basicConfig(level=logging.INFO)

# ดึงค่าแอดมินสูงสุดจาก Environment Variables
MASTER_ADMIN = os.getenv('ADMIN_ID')

# --- ⚙️ ฟังก์ชันจัดการเวลา (Timezone Management) ---
def get_now(chat_id):
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT timezone FROM chat_settings WHERE chat_id = %s', (chat_id,))
    res = cursor.fetchone()
    offset = res[0] if res else 0
    cursor.close(); conn.close()
    return datetime.utcnow() + timedelta(hours=offset)

# --- 🛡️ ฟังก์ชันตรวจสอบสิทธิ์ (Access Control) ---
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

# --- 📊 ฟังก์ชันสรุปยอด (Summary Engine) ---
async def send_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, show_all=False):
    chat_id = update.effective_chat.id
    now = get_now(chat_id); today_str = now.strftime('%Y-%m-%d')
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("""
        SELECT amount, user_name FROM history 
        WHERE chat_id = %s 
        AND TO_CHAR(timestamp AT TIME ZONE 'UTC' + (SELECT timezone || ' hours' FROM chat_settings WHERE chat_id = %s), 'YYYY-MM-DD') = %s 
        ORDER BY timestamp ASC
    """, (chat_id, chat_id, today_str))
    rows = cursor.fetchall(); total = sum(r[0] for r in rows); count = len(rows)
    
    display_rows = rows if show_all else (rows[-6:] if count > 6 else rows)
    history_text = "📋 รายการทั้งหมดของวันนี้:\n" if show_all else ("...\n" if count > 6 else "")
    for i, r in enumerate(display_rows):
        num = (count - len(display_rows) + i + 1)
        history_text += f"{num}. {'+' if r[0] > 0 else ''}{r[0]} ({r[1]})\n"
    
    cursor.close(); conn.close()
    await update.message.reply_text(
        f"🍎 **今日账目 ({today_str})**\n━━━━━━━━━━━━━━━\n{history_text}━━━━━━━━━━━━━━━\n💰 **ยอดรวม: {total}**",
        parse_mode='Markdown'
    )

# --- 🤖 คำสั่งจัดการบัญชี (Accounting Commands) ---
async def help_cmd(update, context):
    msg = ("📖 **วิธีใช้บอท Black Candy (ละเอียด)**\n"
           "━━━━━━━━━━━━━━━\n"
           "💰 **จดบันทึก:** พิมพ์ `+100` หรือ `-50` ได้ทันที\n"
           "• `/bot`: ดูยอดสรุปปัจจุบัน\n"
           "• `/undo`: ลบรายการล่าสุด และโชว์ยอดใหม่\n"
           "• `/reset`: ล้างบัญชีทั้งหมดของวันนี้\n"
           "• `/showall`: ดูยอดทั้งหมดแบบไม่ย่อ\n"
           "• `/settime [+/-เลข]`: ตั้งโซนเวลา เช่น `/settime +7` \n\n"
           "👥 **จัดการทีม:**\n"
           "• `/add`: เพิ่มคนบันทึก (Reply หรือ @username)\n"
           "• `/addlist`: ดูรายชื่อคนบันทึก\n"
           "• `/resetadd`: ลบคนบันทึกทั้งหมด\n\n"
           "👑 **Admin:**\n"
           "• `/check`: เช็ค ID และเวลาใช้งาน (ละเอียดถึงนาที)\n"
           "• `/setadmin [วัน]`: เพิ่มวันแอดมิน (สะสมวันได้)\n"
           "• `/setlist`: ดูรายชื่อแอดมินทั้งหมด")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def undo_last(update, context):
    if not await is_allowed(update): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ ลบรายการล่าสุดแล้ว ยอดใหม่คือ:")
    await send_summary(update, context)

async def reset_day(update, context):
    if not await is_allowed(update): return
    chat_id = update.effective_chat.id; now = get_now(chat_id); today_str = now.strftime('%Y-%m-%d')
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("DELETE FROM history WHERE chat_id = %s AND TO_CHAR(timestamp AT TIME ZONE 'UTC' + (SELECT timezone || ' hours' FROM chat_settings WHERE chat_id = %s), 'YYYY-MM-DD') = %s", (chat_id, chat_id, today_str))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"🗑️ ล้างรายการของวันที่ {today_str} เรียบร้อย")

async def set_time(update, context):
    if not await is_allowed(update): return
    try:
        tz = int(context.args[0].replace('+', ''))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO chat_settings (chat_id, timezone) VALUES (%s, %s) ON CONFLICT (chat_id) DO UPDATE SET timezone = EXCLUDED.timezone", (update.effective_chat.id, tz))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"✅ ตั้งเวลาเป็น: `{tz:+} ชั่วโมง` เรียบร้อย")
    except: await update.message.reply_text("วิธีใช้: `/settime +7` หรือ `/settime -8` ")

# --- 👥 จัดการทีมงาน (Team Members) ---
async def add_member(update, context):
    if not await is_allowed(update): return
    target = None; name = ""
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user.id
        name = update.message.reply_to_message.from_user.first_name
    elif context.args:
        await update.message.reply_text("⚠️ โปรดใช้วิธี Reply ข้อความแล้วพิมพ์ /add")
        return
    if target:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO team_members VALUES (%s, %s, %s) ON CONFLICT (member_id, chat_id) DO UPDATE SET username = EXCLUDED.username", (target, update.effective_chat.id, name))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"✅ เพิ่มคุณ {name} เป็นคนบันทึกแล้ว")

async def add_list(update, context):
    if not await is_allowed(update): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT username, member_id FROM team_members WHERE chat_id = %s", (update.effective_chat.id,))
    rows = cursor.fetchall(); cursor.close(); conn.close()
    msg = "👥 **รายชื่อคนบันทึก:**\n" + "\n".join([f"{i+1}. {r[0]} (`{r[1]}`)" for i, r in enumerate(rows)]) if rows else "ℹ️ ยังไม่มีรายชื่อคนบันทึก"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def reset_add(update, context):
    if not await is_allowed(update): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("DELETE FROM team_members WHERE chat_id = %s", (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("🗑️ ลบคนบันทึกทั้งหมดในกลุ่มนี้แล้ว")

# --- 👑 สำหรับ Admin และ MASTER_ADMIN ---
async def check_status(update, context):
    uid = update.effective_user.id; conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM admins WHERE user_id = %s', (uid,))
    res = cursor.fetchone(); cursor.close(); conn.close()
    if str(uid) == str(MASTER_ADMIN): 
        msg = f"🆔 ID: `{uid}`\n👑 สถานะ: **แอดมินหลัก (ถาวร)**"
    elif res:
        rem = res[0] - datetime.utcnow()
        if rem.total_seconds() > 0:
            msg = f"🆔 ID: `{uid}`\n⏳ เหลือ: `{rem.days} วัน {rem.seconds // 3600} ชม. {(rem.seconds // 60) % 60} นาที`"
        else: msg = f"🆔 ID: `{uid}`\n❌ สถานะ: หมดอายุ"
    else: msg = f"🆔 ID: `{uid}`\n❌ คุณไม่มีสิทธิ์แอดมิน"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def set_admin(update, context):
    if str(update.effective_user.id) != str(MASTER_ADMIN): return
    try:
        days = int(context.args[-1]); target_id = None
        if update.message.reply_to_message: target_id = update.message.reply_to_message.from_user.id
        else: target_id = int(context.args[0])
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO admins (user_id, expire_date) VALUES (%s, CURRENT_TIMESTAMP + interval '%s day') ON CONFLICT (user_id) DO UPDATE SET expire_date = GREATEST(admins.expire_date, CURRENT_TIMESTAMP) + interval '%s day'", (target_id, days, days))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"👑 เพิ่มวัน ID `{target_id}` อีก `{days}` วัน (สะสมจากเดิม)")
    except: await update.message.reply_text("วิธีใช้: `/setadmin [ID] [วัน]` หรือ Reply พร้อมระบุวัน")

async def set_list(update, context):
    if str(update.effective_user.id) != str(MASTER_ADMIN): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT user_id, expire_date FROM admins ORDER BY expire_date DESC")
    rows = cursor.fetchall(); cursor.close(); conn.close()
    msg = "👑 **รายชื่อแอดมินทั้งหมด:**\n"
    now = datetime.utcnow()
    for r in rows:
        rem = r[1] - now
        status = f"🟢 `{rem.days}d {rem.seconds//3600}h {(rem.seconds//60)%60}m`" if r[1] > now else "🔴 หมดอายุ"
        msg += f"• `{r[0]}`: {status}\n"
    await update.message.reply_text(msg if rows else "ℹ️ ไม่มีแอดมิน", parse_mode='Markdown')

async def handle_msg(update, context):
    text = update.message.text.strip(); match = re.match(r'^([+-])(\d+)$', text)
    if match:
        if not await is_allowed(update): return
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', (update.effective_chat.id, amt, update.message.from_user.first_name))
        conn.commit(); cursor.close(); conn.close(); await send_summary(update, context)

if __name__ == '__main__':
    init_db()
    app = Application.builder().token(os.getenv('TOKEN')).build()
    app.add_handler(CommandHandler(["start", "help"], help_cmd))
    app.add_handler(CommandHandler("bot", send_summary))
    app.add_handler(CommandHandler("undo", undo_last))
    app.add_handler(CommandHandler("reset", reset_day))
    app.add_handler(CommandHandler("showall", lambda u, c: send_summary(u, c, show_all=True)))
    app.add_handler(CommandHandler("settime", set_time))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("addlist", add_list))
    app.add_handler(CommandHandler("resetadd", reset_add))
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(CommandHandler("setadmin", set_admin))
    app.add_handler(CommandHandler("setlist", set_list))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.run_polling()
