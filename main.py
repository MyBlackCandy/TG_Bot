import os
import re
import sys
import logging
import psycopg2
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- ตั้งค่า Logging ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')

def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

# --- [ฟีเจอร์ใหม่] Undo: ยกเลิกรายการล่าสุด ---
async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    chat_id = update.effective_chat.id
    
    if not check_access(user_id, chat_id): return

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # ค้นหารายการล่าสุดของกลุ่มนี้
    cursor.execute('SELECT id, amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1', (chat_id,))
    last_item = cursor.fetchone()

    if last_item:
        item_id, amount, name = last_item
        # ลบรายการนั้นออก
        cursor.execute('DELETE FROM history WHERE id = %s', (item_id,))
        conn.commit()
        
        symbol = "+" if amount > 0 else ""
        await update.message.reply_text(f"↩️ **ยกเลิกรายการล่าสุดสำเร็จ!**\nลบรายการ: {symbol}{amount} ({name}) ออกแล้ว")
    else:
        await update.message.reply_text("❌ ไม่พบรายการที่จะยกเลิก")
    
    cursor.close()
    conn.close()

# --- ส่วนอื่นๆ (คงเดิมและอัปเดต CommandHandler) ---

async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (โค้ด handle_calc เดิมของคุณ) ...
    if not update.message or not update.message.text: return
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

# ฟังก์ชันช่วยเหลืออื่นๆ เหมือนเดิม... (init_db, check_access, set_admin, add_member, reset)

if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("setadmin", set_admin))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("undo", undo)) # เพิ่ม Handler สำหรับคำสั่ง undo
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    app.run_polling()
