import os
import re
import logging
import tempfile
from decimal import Decimal
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from database import get_db_connection, init_db
from telegram import InlineKeyboardMarkup, InlineKeyboardButton


TOKEN = os.getenv("TOKEN")
MASTER_ID = os.getenv("MASTER_ID")

if not TOKEN:
    raise ValueError("TOKEN not set")
if not MASTER_ID:
    raise ValueError("MASTER_ID not set")

logging.basicConfig(level=logging.INFO)
# ==============================
# 开始 联系卖家
# ==============================

async def start_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    text = (
        "🍬 黑糖果机器人\n"
        "━━━━━━━━━━━━━━━\n"
        "需要开通请联系: @Mbcdcandy\n\n"
        "💰 价格说明:\n"
        "90U 使用期 30 天\n"
        "或 可自定义使用期\n"
        "例如: 10天 / 15天 / 20天\n\n"
        "🎁 试用:\n"
        "可以联系 @Mbcdcandy 开通试用期\n\n"
        "━━━━━━━━━━━━━━━\n"
        "🆔 你的ID:\n"
        f"{user_id}\n\n"
        "📩 请将此ID发送给卖家\n"
        "🔐 卖家会通过 ID 设置机器人"
    )

    await update.message.reply_text(text)
# ==============================
# 开始（完整状态面板）
# ==============================
async def starts_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    ensure_chat_settings(chat_id)

    conn = get_db_connection()
    cursor = conn.cursor()

    # 读取时区和工作时间
    cursor.execute("""
        SELECT timezone, work_start
        FROM chat_settings
        WHERE chat_id=%s
    """, (chat_id,))
    tz, work_start = cursor.fetchone()

    # 当前时间
    now_utc = datetime.utcnow()
    now_local = now_utc + timedelta(hours=tz)

    # 当前工作轮次
    start_utc, end_utc, _ = get_work_period(chat_id)
    start_local = start_utc + timedelta(hours=tz)
    end_local = end_utc + timedelta(hours=tz)

    # 操作者数量
    cursor.execute("""
        SELECT COUNT(*) FROM team_members
        WHERE chat_id=%s
    """, (chat_id,))
    operator_count = cursor.fetchone()[0]

    # 本轮记录数量
    cursor.execute("""
        SELECT COUNT(*) FROM history
        WHERE chat_id=%s
        AND timestamp BETWEEN %s AND %s
    """, (chat_id, start_utc, end_utc))
    record_count = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    record_status = "有记录 📊" if record_count > 0 else "暂无记录 📭"

    text = (
        "🤖 机器人已开始记账\n"
        "━━━━━━━━━━━━━━━\n"
        f"目前时区: UTC{tz:+}\n"
        f"目前时间: {now_local.strftime('%Y-%m-%d %H:%M:%S')}\n"
        "\n"
        "今天开始记账至记账结束:\n"
        f"{start_local.strftime('%Y-%m-%d %H:%M')}  →  "
        f"{end_local.strftime('%Y-%m-%d %H:%M')}\n"
        "━━━━━━━━━━━━━━━"
    )

    await update.message.reply_text(text)
    await send_summary(update, context)
    
# ==============================
# 帮助菜单
# ==============================

async def help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 机器人指令说明\n"
        "━━━━━━━━━━━━━━━\n"
        "/start 或 /开始 - 查看系统状态\n"
        "/report 或 /账单 - 查看当前账单\n"
        "/all 或 /全部 - 查看全部记录\n"
        "/undo 或 /撤销 - 撤销上一条\n"
        "/reset 或 /重置 - 重置当前轮次\n"
        "\n"
        "👥 Owner 功能\n"
        "/add 或 /添加 - 用回复的方式来回复需要增加的操纵人\n"
        "/remove 或 /删除 - 用回复的方式来回复需要移除的操纵人\n"
        "/timezone 或 /设置时区 - 设置记账时间 例如：/timezone +8\n"
        "/worktime 或 /设置时间 - 设置开始记账到结束的时间 例如：/worktime 14:00\n"
        "━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(text)
# ==============================
# 权限系统
# ==============================

async def is_master(update: Update):
    return str(update.effective_user.id) == str(MASTER_ID)


async def is_owner(update: Update):
    if await is_master(update):
        return True

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT expire_date FROM admins WHERE user_id=%s",
                   (update.effective_user.id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    return row and row[0] > datetime.utcnow()


async def is_operator(update: Update):
    if await is_owner(update):
        return True

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 1 FROM team_members
        WHERE member_id=%s AND chat_id=%s
    """, (update.effective_user.id, update.effective_chat.id))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    return bool(row)

# ==============================
# 工作时间段
# ==============================

def ensure_chat_settings(chat_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM chat_settings WHERE chat_id=%s", (chat_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO chat_settings (chat_id) VALUES (%s)", (chat_id,))
        conn.commit()
    cursor.close()
    conn.close()


def get_work_period(chat_id):
    ensure_chat_settings(chat_id)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT timezone, work_start FROM chat_settings WHERE chat_id=%s",
                   (chat_id,))
    tz, work_start = cursor.fetchone()
    cursor.close()
    conn.close()

    now_utc = datetime.utcnow()
    now_local = now_utc + timedelta(hours=tz)

    today_start = datetime.combine(now_local.date(), work_start)
    if now_local < today_start:
        today_start -= timedelta(days=1)

    start_utc = today_start - timedelta(hours=tz)
    end_utc = start_utc + timedelta(days=1)

    return start_utc, end_utc, tz

# ==============================
# 账单显示
# ==============================

async def send_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, show_all=False):
    chat_id = update.effective_chat.id
    start_utc, end_utc, tz = get_work_period(chat_id)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT amount, user_name, timestamp
        FROM history
        WHERE chat_id=%s
        AND timestamp BETWEEN %s AND %s
        ORDER BY timestamp ASC
    """, (chat_id, start_utc, end_utc))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        await update.message.reply_text("📋 今天没有记录")
        return

    total = sum(Decimal(r[0]) for r in rows)

    display = rows if show_all else rows[-6:]
    start_index = len(rows) - len(display) + 1

    def fmt(n: Decimal):
        return f"{n:,.2f}".rstrip("0").rstrip(".")

    text = "📋 今天记录:\n━━━━━━━━━━━━━━━\n"
    # เพิ่มส่วนนี้: ถ้าไม่ได้โชว์ทั้งหมด และจำนวนแถวมีมากกว่า 6 ให้ใส่ ...
    if not show_all and len(rows) > 6:
        text += "  ...\n"
    for i, r in enumerate(display):
        local_time = r[2] + timedelta(hours=tz)
        # แสดงลำดับที่ + เวลา | จำนวนเงิน
        text += f"{start_index + i}. {local_time.strftime('%H:%M')} | {fmt(Decimal(r[0]))}  ({r[1]}) \n" 
        #text += f"{start_index + i}. {local_time.strftime('%H:%M')} | {fmt(Decimal(r[0]))} ({r[1]})\n"



    text += "━━━━━━━━━━━━━━━\n"
    text += f"**合计: {fmt(total)}**\n\n"

    
   
    # ====== สรุปแยกตามคน ======
    person_summary = {}
    for amount, user_name, _ in rows:
        amount = Decimal(amount)
        if user_name not in person_summary:
            person_summary[user_name] = {"count": 0, "total": Decimal("0")}
        person_summary[user_name]["count"] += 1
        person_summary[user_name]["total"] += amount

    # ⭐ เรียงจากยอดรวมมาก → น้อย
    sorted_people = sorted(
        person_summary.items(),
        key=lambda x: x[1]["total"],
        reverse=True
    )

    text += "👤 按人统计:\n"
    for name, data in sorted_people:
        text += f"{name} | {data['count']} 笔 | {fmt(data['total'])}\n"

     # ส่งข้อความ
    await update.message.reply_text(text, parse_mode='Markdown')
    #await update.message.reply_text(text)
# ==============================
# 记账
# ==============================

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_operator(update):
        return

    text = update.message.text.strip()

    # รับเฉพาะ +xx หรือ -xx
    match = re.match(r'^([+-])\s*([\d,]+(?:\.\d{1,2})?)$', text)
    if not match:
        return

    sign = match.group(1)
    number_str = match.group(2).replace(",", "")
    amount = Decimal(number_str)

    if sign == "-":
        amount = -amount

    # === เลือกชื่อ ===
    # ถ้า reply ใคร → ใช้ชื่อคนนั้น
    if update.message.reply_to_message:
        user_name = update.message.reply_to_message.from_user.first_name
    else:
        user_name = update.message.from_user.first_name

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO history (chat_id, amount, user_name) VALUES (%s,%s,%s)",
        (update.effective_chat.id, amount, user_name)
    )
    conn.commit()
    cursor.close()
    conn.close()

    # ส่งกลับเฉพาะ summary
    await send_summary(update, context)

# ==============================
# 撤销
# ==============================

async def undo_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_operator(update):
        return

    chat_id = update.effective_chat.id
    start_utc, end_utc, _ = get_work_period(chat_id)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, amount FROM history
        WHERE chat_id=%s
        AND timestamp BETWEEN %s AND %s
        ORDER BY timestamp DESC LIMIT 1
    """, (chat_id, start_utc, end_utc))
    row = cursor.fetchone()

    if not row:
        await update.message.reply_text("⚠️ 当前没有可撤销的记录")
        cursor.close(); conn.close()
        return

    cursor.execute("DELETE FROM history WHERE id=%s", (row[0],))
    conn.commit()
    cursor.close()
    conn.close()

    await update.message.reply_text(f"↩️ 已撤销记录: {row[1]}")
    await send_summary(update, context)

# ==============================
# 重置
# ==============================

async def reset_current(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_operator(update):
        return

    chat_id = update.effective_chat.id
    start_utc, end_utc, _ = get_work_period(chat_id)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM history
        WHERE chat_id=%s
        AND timestamp BETWEEN %s AND %s
    """, (chat_id, start_utc, end_utc))
    conn.commit()
    cursor.close()
    conn.close()

    await update.message.reply_text("🗑️ 今天已清空")
    await send_summary(update, context)

# ==============================
# 添加操作者
# ==============================

async def add_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_owner(update):
        return

    target = None

    # ====== แบบ reply ======
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user

    # ====== แบบ /添加 @username ======
    elif context.args:
        username = context.args[0].lstrip("@")

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT member_id, username
            FROM team_members
            WHERE chat_id=%s AND username=%s
        """, (update.effective_chat.id, username))
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row:
            await update.message.reply_text("⚠️ 找不到该用户，请先让他在群里说话一次")
            return

        # สร้าง object จำลองให้เหมือน user
        class DummyUser:
            def __init__(self, id, first_name):
                self.id = id
                self.first_name = first_name

        target = DummyUser(row[0], row[1])

    else:
        await update.message.reply_text("⚠️ 请回复用户 或 使用: /添加 @username")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO team_members (member_id, chat_id, username)
        VALUES (%s,%s,%s)
        ON CONFLICT (member_id, chat_id)
        DO UPDATE SET username=%s
    """, (target.id, update.effective_chat.id,
          target.first_name, target.first_name))
    conn.commit()
    cursor.close()
    conn.close()

    await update.message.reply_text(f"✅ 已添加操作人: {target.first_name}")
# ==============================
# 删除操作者
# ==============================

async def remove_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_owner(update):
        return

    target_id = None
    target_name = None

    # ====== แบบ reply ======
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        target_id = user.id
        target_name = user.first_name

    # ====== แบบ /删除 @username ======
    elif context.args:
        username = context.args[0].lstrip("@")

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT member_id, username
            FROM team_members
            WHERE chat_id=%s AND username=%s
        """, (update.effective_chat.id, username))
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row:
            await update.message.reply_text("⚠️ 找不到该用户，或该用户不是操作者")
            return

        target_id = row[0]
        target_name = row[1]

    else:
        await update.message.reply_text("⚠️ 请回复用户 或 使用: /删除 @username")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM team_members
        WHERE member_id=%s AND chat_id=%s
    """, (target_id, update.effective_chat.id))
    conn.commit()
    cursor.close()
    conn.close()

    await update.message.reply_text(f"🗑️ 已删除操作人: {target_name}")

# ==============================
# 设置时区
# ==============================

async def set_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_owner(update):
        return

    # ถ้ามาจาก /timezone ใช้ context.args
    if context.args:
        arg = context.args[0]
    else:
        # ถ้ามาจาก /设置时区 ดึงจากข้อความเอง
        parts = update.message.text.split()
        if len(parts) < 2:
            await update.message.reply_text("用法: /设置时区 +8")
            return
        arg = parts[1]

    try:
        tz = int(arg)
    except:
        await update.message.reply_text("用法: /设置时区 +8")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO chat_settings (chat_id, timezone)
        VALUES (%s,%s)
        ON CONFLICT (chat_id)
        DO UPDATE SET timezone=%s
    """, (update.effective_chat.id, tz, tz))
    conn.commit()
    cursor.close()
    conn.close()

    # ====== เพิ่ม 目前时间 ======
    now_utc = datetime.utcnow()
    now_local = now_utc + timedelta(hours=tz)

    await update.message.reply_text(
        f"✅ 时区已设置为 UTC{tz:+}\n"
        f"目前时间: {now_local.strftime('%Y-%m-%d %H:%M:%S')}"
    )

# ==============================
# 设置时间
# ==============================

async def set_worktime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_owner(update):
        return

    # ถ้ามาจาก /worktime ใช้ context.args
    if context.args:
        time_str = context.args[0]
    else:
        # ถ้ามาจาก /设置时间 ดึงจากข้อความเอง
        parts = update.message.text.split()
        if len(parts) < 2:
            await update.message.reply_text("用法: /设置时间 14:00")
            return
        time_str = parts[1]

    try:
        datetime.strptime(time_str, "%H:%M")
    except:
        await update.message.reply_text("用法: /设置时间 14:00")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO chat_settings (chat_id, work_start)
        VALUES (%s,%s)
        ON CONFLICT (chat_id)
        DO UPDATE SET work_start=%s
    """, (update.effective_chat.id, time_str, time_str))
    conn.commit()

    # 取出当前时区
    cursor.execute("SELECT timezone FROM chat_settings WHERE chat_id=%s",
                   (update.effective_chat.id,))
    tz = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    # 计算目前时间
    now_utc = datetime.utcnow()
    now_local = now_utc + timedelta(hours=tz)

    # 计算记账开始与结束时间
    start_time = datetime.combine(
        now_local.date(),
        datetime.strptime(time_str, "%H:%M").time()
    )
    end_time = start_time + timedelta(days=1)

    await update.message.reply_text(
        f"✅ 工作时间设置为 {time_str}\n"
        f"目前时间: {now_local.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"每日记账开始至结束时间:\n"
        f"今天{start_time.strftime('%Y-%m-%d %H:%M')} → 明天{end_time.strftime('%Y-%m-%d %H:%M')}"
    )
# ==============================
# 权限检查
# ==============================

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Master
    if await is_master(update):
        await update.message.reply_text(
            f"🆔 ID: {user_id}\n"
            "👑 身份: Master\n"
            "权限: 最高权限"
        )
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    # Owner
    cursor.execute(
        "SELECT expire_date FROM admins WHERE user_id=%s",
        (user_id,)
    )
    row = cursor.fetchone()

    if row and row[0] > datetime.utcnow():
        remaining = row[0] - datetime.utcnow()

        total_seconds = int(remaining.total_seconds())

        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60

        cursor.close()
        conn.close()

        await update.message.reply_text(
            f"🆔 ID: {user_id}\n"
            "👑 身份: Owner\n"
            f"剩余时间: {days} 天 {hours} 小时 {minutes} 分钟"
        )
        return

    # Operator
    cursor.execute("""
        SELECT 1 FROM team_members
        WHERE member_id=%s AND chat_id=%s
    """, (user_id, update.effective_chat.id))

    if cursor.fetchone():
        cursor.close()
        conn.close()

        await update.message.reply_text(
            f"🆔 ID: {user_id}\n"
            "👥 身份: 操作者"
        )
        return

    cursor.close()
    conn.close()

    # 普通成员
    await update.message.reply_text(
        f"🆔 ID: {user_id}\n"
        "❌ 身份: 普通成员\n"
        "无操作权限"
    )

# ==============================
# Master 续费
# ==============================

async def renew_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_master(update):
        return

    try:
        if update.message.reply_to_message:
            target_id = update.message.reply_to_message.from_user.id
            days = int(context.args[0])
        else:
            target_id = int(context.args[0])
            days = int(context.args[1])
    except:
        await update.message.reply_text("用法: /续费 用户ID 天数 或 回复用户 /续费 天数")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT expire_date FROM admins WHERE user_id=%s", (target_id,))
    row = cursor.fetchone()

    now = datetime.utcnow()
    if row and row[0] > now:
        new_expire = row[0] + timedelta(days=days)
    else:
        new_expire = now + timedelta(days=days)

    cursor.execute("""
        INSERT INTO admins (user_id, expire_date)
        VALUES (%s,%s)
        ON CONFLICT (user_id)
        DO UPDATE SET expire_date=%s
    """, (target_id, new_expire, new_expire))

    conn.commit()
    cursor.close()
    conn.close()

    await update.message.reply_text(
        f"✅ 已续费 {days} 天\n到期时间: {new_expire.strftime('%Y-%m-%d %H:%M')}"
    )

# ==============================
# 查看用户列表（按群名，仅 Master）
# ==============================

# ==============================
# 查看用户列表（按群显示 Owners + Operators，仅 Master）
# ==============================

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_master(update):
        return

    bot = context.bot
    conn = get_db_connection()
    cursor = conn.cursor()

    now = datetime.utcnow()

    lines = []
    lines.append("用户列表（按群）")
    lines.append("━━━━━━━━━━━━━━━")

    # ===== Owners =====
    cursor.execute("SELECT user_id, expire_date FROM admins ORDER BY expire_date DESC")
    owners = cursor.fetchall()

    owners_info = []
    for uid, exp in owners:
        try:
            user = await bot.get_chat(uid)
            name = user.first_name or str(uid)
        except:
            name = str(uid)

        if exp > now:
            remain = exp - now
            days = remain.days
            hours = remain.seconds // 3600
            status = f"🟢 剩余: {days}天 {hours}小时"
        else:
            status = "🔴 已过期"

        owners_info.append((name, uid, status))

    # ===== Operators 按群 =====
    cursor.execute("""
        SELECT chat_id, member_id, username
        FROM team_members
        ORDER BY chat_id
    """)
    rows = cursor.fetchall()

    groups = {}
    for chat_id, member_id, username in rows:
        if chat_id not in groups:
            groups[chat_id] = []
        groups[chat_id].append((member_id, username))

    # ===== 生成文本 =====
    for chat_id, members in groups.items():
        try:
            chat = await bot.get_chat(chat_id)
            group_name = chat.title or str(chat_id)
        except:
            group_name = "未知群"

        lines.append(f"\n群: {group_name}")
        lines.append(f"群ID: {chat_id}")

        lines.append("Owners:")
        if owners_info:
            for name, uid, status in owners_info:
                lines.append(f"  {name} ({uid}) | {status}")
        else:
            lines.append("  （无）")

        lines.append("Operators:")
        if members:
            for mid, uname in members:
                lines.append(f"  {uname} ({mid})")
        else:
            lines.append("  （无）")

    cursor.close()
    conn.close()

    content = "\n".join(lines)

    # ===== 写入临时文件 =====
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as f:
        f.write(content)
        file_path = f.name

    # ===== 发送文件 =====
    await update.message.reply_document(
        document=open(file_path, "rb"),
        filename="users.txt",
        caption="📄 用户列表（按群）"
    )

    os.remove(file_path)

# ==============================
# Master 选择要清空的群（显示群名，不在群则显示 chat_id）
# ==============================

async def clearall_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_master(update):
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT DISTINCT chat_id FROM history ORDER BY chat_id")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        await update.message.reply_text("📭 当前没有任何历史数据")
        return

    keyboard = []

    for (chat_id,) in rows:
        try:
            chat = await context.bot.get_chat(chat_id)
            title = chat.title if chat.title else str(chat_id)
        except:
            title = str(chat_id)

        keyboard.append([
            InlineKeyboardButton(f"🗑️ {title}", callback_data=f"ask:{chat_id}")
        ])

    keyboard.append([
        InlineKeyboardButton("🔥 删除全部", callback_data="ask_all"),
        InlineKeyboardButton("❎ 取消", callback_data="cancel")
    ])

    await update.message.reply_text(
        "⚠️ 请选择要清空的群：",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==============================
# 处理清空按钮（双重确认）
# ==============================

async def clearall_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not await is_master(update):
        return

    data = query.data

    conn = get_db_connection()
    cursor = conn.cursor()

    # ❎ ยกเลิก
    if data == "cancel":
        await query.edit_message_text("❎ 已取消操作")
        cursor.close(); conn.close()
        return

    # ====== ขอ CONFIRM สำหรับกลุ่มเดียว ======
    if data.startswith("ask:"):
        chat_id = data.split(":")[1]

        try:
            chat = await context.bot.get_chat(chat_id)
            title = chat.title if chat.title else chat_id
        except:
            title = chat_id

        keyboard = [
            [
                InlineKeyboardButton("⚠️ 确认清空", callback_data=f"confirm:{chat_id}"),
                InlineKeyboardButton("❎ 取消", callback_data="cancel")
            ]
        ]

        await query.edit_message_text(
            f"⚠️ 确认要清空该群的历史记录吗？\n\n{title}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        cursor.close(); conn.close()
        return

    # ====== ขอ CONFIRM สำหรับ全部 ======
    if data == "ask_all":
        keyboard = [
            [
                InlineKeyboardButton("🔥 确认清空全部", callback_data="confirm_all"),
                InlineKeyboardButton("❎ 取消", callback_data="cancel")
            ]
        ]
        await query.edit_message_text(
            "⚠️ 确认要清空【所有群】的历史记录吗？",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        cursor.close(); conn.close()
        return

    # ====== ลบจริง (กลุ่มเดียว) ======
    if data.startswith("confirm:"):
        chat_id = data.split(":")[1]
        cursor.execute("DELETE FROM history WHERE chat_id=%s", (chat_id,))
        conn.commit()
        await query.edit_message_text("🗑️ 已清空该群的历史记录")
        cursor.close(); conn.close()
        return

    # ====== ลบจริง (ทั้งหมด) ======
    if data == "confirm_all":
        cursor.execute("DELETE FROM history")
        conn.commit()
        await query.edit_message_text("🔥 已清空【全部群】的历史记录")
        cursor.close(); conn.close()
        return

# ==============================
# 启动
# ==============================

if __name__ == "__main__":
    init_db()

    app = Application.builder().token(TOKEN).build()

    # 中文命令处理
    # ==============================
    # 开始
    app.add_handler(CommandHandler("start", start_bot))
    # 状态
    app.add_handler(CommandHandler("starts", starts_bot))
    app.add_handler(MessageHandler(filters.Regex(r"^/开始$"), starts_bot))

    # 帮助
    app.add_handler(CommandHandler("help", help_menu))
    app.add_handler(MessageHandler(filters.Regex(r"^/帮助$"), help_menu))
    
    # 检查
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(MessageHandler(filters.Regex(r"^/权限检查$"), check_status))

    # 账单
    app.add_handler(CommandHandler("report", send_summary))
    app.add_handler(MessageHandler(filters.Regex(r"^/目前账单$"), send_summary))

    # 全部
    app.add_handler(CommandHandler("all", lambda u, c: send_summary(u, c, show_all=True)))
    app.add_handler(MessageHandler(filters.Regex(r"^/全部账单$"), lambda u, c: send_summary(u, c, show_all=True)))

    # 撤销
    app.add_handler(CommandHandler("undo", undo_last))
    app.add_handler(MessageHandler(filters.Regex(r"^/撤销$"), undo_last))

    # 重置
    app.add_handler(CommandHandler("reset", reset_current))
    app.add_handler(MessageHandler(filters.Regex(r"^/清空所有记录$"), reset_current))

    # 添加操作者
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(MessageHandler(filters.Regex(r"^/添加$"), add_member))

    # 删除操作者
    app.add_handler(CommandHandler("remove", remove_member))
    app.add_handler(MessageHandler(filters.Regex(r"^/删除$"), remove_member))

    # 设置时区
    app.add_handler(CommandHandler("timezone", set_timezone))
    app.add_handler(MessageHandler(filters.Regex(r"^/设置时区"), set_timezone))

    # 设置工作时间
    app.add_handler(CommandHandler("worktime", set_worktime))
    app.add_handler(MessageHandler(filters.Regex(r"^/设置时间"), set_worktime))

    # 续费
    app.add_handler(CommandHandler("renew", renew_owner))
    app.add_handler(MessageHandler(filters.Regex(r"^/续费"), renew_owner))
    
    # 用户列表
    app.add_handler(CommandHandler("users", list_users))
    app.add_handler(MessageHandler(filters.Regex(r"^/用户列表$"), list_users))

    # Master 清空菜单
    app.add_handler(CommandHandler("clearall", clearall_menu))
    app.add_handler(CallbackQueryHandler(clearall_callback))

    # 普通文本记账
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))

    app.run_polling()
