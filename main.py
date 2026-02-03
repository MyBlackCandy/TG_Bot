import os
import re
import sys
import logging
import psycopg2
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- Logging ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')

def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

# --- ฟีเจอร์ /info: แสดงวิธีใช้งาน ---
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    
    # ข้อความพื้นฐานสำหรับทุกคน
    text = "📖 **AK Robot - วิธีใช้งาน**\n\n"
    text += "🔢 **การบันทึกยอด:**\n"
    text += "• พิมพ์ `+เลข` (เช่น +100) เพื่อเพิ่มยอด\n"
    text += "• พิมพ์ `-เลข` (เช่น -50) เพื่อลดยอด\n\n"
    
    text += "🎮 **คำสั่งทั่วไป:**\n"
    text += "• /undo - ยกเลิกรายการล่าสุดที่เพิ่งพิมพ์ผิด\n"
    text += "• /info - ดูวิธีใช้งานทั้งหมดนี้\n\n"

    # ข้อความสำหรับหัวหน้าทีม (Customer)
    text += "👤 **สำหรับหัวหน้าทีม:**\n"
    text += "• /add - (Reply ลูกทีม) เพื่อเพิ่มลูกทีมเข้ากลุ่มนี้\n"
    text += "• /reset - ล้างประวัติยอดทั้งหมดในกลุ่มเป็น 0\n\n"

    # ข้อความพิเศษสำหรับคุณ (Master Admin)
    if user_id == str(MASTER_ADMIN):
        text += "👑 **Master Admin Only:**\n"
        text += "• /setadmin [วัน] - (Reply ลูกค้า) เพื่อเปิดสิทธิ์หัวหน้าทีม\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

# --- ฟีเจอร์ /undo: ยกเลิกรายการล่าสุด ---
async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    chat_id = update.effective_chat.id
    if not check_access(user_id, chat_id): return

    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT id, amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1', (chat_id,))
    last_item = cursor.fetchone()

    if last_item:
        item_id, amount, name = last_item
        cursor.execute('DELETE FROM history WHERE id = %s', (item_id,))
        conn.commit()
        symbol = "+" if amount > 0 else ""
        await update.message.reply_text(f"↩️ **ยกเลิกสำเร็จ!**\nลบรายการ: {symbol}{amount} ({name}) ออกแล้ว")
    else:
        await update.message.reply_text("❌ ไม่พบรายการที่จะยกเลิก")
    cursor.close(); conn.close()

# --- ส่วนอื่นๆ (คงเดิม) ---
def init_db():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS customers (user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP)')
    cursor.execute('CREATE TABLE IF NOT EXISTS team_members (member_id BIGINT PRIMARY KEY, leader_id BIGINT, allowed_chat_id BIGINT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, chat_id BIGINT, amount INTEGER, user_name TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    conn.commit(); cursor.close(); conn.close()

def check_access(user_id, chat_id):
    if str(user_id) == str(MASTER_ADMIN): return True
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM customers WHERE user_id = %s AND expire_date > %s', (user_id, datetime.now()))
    if cursor.fetchone(): 
        cursor.close(); conn.close(); return True
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    res = cursor.fetchone(); cursor.close(); conn.close()
    return True if res else False

async def set_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(MASTER_ADMIN) or not update.message.reply_to_message: return
    try:
        target = update.message.reply_to_message.from_user
        days = int(context.args[0]) if context.args else 30
        exp = datetime.now() + timedelta(days=days)
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO customers VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date = EXCLUDED.expire_date', (target.id, exp))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"👑 ตั้ง `{target.first_name}` เป็นหัวหน้าทีม ({days} วัน)")
    except: pass

async def add_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leader_id = update.message.from_user.id
    chat_id = update.effective_chat.id
    if not check_access(leader_id, chat_id) or not update.message.reply_to_message: return
    target = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO team_members VALUES (%s, %s, %s) ON CONFLICT (member_id) DO UPDATE SET allowed_chat_id = EXCLUDED.allowed_chat_id', (target.id, leader_id, chat_id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"✅ เพิ่ม `{target.first_name}` เป็นลูกทีมแล้ว")

async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    chat_id = update.effective_chat.id; user_id = update.message.from_user.id
    if not check_access(user_id, chat_id): return
    text = update.message.text.strip()
    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        val = int(match.group(2))
        amount = val if match.group(1) == '+' else -val
        user_name = update.message.from_user.first_name
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', (chat_id, amount, user_name))
        conn.commit()
        cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
        rows = cursor.fetchall(); cursor.close(); conn.close()
        total = sum(r[0] for r in rows); count = len(rows)
        res = "📋 AK机器人:记录\n"
        display = rows[-10:] if count > 10 else rows
        if count > 10: res += "...\n"
        for i, (v, name) in enumerate(display, (count-9 if count > 10 else 1)):
            res += f"{i}. {'+' if v > 0 else ''}{v} ({name})\n"
        res += f"----------------\n📊 全部: {count} | 💰 总金额: {total}"
        await update.message.reply_text(res)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE chat_id = %s', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("🧹 已清理数据!")

if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("setadmin", set_admin))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("undo", undo))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    app.run_polling()
