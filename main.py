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
    
    history_text = "📋 **记录:**\n" if show_all else ("...\n" if count > 6 else "")
    
    for i, r in enumerate(display_rows):
        num = (count - len(display_rows) + i + 1)
        time_str = r[2].strftime('%H:%M')
        history_text += f"{num:<3} {time_str:<6} \t\t{r[0]} ({r[1]})\n"

    cursor.close(); conn.close()
    await update.message.reply_text(
        f"🍎 **今日账目 ({today_str})**\n━━━━━━━━━━━━━━━\n{history_text}━━━━━━━━━━━━━━━\n💰 **总额: {total}**",
        parse_mode='Markdown'
    )
    
# --- 🤖 5. คำสั่งจัดการบัญชี (Accounting) ---
async def help_cmd(update, context):
    msg = ("📖 **黑糖果机器人说明**\n━━━━━━━━━━━━━━━\n"
           "💰 **登记方式** 输入 `+100` 或 `-50` 机器人会自动登记，但是需要权限等级：管理员 或 被设置为操作者\n\n"
           "⚙️ **操控指令:**\n• `/bot` : 查看目前账单（呼叫机器人）\n• `/undo` : 撤销上一项登记\n• `/reset` : 清除今天所有登记\n• `/showall` : 查看所有登记\n• `/settime [+/-เลข]` : 设置登记账单时间 (例如 `/settime +8`)\n\n"
           "👥 **人员设置:**\n• `/add` : 增加操作人（让需要增加的人在群里随便发一个信息，然后有权限的人回复 `/add`\n• `/addlist` : 查看操作者名单\n• `/resetadd` : 清除所有操作者\n\n"
           "👑 **管理员:**\n• `/check` : 查看权限及可用期\n")
           #• `/setadmin [天]` : เพิ่มวันแอดมิน (สะสมวันได้)\n• `/setlist` : ดูรายชื่อแอดมินทั้งหมด")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def undo_last(update, context):
    if not await is_allowed(update): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ 已撤销登记")
    await send_summary(update, context)

async def reset_day(update, context):
    if not await is_allowed(update): return
    chat_id = update.effective_chat.id; now_local = get_local_time(chat_id); today_str = now_local.strftime('%Y-%m-%d')
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("DELETE FROM history WHERE chat_id = %s AND TO_CHAR(timestamp AT TIME ZONE 'UTC' + ( (SELECT timezone FROM chat_settings WHERE chat_id = %s) || ' hours')::interval, 'YYYY-MM-DD') = %s", (chat_id, chat_id, today_str))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"🗑️ 已清理 `{today_str}` 记录")

async def set_time(update, context):
    if not await is_allowed(update): return
    try:
        tz = int(context.args[0].replace('+', ''))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO chat_settings (chat_id, timezone) VALUES (%s, %s) ON CONFLICT (chat_id) DO UPDATE SET timezone = EXCLUDED.timezone", (update.effective_chat.id, tz))
        conn.commit(); cursor.close(); conn.close()
        new_time = get_local_time(update.effective_chat.id)
        await update.message.reply_text(f"✅ 已设置时间! `{new_time.strftime('%H:%M:%S')}`")
    except: await update.message.reply_text("用: `/settime +8` 或者 `/settime -8` ")

# --- 👥 6. จัดการทีมงาน (Team Members) ---
async def add_member(update, context):
    if not await is_allowed(update): return
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user.id
        name = update.message.reply_to_message.from_user.first_name
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO team_members VALUES (%s, %s, %s) ON CONFLICT (member_id, chat_id) DO UPDATE SET username = EXCLUDED.username", (target, update.effective_chat.id, name))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"✅ 增加 {name} 成操作者")
    else: await update.message.reply_text("⚠️ 用回复的方式来设置，用`/add`来回复需要设置的人 ")

async def add_list(update, context):
    if not await is_allowed(update): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT username, member_id FROM team_members WHERE chat_id = %s", (update.effective_chat.id,))
    rows = cursor.fetchall(); cursor.close(); conn.close()
    msg = "👥 **操作者名单:**\n" + "\n".join([f"{i+1}. {r[0]} (`{r[1]}`)" for i, r in enumerate(rows)]) if rows else "ℹ️ 没有设置操作者"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def reset_add(update, context):
    if not await is_allowed(update): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("DELETE FROM team_members WHERE chat_id = %s", (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("🗑️ 已清除所有操作者")

# --- 👑 7. ระบบ Admin & MASTER (Privileged) ---
async def check_status(update, context):
    uid = update.effective_user.id; conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM admins WHERE user_id = %s', (uid,))
    res = cursor.fetchone(); cursor.close(); conn.close()
    if str(uid) == str(MASTER_ADMIN): msg = f"🆔 用户编号：`{uid}`\n👑 权限等级：**最高管理员（永久有效）**"
    elif res:
        rem = res[0] - datetime.utcnow()
        if rem.total_seconds() > 0:
            msg = f"🆔 用户编号: `{uid}`\n⏳ 权限等级:管理员 可用 `{rem.days} 天 {rem.seconds // 3600} 小时 {(rem.seconds // 60) % 60} 分钟`"
        else: msg = f"🆔 用户编号: `{uid}`\n❌ 权限等级:管理员 **已过期**"
    else: msg = f"🆔 用户编号: `{uid}`\n❌ 权限等级:没有开通"
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
        await update.message.reply_text(f"🆔 用户编号 `{target_id}` \t已增加 `{days}` 天使用期")
    except: await update.message.reply_text("用: `/setadmin [ID] [天]` 或者用回复的方式然后输入天数")

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
