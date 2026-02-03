import os
import re
import psycopg2
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURATION ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')

def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS customers (user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP)')
    cursor.execute('CREATE TABLE IF NOT EXISTS team_members (member_id BIGINT PRIMARY KEY, leader_id BIGINT, allowed_chat_id BIGINT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, chat_id BIGINT, amount INTEGER, user_name TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    conn.commit(); cursor.close(); conn.close()

# --- CHECK PERMISSIONS ---
def check_access(user_id, chat_id):
    if str(user_id) == str(MASTER_ADMIN): return True
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM customers WHERE user_id = %s AND expire_date > %s', (user_id, datetime.now()))
    if cursor.fetchone(): 
        cursor.close(); conn.close()
        return True
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    res = cursor.fetchone()
    cursor.close(); conn.close()
    return True if res else False

# --- COMMANDS ---
async def add_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leader_id = update.message.from_user.id
    chat_id = update.effective_chat.id
    
    # ตรวจสอบสิทธิ์คนสั่ง (ต้องเป็นหัวหน้าทีมหรือ Master Admin)
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM customers WHERE user_id = %s AND expire_date > %s', (leader_id, datetime.now()))
    is_leader = cursor.fetchone() or str(leader_id) == str(MASTER_ADMIN)
    
    if not is_leader:
        await update.message.reply_text("❌ เฉพาะหัวหน้าทีมเท่านั้นที่เพิ่มลูกทีมได้")
        return

    target_id = None
    target_name = ""

    # วิธีที่ 1: ตรวจสอบจากการแท็ก @username (Entity)
    if update.message.entities:
        for entity in update.message.entities:
            if entity.type == "text_mention": # สำหรับคนไม่มี Username (ต้อง Reply)
                target_id = entity.user.id
                target_name = entity.user.first_name
            elif entity.type == "mention": # สำหรับ @username
                # หมายเหตุ: บอทจะหา ID จาก @ ได้ก็ต่อเมื่อบอทเคยเห็นคนนั้นมาก่อน
                # แนะนำให้ใช้การ Reply @ หรือให้เพื่อนพิมพ์อะไรบางอย่างก่อนครับ
                pass

    # วิธีที่ 2: ใช้การ Reply (แม่นยำที่สุด)
    if not target_id and update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
        target_name = update.message.reply_to_message.from_user.first_name

    if target_id:
        cursor.execute('INSERT INTO team_members (member_id, leader_id, allowed_chat_id) VALUES (%s, %s, %s) ON CONFLICT (member_id) DO UPDATE SET allowed_chat_id = EXCLUDED.allowed_chat_id', (target_id, leader_id, chat_id))
        conn.commit()
        await update.message.reply_text(f"✅ เพิ่ม `{target_name}` เป็นลูกทีมในกลุ่มนี้เรียบร้อย!")
    else:
        await update.message.reply_text("💡 วิธีใช้: พิมพ์ `/add` แล้วตอบกลับข้อความเพื่อน หรือพิมพ์ `/add @ชื่อเพื่อน` (เพื่อนต้องอยู่ในกลุ่ม)")
    
    cursor.close(); conn.close()

# --- CALCULATION LOGIC ---
async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.message.from_user.id
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
        cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id, ))
        rows = cursor.fetchall(); cursor.close(); conn.close()
        
        total = sum(r[0] for r in rows)
        count = len(rows)
        res = "📋 AK机器人:记录\n"
        display = rows[-10:] if count > 10 else rows
        if count > 10: res += "...\n"
        for i, (v, name) in enumerate(display, (count-9 if count > 10 else 1)):
            res += f"{i}. {'+' if v > 0 else ''}{v} ({name})\n"
        res += f"----------------\n📊 全部: {count}\n💰 总金额: {total}"
        await update.message.reply_text(res)

if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("add", add_member))
    # คำสั่งหลักสำหรับ Master Admin (คุณ)
    app.add_handler(CommandHandler("set", lambda u, c: None)) # ใส่ logic add_leader ตามเดิม
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    app.run_polling()
