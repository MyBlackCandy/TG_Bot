import os
import re
import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from database import init_db, get_db_connection

# --- ⚙️ 1. ตั้งค่าพื้นฐานและการ Log ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
MASTER_ADMIN = os.getenv('ADMIN_ID')

# --- ⚙️ 2. ฟังก์ชันจัดการเวลาท้องถิ่น (Timezone Handling) ---
def get_local_time(chat_id, utc_time=None):
    if utc_time is None:
        utc_time = datetime.utcnow()
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT timezone FROM chat_settings WHERE chat_id = %s', (chat_id,))
    res = cursor.fetchone()
    offset = res[0] if res else 0
    cursor.close(); conn.close()
    return utc_time + timedelta(hours=offset)

# --- 🛡️ 3. ระบบตรวจสอบสิทธิ์ (Access Control) ---
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

# --- 📊 4. ระบบแสดงผลยอด (Summary Engine) ---
async def send_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, show_all=False):
    chat_id = update.effective_chat.id
    now_local = get_local_time(chat_id)
    today_str = now_local.strftime('%Y-%m-%d')
    
    conn = get_db_connection(); cursor = conn.cursor()
    # ดึงข้อมูลพร้อมปรับโซนเวลาด้วย SQL เพื่อความแม่นยำสูงสุด
    cursor.execute("""
        SELECT amount, user_name, (timestamp AT TIME ZONE 'UTC' + ( (SELECT timezone FROM chat_settings WHERE chat_id = %s) || ' hours')::interval) as local_ts 
        FROM history 
        WHERE chat_id = %s 
        AND TO_CHAR(timestamp AT TIME ZONE 'UTC' + ( (SELECT timezone FROM chat_settings WHERE chat_id = %s) || ' hours')::interval, 'YYYY-MM-DD') = %s 
        ORDER BY timestamp ASC
    """, (chat_id, chat_id, chat_id, today_str))
    
    rows = cursor.fetchall(); total = sum(r[0] for r in rows); count = len(rows)
    display_rows = rows if show_all else (rows[-6:] if count > 6 else rows)
    history_text = "📋 **รายการทั้งหมดของวันนี้:**\n" if show_all else ("...\n" if count > 6 else "")
    
    for i, r in enumerate(display_rows):
        num = (count - len(display_rows) + i + 1)
        time_str = r[2].strftime('%H:%M')
        history_text += f"{num:<3} {time_str:<6} {r[0]:>8} ({r[1]})\n"

    cursor.close(); conn.close()
    await update.message.reply_text(
        f"🍎 **今日账目 ({today_str})**\n━━━━━━━━━━━━━━━\n{history_text}━━━━━━━━━━━━━━━\n💰 **ยอดรวม: {total}**",
        parse_mode='Markdown'
    )
    
# --- 🤖 5. คำสั่งจัดการบัญชี (Accounting) ---
async def help_cmd(update, context):
    msg = ("📖 **Black Candy Help (ละเอียด)**\n━━━━━━━━━━━━━━━\n"
           "💰 **การบันทึก:** พิมพ์ `+100` หรือ `-50` บอทจะจดเวลาและชื่อคนพิมพ์ให้ทันที\n\n"
           "⚙️ **บัญชี:**\n• `/bot` : ดูยอดสรุปและรายการล่าสุด\n• `/undo` : ลบรายการล่าสุด\n• `/reset` : ล้างรายการทั้งหมดของวันนี้\n• `/showall` : ดูรายการทั้งหมดแบบไม่ย่อ\n• `/settime [+/-เลข]` : ตั้งโซนเวลา (เช่น `/settime +7`)\n\n"
           "👥 **ทีมงาน:**\n• `/add` : เพิ่มคนจด (Reply คนนั้น)\n• `/addlist` : ดูรายชื่อคนจดในกลุ่ม\n• `/resetadd` : ลบคนจดทั้งหมดในกลุ่ม\n\n"
           "👑 **Admin:**\n• `/check` : เช็ค ID และเวลาที่เหลือ (ละเอียดถึงนาที)\n• `/setadmin [วัน]` : เพิ่มวันแอดมิน (สะสมวันได้)\n• `/setlist` : ดูรายชื่อแอดมินทั้งหมด")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def undo_last(update, context):
    if not await is_allowed(update): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ ลบรายการล่าสุดเรียบร้อย")
    await send_summary(update, context)

async def reset_day(update, context):
    if not await is_allowed(update): return
    chat_id = update.effective_chat.id; now_local = get_local_time(chat_id); today_str = now_local.strftime('%Y-%m-%d')
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("DELETE FROM history WHERE chat_id = %s AND TO_CHAR(timestamp AT TIME ZONE 'UTC' + ( (SELECT timezone FROM chat_settings WHERE chat_id = %s) || ' hours')::interval, 'YYYY-MM-DD') = %s", (chat_id, chat_id, today_str))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"🗑️ ล้างรายการของวันที่ `{today_str}` เรียบร้อยแล้ว")

async def set_time(update, context):
    if not await is_allowed(update): return
    try:
        tz = int(context.args[0].replace('+', ''))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO chat_settings (chat_id, timezone) VALUES (%s, %s) ON CONFLICT (chat_id) DO UPDATE SET timezone = EXCLUDED.timezone", (update.effective_chat.id, tz))
        conn.commit(); cursor.close(); conn.close()
        new_time = get_local_time(update.effective_chat.id)
        await update.message.reply_text(f"✅ ตั้งโซนเวลาสำเร็จ! เวลาบอทตอนนี้: `{new_time.strftime('%H:%M:%S')}`")
    except: await update.message.reply_text("ใช้: `/settime +7` หรือ `/settime -8` ")

# --- 👥 6. จัดการทีมงาน (Team Members) ---
async def add_member(update, context):
    if not await is_allowed(update): return
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user.id
        name = update.message.reply_to_message.from_user.first_name
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO team_members VALUES (%s, %s, %s) ON CONFLICT (member_id, chat_id) DO UPDATE SET username = EXCLUDED.username", (target, update.effective_chat.id, name))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"✅ เพิ่มคุณ {name} เป็นคนจดเรียบร้อย")
    else: await update.message.reply_text("⚠️ โปรดใช้วิธี Reply ข้อความของคนที่จะเพิ่มแล้วพิมพ์ /add")

async def add_list(update, context):
    if not await is_allowed(update): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT username, member_id FROM team_members WHERE chat_id = %s", (update.effective_chat.id,))
    rows = cursor.fetchall(); cursor.close(); conn.close()
    msg = "👥 **คนที่มีสิทธิ์จดในกลุ่มนี้:**\n" + "\n".join([f"{i+1}. {r[0]} (`{r[1]}`)" for i, r in enumerate(rows)]) if rows else "ℹ️ ไม่มีรายชื่อคนจด"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def reset_add(update, context):
    if not await is_allowed(update): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("DELETE FROM team_members WHERE chat_id = %s", (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("🗑️ ล้างรายชื่อคนจดทั้งหมดในกลุ่มนี้แล้ว")

# --- 👑 7. ระบบ Admin & MASTER (Privileged) ---
async def check_status(update, context):
    uid = update.effective_user.id; conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM admins WHERE user_id = %s', (uid,))
    res = cursor.fetchone(); cursor.close(); conn.close()
    if str(uid) == str(MASTER_ADMIN): msg = f"🆔 ID: `{uid}`\n👑 สถานะ: **MASTER ADMIN (ถาวร)**"
    elif res:
        rem = res[0] - datetime.utcnow()
        if rem.total_seconds() > 0:
            msg = f"🆔 ID: `{uid}`\n⏳ เหลือ: `{rem.days} วัน {rem.seconds // 3600} ชม. {(rem.seconds // 60) % 60} นาที`"
        else: msg = f"🆔 ID: `{uid}`\n❌ สถานะ: **หมดอายุ**"
    else: msg = f"🆔 ID: `{uid}`\n❌ คุณไม่มีสิทธิ์เข้าถึงระบบแอดมิน"
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
        await update.message.reply_text(f"👑 เพิ่มวัน ID `{target_id}` อีก `{days}` วัน (สะสมเรียบร้อย)")
    except: await update.message.reply_text("ใช้: `/setadmin [ID] [วัน]` หรือ Reply แล้วใส่จำนวนวัน")

async def set_list(update, context):
    if str(update.effective_user.id) != str(MASTER_ADMIN): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT user_id, expire_date FROM admins ORDER BY expire_date DESC")
    rows = cursor.fetchall(); cursor.close(); conn.close(); now = datetime.utcnow()
    msg = "👑 **แอดมินทั้งหมดในระบบ:**\n"
    for r in rows:
        rem = r[1] - now
        st = f"🟢 `{rem.days}d {rem.seconds//3600}h {(rem.seconds//60)%60}m`" if r[1] > now else "🔴 หมดอายุ"
        msg += f"• `{r[0]}`: {st}\n"
    await update.message.reply_text(msg if rows else "ℹ️ ไม่มีข้อมูล", parse_mode='Markdown')

# --- 📥 8. Message Handler (The Record Core) ---
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip(); match = re.match(r'^([+-])(\d+)$', text)
    if match:
        if not await is_allowed(update): return
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', (update.effective_chat.id, amt, update.message.from_user.first_name))
        conn.commit(); cursor.close(); conn.close()
        await send_summary(update, context)

# --- 🚀 9. Main Entrance ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(os.getenv('TOKEN')).build()
    
    # Register Commands
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
    
    # Message Listener
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    
    logging.info("Black Candy Bot is now running...")
    app.run_polling()
