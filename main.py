import os
import re
import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from database import init_db, get_db_connection

# --- ⚙️ 1. Setup & Logging ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
MASTER_ADMIN = os.getenv('ADMIN_ID')

# --- ⚙️ 2. Timezone Management (Auto-Register Group) ---
def get_local_time(chat_id, utc_time=None):
    if utc_time is None:
        utc_time = datetime.utcnow()
    conn = get_db_connection(); cursor = conn.cursor()
    
    # ตรวจสอบกลุ่ม; หากไม่มีในฐานข้อมูล ให้ลงทะเบียนอัตโนมัติ (Default +0)
    cursor.execute('SELECT timezone FROM chat_settings WHERE chat_id = %s', (chat_id,))
    res = cursor.fetchone()
    
    if res is None:
        cursor.execute('INSERT INTO chat_settings (chat_id, timezone) VALUES (%s, 0)', (chat_id,))
        conn.commit()
        offset = 0
    else:
        offset = res[0]
        
    cursor.close(); conn.close()
    return utc_time + timedelta(hours=offset)
    
    # --- 🔄 2. Internal Sync Function (The Core) ---
async def register_group_if_not_exists(chat_id, context: ContextTypes.DEFAULT_TYPE):
    """ฟังก์ชันอัปเดตข้อมูลกลุ่มเข้า DB ทันที"""
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM chat_settings WHERE chat_id = %s', (chat_id,))
    if cursor.fetchone() is None:
        try:
            # พยายามดึงชื่อกลุ่มเพื่อความถูกต้อง
            chat = await context.bot.get_chat(chat_id)
            title = chat.title or "Private/Unknown"
            cursor.execute('INSERT INTO chat_settings (chat_id, timezone) VALUES (%s, 0)', (chat_id,))
            conn.commit()
            logging.info(f"✨ Auto-Synced New Group: {title} ({chat_id})")
        except Exception as e:
            logging.error(f"⚠️ Sync Error for {chat_id}: {e}")
    cursor.close(); conn.close()

# --- 🛡️ 3. Access Control (Global Master & Admin / Local Team) ---
async def is_allowed(update: Update):
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # 1. Master Admin (จาก ENV) - ใช้งานได้ทุกกลุ่ม
    if str(uid) == str(MASTER_ADMIN): return True
    
    conn = get_db_connection(); cursor = conn.cursor()
    
    # 2. แอดมินทั่วไป (Global - ใช้งานได้ทุกกลุ่มถ้าไม่หมดอายุ)
    cursor.execute('SELECT expire_date FROM admins WHERE user_id = %s', (uid,))
    res_admin = cursor.fetchone()
    if res_admin and res_admin[0] > datetime.utcnow():
        cursor.close(); conn.close(); return True
    
    # 3. ทีมงาน/ผู้ช่วยจด (Local - ใช้งานได้เฉพาะกลุ่มที่ถูกเพิ่ม)
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND chat_id = %s', (uid, chat_id))
    is_team = cursor.fetchone()
    
    cursor.close(); conn.close()
    return True if is_team else False

# --- 📊 4. Summary Engine (จัดช่องไฟให้ตรงเป๊ะ) ---
async def send_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, show_all=False):
    chat_id = update.effective_chat.id
    now_local = get_local_time(chat_id)
    today_str = now_local.strftime('%Y-%m-%d')
    
    conn = get_db_connection(); cursor = conn.cursor()
    # ดึงข้อมูลแยกกลุ่มชัดเจน พร้อมคำนวณเวลาท้องถิ่นโดยใช้ ::interval ป้องกัน SQL Error
    cursor.execute("""
        SELECT amount, user_name, (timestamp AT TIME ZONE 'UTC' + ( (SELECT timezone FROM chat_settings WHERE chat_id = %s) || ' hours')::interval) as local_ts 
        FROM history WHERE chat_id = %s 
        AND TO_CHAR(timestamp AT TIME ZONE 'UTC' + ( (SELECT timezone FROM chat_settings WHERE chat_id = %s) || ' hours')::interval, 'YYYY-MM-DD') = %s 
        ORDER BY timestamp ASC
    """, (chat_id, chat_id, chat_id, today_str))
    
    rows = cursor.fetchall(); total = sum(r[0] for r in rows); count = len(rows)
    display_rows = rows if show_all else (rows[-6:] if count > 6 else rows)
    
    # จัดระเบียบช่องไฟด้วย Monospace Code Block (```)
    history_text = "```\n"
    history_text += f"{'#'.ljust(3)} {'时间'.ljust(5)} {'金额'.ljust(8)} {'姓名'}\n"
    history_text += "--------------------------\n"
    if not show_all and count > 6: history_text += "...\n"
    
    for i, r in enumerate(display_rows):
        num = str((count - len(display_rows) + i + 1)).ljust(3)
        time_str = r[2].strftime('%H:%M').ljust(5)
        amt_str = f"{'+' if r[0] > 0 else ''}{r[0]}".ljust(8)
        history_text += f"{num} {time_str} {amt_str} {r[1]}\n"
    history_text += "```"

    cursor.close(); conn.close()
    await update.message.reply_text(
        f"🍎 **今日账目 ({today_str})**\n━━━━━━━━━━━━━━━\n{history_text}━━━━━━━━━━━━━━━\n💰 **总额: `{total}`**",
        parse_mode='MarkdownV2'
    )
    
# --- 🤖 5. Accounting Commands ---
async def help_cmd(update, context):
    msg = ("📖 **黑糖果机器人说明**\n━━━━━━━━━━━━━━━\n"
           "💰 **登记方式:** 输入 `+100` 或 `-50` 即可登记\n\n"
           "⚙️ **操控指令:**\n"
           "• `/bot` : 查看目前账单\n"
           "• `/undo` : 撤销上次登记\n"
           "• `/reset` : 清除今日所有登记\n"
           "• `/showall` : 查看所有登记\n"
           "• `/settime [+/-H]` : 设置时区 (如 `/settime +8`)\n\n"
           "👥 **人员管理:**\n"
           "• `/add` : 增加操作者 (Reply 对方)\n"
           "• `/addlist` : 查看操作者名单\n"
           "• `/resetadd` : 清除所有操作者\n\n"
           "👑 **管理员:**\n"
           "• `/check` : 查看权限及可用期\n"
           "• `/setadmin [ID/Reply] [天]` : 授权管理\n"
           "• `/setlist` : 查看所有管理员")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def undo_last(update, context):
    if not await is_allowed(update): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ 已撤销上一项登记")
    await send_summary(update, context)

async def reset_day(update, context):
    if not await is_allowed(update): return
    chat_id = update.effective_chat.id; now_local = get_local_time(chat_id); today_str = now_local.strftime('%Y-%m-%d')
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM history WHERE chat_id = %s 
        AND TO_CHAR(timestamp AT TIME ZONE 'UTC' + ( (SELECT timezone FROM chat_settings WHERE chat_id = %s) || ' hours')::interval, 'YYYY-MM-DD') = %s
    """, (chat_id, chat_id, today_str))
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
        await update.message.reply_text(f"✅ 已设置时区! 当前时间: `{new_time.strftime('%H:%M:%S')}`")
    except: await update.message.reply_text("用法: `/settime +8` หรือ `/settime -8` ")

# --- 👥 6. Team Members Management ---
async def add_member(update, context):
    if not await is_allowed(update): return
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user.id
        name = update.message.reply_to_message.from_user.first_name
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO team_members VALUES (%s, %s, %s) ON CONFLICT (member_id, chat_id) DO UPDATE SET username = EXCLUDED.username", (target, update.effective_chat.id, name))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"✅ 已成功增加 {name} 为本群操作者")
    else: await update.message.reply_text("⚠️ 请回复需要设置的人的消息，并输入 `/add` ")

async def add_list(update, context):
    if not await is_allowed(update): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT username, member_id FROM team_members WHERE chat_id = %s", (update.effective_chat.id,))
    rows = cursor.fetchall(); cursor.close(); conn.close()
    msg = "👥 **本群操作者名单:**\n" + "\n".join([f"{i+1}. {r[0]} (`{r[1]}`)" for i, r in enumerate(rows)]) if rows else "ℹ️ 没有设置操作者"
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- 👑 7. Admin & Master System ---
async def check_status(update, context):
    uid = update.effective_user.id; conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM admins WHERE user_id = %s', (uid,))
    res = cursor.fetchone(); cursor.close(); conn.close()
    if str(uid) == str(MASTER_ADMIN): 
        msg = f"🆔 ID: `{uid}`\n👑 权限: **最高管理员 (MASTER)**"
    elif res:
        rem = res[0] - datetime.utcnow()
        if rem.total_seconds() > 0:
            msg = f"🆔 ID: `{uid}`\n⏳ 管理员有效期: `{rem.days} 天 {rem.seconds // 3600} 小时 {(rem.seconds // 60) % 60} 分钟`"
        else: msg = f"🆔 ID: `{uid}`\n❌ 权限已过期"
    else: msg = f"🆔 ID: `{uid}`\n❌ 无权限等级"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def set_admin(update, context):
    if str(update.effective_user.id) != str(MASTER_ADMIN): return
    try:
        days = int(context.args[-1]); target_id = None
        if update.message.reply_to_message: target_id = update.message.reply_to_message.from_user.id
        else: target_id = int(context.args[0])
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO admins (user_id, expire_date) VALUES (%s, CURRENT_TIMESTAMP + interval '%s day') 
            ON CONFLICT (user_id) DO UPDATE SET expire_date = GREATEST(admins.expire_date, CURRENT_TIMESTAMP) + interval '%s day'
        """, (target_id, days, days))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"👑 已增加 ID `{target_id}` 权限 `{days}` 天")
    except: await update.message.reply_text("用法: `/setadmin [ID] [天]` หรือ Reply 对方")

async def set_list(update, context):
    if str(update.effective_user.id) != str(MASTER_ADMIN): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("""
        SELECT a.user_id, a.expire_date, COALESCE(t.username, 'Unknown') 
        FROM admins a LEFT JOIN (SELECT DISTINCT ON (member_id) member_id, username FROM team_members) t 
        ON a.user_id = t.member_id ORDER BY a.expire_date DESC
    """)
    rows = cursor.fetchall(); cursor.close(); conn.close(); now = datetime.utcnow()
    msg = "👑 **管理员名单:**\n```\n"
    msg += f"{'ID'.ljust(11)} {'Name'.ljust(10)} {'Status'}\n"
    msg += "------------------------------\n"
    for r in rows:
        rem = r[1] - now
        name = (r[2][:9] + '..') if len(r[2]) > 9 else r[2].ljust(10)
        status = f"{rem.days}d {rem.seconds//3600}h" if r[1] > now else "Expired"
        msg += f"{str(r[0]).ljust(11)} {name} {status}\n"
    msg += "```"
    await update.message.reply_text(msg if rows else "ℹ️ 无数据", parse_mode='MarkdownV2')

# --- 📥 8. Message Handler (The Record Core) ---
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.strip(); match = re.match(r'^([+-])(\d+)$', text)
    if match:
        if not await is_allowed(update): return
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', 
                       (update.effective_chat.id, amt, update.message.from_user.first_name))
        conn.commit(); cursor.close(); conn.close()
        await send_summary(update, context)
# --- 👑 6. Master Commands (Sync & Manage) ---

async def group_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/grouplist: ดูรายชื่อทุกกลุ่มที่บอทไปแฝงตัวอยู่และบันทึกไว้ใน DB"""
    if str(update.effective_user.id) != str(MASTER_ADMIN): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("""
        SELECT cs.chat_id, cs.timezone, 
        (SELECT COUNT(*) FROM team_members tm WHERE tm.chat_id = cs.chat_id) as team_cnt,
        (SELECT COUNT(*) FROM history h WHERE h.chat_id = cs.chat_id AND h.timestamp > NOW() - INTERVAL '1 day') as activity
        FROM chat_settings cs
    """)
    rows = cursor.fetchall(); cursor.close(); conn.close()
    
    msg = "🏢 **Master Group Control Center**\n```\n"
    msg += f"{'Chat ID'.ljust(15)} {'TZ'.ljust(4)} {'T'.ljust(2)} {'Act'}\n"
    msg += "------------------------------\n"
    for r in rows:
        # พยายามดึงชื่อกลุ่ม (Title) มาแสดง
        try:
            chat = await context.bot.get_chat(r[0])
            title = (chat.title[:10] + "..") if chat.title and len(chat.title) > 10 else (chat.title or "N/A")
        except: title = "Locked/Left"
        msg += f"{str(r[0]).ljust(15)} {str(r[1]).ljust(4)} {str(r[2]).ljust(2)} {r[3]}\n"
    msg += "```\n*Act = จำนวนรายการจดใน 24 ชม.*"
    await update.message.reply_text(msg, parse_mode='MarkdownV2')

# --- 🚀 9. Main Entrance ---
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
    app.add_handler(CommandHandler("grouplist", group_list))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    
    logging.info("Black Candy Bot is now running...")
    app.run_polling()
