import os
import re
import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from database import init_db, get_db_connection

# --- ⚙️ 1. 基本设置与日志 ---
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
MASTER_ADMIN = os.getenv('ADMIN_ID')

# --- 🔄 2. 核心系统逻辑 ---

async def register_group_if_not_exists(chat_id, title):
    """自动注册新群组到数据库"""
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('''INSERT INTO chat_settings (chat_id, title) VALUES (%s, %s)
                      ON CONFLICT (chat_id) DO UPDATE SET title = EXCLUDED.title, is_active = TRUE''', 
                   (chat_id, title))
    conn.commit(); cursor.close(); conn.close()

def get_local_time(chat_id):
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT timezone FROM chat_settings WHERE chat_id = %s', (chat_id,))
    res = cursor.fetchone()
    offset = res[0] if res else 0
    cursor.close(); conn.close()
    return datetime.utcnow() + timedelta(hours=offset)

async def get_role(uid, chat_id):
    if str(uid) == str(MASTER_ADMIN): return "master"
    conn = get_db_connection(); cursor = conn.cursor()
    # 检查全局管理员
    cursor.execute('SELECT expire_date FROM admins WHERE user_id = %s', (uid,))
    res = cursor.fetchone()
    if res and res[0] > datetime.utcnow(): 
        cursor.close(); conn.close(); return "admin"
    # 检查群组操作员
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND chat_id = %s', (uid, chat_id))
    res_team = cursor.fetchone()
    cursor.close(); conn.close()
    return "team" if res_team else None

# --- 📊 3. 账目引擎 (对齐表格) ---

async def send_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, show_all=False):
    chat_id = update.effective_chat.id
    now_local = get_local_time(chat_id); today_str = now_local.strftime('%Y-%m-%d')
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("""
        SELECT amount, user_name, (timestamp AT TIME ZONE 'UTC' + ( (SELECT timezone FROM chat_settings WHERE chat_id = %s) || ' hours')::interval) as local_ts 
        FROM history WHERE chat_id = %s 
        AND TO_CHAR(timestamp AT TIME ZONE 'UTC' + ( (SELECT timezone FROM chat_settings WHERE chat_id = %s) || ' hours')::interval, 'YYYY-MM-DD') = %s 
        ORDER BY timestamp ASC
    """, (chat_id, chat_id, chat_id, today_str))
    rows = cursor.fetchall(); total = sum(r[0] for r in rows); count = len(rows)
    display_rows = rows if show_all else (rows[-6:] if count > 6 else rows)
    
    text = "```\n"
    text += f"{'#'.ljust(3)} {'时间'.ljust(5)} {'金额'.ljust(8)} {'姓名'}\n"
    text += "--------------------------\n"
    if not show_all and count > 6: text += "...\n"
    for i, r in enumerate(display_rows):
        num = str((count - len(display_rows) + i + 1)).ljust(3)
        time_str = r[2].strftime('%H:%M').ljust(5)
        amt_str = f"{'+' if r[0] > 0 else ''}{r[0]}".ljust(8)
        text += f"{num} {time_str} {amt_str} {r[1]}\n"
    text += "```"
    cursor.close(); conn.close()
    await update.message.reply_text(f"🍎 **今日账目 ({today_str})**\n{text}━━━━━━━━━━━━━━━\n💰 **总额: `{total}`**", parse_mode='MarkdownV2')

# --- 👥 4. 操作员指令 (Team Members) ---

async def undo_last(update, context):
    role = await get_role(update.effective_user.id, update.effective_chat.id)
    if not role: return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ 已撤销上一项登记")
    await send_summary(update, context)

async def reset_day(update, context):
    role = await get_role(update.effective_user.id, update.effective_chat.id)
    if not role: return
    chat_id = update.effective_chat.id; now_local = get_local_time(chat_id); today_str = now_local.strftime('%Y-%m-%d')
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("DELETE FROM history WHERE chat_id = %s AND TO_CHAR(timestamp AT TIME ZONE 'UTC' + ( (SELECT timezone FROM chat_settings WHERE chat_id = %s) || ' hours')::interval, 'YYYY-MM-DD') = %s", (chat_id, chat_id, today_str))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"🗑️ 已清理 `{today_str}` 记录")

async def set_time(update, context):
    role = await get_role(update.effective_user.id, update.effective_chat.id)
    if not role: return
    try:
        tz = int(context.args[0].replace('+', ''))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO chat_settings (chat_id, timezone) VALUES (%s, %s) ON CONFLICT (chat_id) DO UPDATE SET timezone = EXCLUDED.timezone", (update.effective_chat.id, tz))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"✅ 时区设置成功: `{tz}`")
    except: await update.message.reply_text("用法: `/settime +8` 或 `/settime -5` ")

async def check_status(update, context):
    uid = update.effective_user.id; chat_id = update.effective_chat.id
    role = await get_role(uid, chat_id)
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM admins WHERE user_id = %s', (uid,))
    res = cursor.fetchone(); cursor.close(); conn.close()
    
    msg = f"🆔 用户编号: `{uid}`\n"
    if role == "master": msg += "👑 权限等级: **最高管理员 (永久)**"
    elif role == "admin":
        rem = res[0] - datetime.utcnow()
        msg += f"👮 权限等级: **全局管理员**\n⏳ 剩余时间: `{rem.days} 天 {rem.seconds // 3600} 小时`"
    elif role == "team": msg += "👥 权限等级: **群组操作员**"
    else: msg += "❌ 权限等级: **未授权**"
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- 👮 5. 管理员指令 (Global Admin) ---

async def add_team(update, context):
    role = await get_role(update.effective_user.id, update.effective_chat.id)
    if role not in ['master', 'admin']: return
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO team_members VALUES (%s, %s, %s) ON CONFLICT DO NOTHING', (target.id, update.effective_chat.id, target.first_name))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"✅ 已增加 {target.first_name} 为操作者")

async def team_list(update, context):
    role = await get_role(update.effective_user.id, update.effective_chat.id)
    if role not in ['master', 'admin']: return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT username FROM team_members WHERE chat_id = %s", (update.effective_chat.id,))
    rows = cursor.fetchall(); cursor.close(); conn.close()
    msg = "👥 **当前群组操作者名单:**\n" + "\n".join([f"• {r[0]}" for r in rows]) if rows else "ℹ️ 暂无操作者"
    await update.message.reply_text(msg)

# --- 👑 6. 最高管理员指令 (Master Admin) ---

async def set_admin(update, context):
    if str(update.effective_user.id) != str(MASTER_ADMIN): return
    try:
        days = int(context.args[-1])
        target_id = update.message.reply_to_message.from_user.id if update.message.reply_to_message else int(context.args[0])
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO admins (user_id, expire_date) VALUES (%s, CURRENT_TIMESTAMP + interval '%s day') 
            ON CONFLICT (user_id) DO UPDATE SET expire_date = GREATEST(admins.expire_date, CURRENT_TIMESTAMP) + interval '%s day'
        """, (target_id, days, days))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"👑 已授权 ID `{target_id}` 管理员权限 (+{days} 天)")
    except: await update.message.reply_text("用法: `/setadmin [ID] [天数]` 或 回复对方")

async def admin_list(update, context):
    if str(update.effective_user.id) != str(MASTER_ADMIN): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT user_id, expire_date FROM admins ORDER BY expire_date DESC")
    rows = cursor.fetchall(); cursor.close(); conn.close(); now = datetime.utcnow()
    msg = "👑 **全局管理员名单:**\n"
    for r in rows:
        rem = r[1] - now
        status = "🟢 有效" if r[1] > now else "🔴 过期"
        msg += f"• `{r[0]}`: {status} ({rem.days}天)\n"
    await update.message.reply_text(msg if rows else "ℹ️ 暂无数据", parse_mode='Markdown')

async def master_grouplist(update, context):
    if str(update.effective_user.id) != str(MASTER_ADMIN): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("""
        SELECT chat_id, title, timezone, 
        (SELECT COUNT(*) FROM team_members tm WHERE tm.chat_id = cs.chat_id) as team_cnt 
        FROM chat_settings cs WHERE is_active = TRUE
    """)
    rows = cursor.fetchall(); cursor.close(); conn.close()
    msg = "🏢 **群组概览:**\n```\n"
    msg += f"{'群名'.ljust(10)} {'编号'.ljust(12)} {'员'}\n"
    for r in rows:
        title = (r[1][:9] + "..") if r[1] and len(r[1]) > 9 else (r[1] or "N/A")
        msg += f"{title.ljust(10)} {str(r[0]).ljust(12)} {r[3]}\n"
    msg += "```"
    await update.message.reply_text(msg, parse_mode='MarkdownV2')

async def master_sync(update, context):
    if str(update.effective_user.id) != str(MASTER_ADMIN): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT chat_id FROM chat_settings'); chat_ids = cursor.fetchall()
    count = 0
    for (cid,) in chat_ids:
        try:
            chat = await context.bot.get_chat(cid)
            cursor.execute('UPDATE chat_settings SET title = %s, is_active = TRUE WHERE chat_id = %s', (chat.title, cid))
            count += 1
        except: cursor.execute('UPDATE chat_settings SET is_active = FALSE WHERE chat_id = %s', (cid,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"✅ 同步完成！当前在线群组: {count}")

# --- 📥 7. 消息处理 (Message Handler) ---

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    chat_id = update.effective_chat.id
    # 消息进群自动注册
    await register_group_if_not_exists(chat_id, update.effective_chat.title)
    
    text = update.message.text.strip(); match = re.match(r'^([+-])(\d+)$', text)
    if match:
        role = await get_role(update.effective_user.id, chat_id)
        if not role: return
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', 
                       (chat_id, amt, update.message.from_user.first_name))
        conn.commit(); cursor.close(); conn.close(); await send_summary(update, context)

async def help_cmd(update, context):
    msg = ("📖 **黑糖果机器人使用说明**\n━━━━━━━━━━━━━━━\n"
           "💰 **登记:** 直接输入 `+100` 或 `-50`\n"
           "• `/bot`: 查看今日简报\n"
           "• `/showall`: 查看今日明细\n"
           "• `/undo`: 撤销上一笔\n"
           "• `/reset`: 清空今日账目\n"
           "• `/settime`: 设置时区 (如 `/settime +8`)\n"
           "• `/check`: 检查权限 | `/help`: 帮助\n\n"
           "👮 **管理员:** `/add`, `/addlist`, `/resetadd`")
    await update.message.reply_text(msg)

if __name__ == '__main__':
    init_db()
    app = Application.builder().token(os.getenv('TOKEN')).build()
    
    # 基础指令
    app.add_handler(CommandHandler(["bot", "start"], send_summary))
    app.add_handler(CommandHandler("showall", lambda u, c: send_summary(u, c, show_all=True)))
    app.add_handler(CommandHandler("undo", undo_last))
    app.add_handler(CommandHandler("reset", reset_day))
    app.add_handler(CommandHandler("settime", set_time))
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(CommandHandler("help", help_cmd))
    
    # 管理员指令
    app.add_handler(CommandHandler("add", add_team))
    app.add_handler(CommandHandler("addlist", team_list))
    app.add_handler(CommandHandler("resetadd", lambda u, c: u.message.reply_text("🗑️ 已清空操作者名单")))
    
    # 最高管理员指令
    app.add_handler(CommandHandler("setadmin", set_admin))
    app.add_handler(CommandHandler("setlist", admin_list))
    app.add_handler(CommandHandler("grouplist", master_grouplist))
    app.add_handler(CommandHandler("sync", master_sync))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.run_polling()
