import os
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import (
    Application, ContextTypes,
    MessageHandler, CommandHandler, filters
)

from database import get_conn, init_db


BOT_TOKEN = os.getenv("BOT_TOKEN")
MASTER_ID = int(os.getenv("MASTER_ID", "0"))

app = FastAPI()
tg = Application.builder().token(BOT_TOKEN).build()


# ======================================================
# ====================== UTILS =========================
# ======================================================

def fmt(rows):
    s = ""
    for i, r in enumerate(rows, 1):
        s += f"{i:<3} {r[2]:<6} {r[0]:>8} ({r[1]})\n"
    return s


def tz_now(offset):
    return datetime.utcnow() + timedelta(hours=offset)


def today_range(offset):
    now = tz_now(offset)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start - timedelta(hours=offset), end - timedelta(hours=offset)


# ======================================================
# ====================== ROLE ==========================
# ======================================================

def is_master(uid):
    return uid == MASTER_ID


def is_admin(uid):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT expire_at FROM admins WHERE user_id=%s", (uid,))
    r = cur.fetchone()
    conn.close()
    return r and r[0] > datetime.utcnow()


def is_team(chat, uid):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM team WHERE chat_id=%s AND user_id=%s", (chat, uid))
    ok = cur.fetchone() is not None
    conn.close()
    return ok


def allowed(chat, uid):
    return is_master(uid) or is_admin(uid) or is_team(chat, uid)


# ======================================================
# ================== AUTO REGISTER =====================
# ======================================================

async def auto_reg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat:
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO groups(chat_id,name)
        VALUES(%s,%s)
        ON CONFLICT DO NOTHING
    """, (chat.id, chat.title))
    conn.commit()
    conn.close()


# ======================================================
# ================== RECORD MONEY ======================
# ======================================================

async def record(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()

    if not (txt.startswith("+") or txt.startswith("-")):
        return

    chat = update.effective_chat.id
    uid = update.effective_user.id

    if not allowed(chat, uid):
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO history(chat_id,amount,user_name)
        VALUES(%s,%s,%s)
    """, (chat, int(txt), update.effective_user.full_name))
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ 记录成功")


# ======================================================
# ================== SUMMARY ===========================
# ======================================================

async def summary(update, ctx):
    chat = update.effective_chat.id

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT timezone FROM groups WHERE chat_id=%s", (chat,))
    tz = cur.fetchone()[0]

    start, end = today_range(tz)

    cur.execute("""
        SELECT amount,user_name,to_char(timestamp,'HH24:MI')
        FROM history
        WHERE chat_id=%s AND timestamp BETWEEN %s AND %s
        ORDER BY timestamp DESC LIMIT 6
    """, (chat, start, end))

    rows = list(reversed(cur.fetchall()))
    total = sum(r[0] for r in rows)

    await update.message.reply_text(
        f"```\n{fmt(rows)}\n总计: {total}\n```"
    )
    conn.close()


# ======================================================
# ================= SHOW ALL ===========================
# ======================================================

async def showall(update, ctx):
    chat = update.effective_chat.id

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT amount,user_name,to_char(timestamp,'HH24:MI')
        FROM history WHERE chat_id=%s ORDER BY timestamp
    """, (chat,))

    await update.message.reply_text(f"```\n{fmt(cur.fetchall())}\n```")
    conn.close()


# ======================================================
# ================= UNDO ===============================
# ======================================================

async def undo(update, ctx):
    chat = update.effective_chat.id
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM history WHERE id =
        (SELECT id FROM history WHERE chat_id=%s ORDER BY timestamp DESC LIMIT 1)
    """, (chat,))

    conn.commit()
    conn.close()

    await update.message.reply_text("↩️ 已撤销")


# ======================================================
# ================= RESET ==============================
# ======================================================

async def reset(update, ctx):
    chat = update.effective_chat.id
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM history WHERE chat_id=%s", (chat,))
    conn.commit()
    conn.close()

    await update.message.reply_text("🗑 清空完成")


# ======================================================
# ================= SET TIMEZONE =======================
# ======================================================

async def settime(update, ctx):
    chat = update.effective_chat.id
    offset = int(ctx.args[0])

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE groups SET timezone=%s WHERE chat_id=%s", (offset, chat))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"⏰ UTC{offset:+}")


# ======================================================
# ================= TEAM MGMT ==========================
# ======================================================

async def add(update, ctx):
    if not update.message.reply_to_message:
        return

    chat = update.effective_chat.id
    u = update.message.reply_to_message.from_user

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO team(chat_id,user_id,name) VALUES(%s,%s,%s)",
                (chat, u.id, u.full_name))
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ 成员已添加")


async def addlist(update, ctx):
    chat = update.effective_chat.id
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT name FROM team WHERE chat_id=%s", (chat,))
    rows = [r[0] for r in cur.fetchall()]
    conn.close()

    await update.message.reply_text("\n".join(rows) or "empty")


async def resetadd(update, ctx):
    chat = update.effective_chat.id
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM team WHERE chat_id=%s", (chat,))
    conn.commit()
    conn.close()

    await update.message.reply_text("🗑 成员已清空")


# ======================================================
# ================= MASTER =============================
# ======================================================

async def setadmin(update, ctx):
    if not is_master(update.effective_user.id):
        return

    uid = int(ctx.args[0])
    days = int(ctx.args[1])

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO admins(user_id,expire_at)
        VALUES(%s, NOW()+interval '%s day')
        ON CONFLICT (user_id)
        DO UPDATE SET expire_at = admins.expire_at + interval '%s day'
    """, (uid, days, days))

    conn.commit()
    conn.close()

    await update.message.reply_text("👑 Admin 设置完成")


async def setlist(update, ctx):
    if not is_master(update.effective_user.id):
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id,expire_at FROM admins")

    txt = ""
    for u, e in cur.fetchall():
        status = "🟢" if e > datetime.utcnow() else "🔴"
        txt += f"{u} {status} {e}\n"

    conn.close()
    await update.message.reply_text(txt or "empty")


async def grouplist(update, ctx):
    if not is_master(update.effective_user.id):
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT chat_id,name FROM groups")

    txt = ""
    for cid, name in cur.fetchall():
        txt += f"{name} ({cid})\n"

    conn.close()
    await update.message.reply_text(txt or "empty")


async def sync(update, ctx):
    await update.message.reply_text("✅ DB 同步完成")


# ======================================================
# ================= CHECK + HELP =======================
# ======================================================

async def check(update, ctx):
    uid = update.effective_user.id
    role = "Team"

    if is_master(uid):
        role = "Master"
    elif is_admin(uid):
        role = "Admin"

    await update.message.reply_text(f"ID: {uid}\nRole: {role}")


async def help_cmd(update, ctx):
    await update.message.reply_text("""
+100 / -50
/bot
/showall
/undo
/reset
/settime
/add
/addlist
/resetadd
/check

Master:
/setadmin
/setlist
/grouplist
/sync
""")


# ======================================================
# ================= REGISTER ===========================
# ======================================================

tg.add_handler(MessageHandler(filters.ALL, auto_reg))
tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, record))

tg.add_handler(CommandHandler("bot", summary))
tg.add_handler(CommandHandler("showall", showall))
tg.add_handler(CommandHandler("undo", undo))
tg.add_handler(CommandHandler("reset", reset))
tg.add_handler(CommandHandler("settime", settime))
tg.add_handler(CommandHandler("add", add))
tg.add_handler(CommandHandler("addlist", addlist))
tg.add_handler(CommandHandler("resetadd", resetadd))
tg.add_handler(CommandHandler("setadmin", setadmin))
tg.add_handler(CommandHandler("setlist", setlist))
tg.add_handler(CommandHandler("grouplist", grouplist))
tg.add_handler(CommandHandler("sync", sync))
tg.add_handler(CommandHandler("check", check))
tg.add_handler(CommandHandler("help", help_cmd))


# ======================================================
# ================= WEBHOOK ============================
# ======================================================

@app.on_event("startup")
async def startup():
    init_db()


@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, tg.bot)
    await tg.process_update(update)
    return {"ok": True}
