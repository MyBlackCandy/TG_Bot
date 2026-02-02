import os
import re
import sys
import logging
import psycopg2
import secrets
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ตั้งค่า Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
ADMIN_ID = os.getenv('ADMIN_ID')

if not TOKEN or not DATABASE_URL:
    print("❌ ERROR: TOKEN หรือ DATABASE_URL หายไป")
    sys.exit(1)

# --- ส่วนจัดการฐานข้อมูล ---
def get_db_connection():
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # ตารางประวัติการคำนวณ
    cursor.execute('''CREATE TABLE IF NOT EXISTS history (
        id SERIAL PRIMARY KEY, chat_id BIGINT, amount INTEGER, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    # ตารางสิทธิ์การใช้งาน (เก็บ ID ของกลุ่มหรือคน)
    cursor.execute('''CREATE TABLE IF NOT EXISTS allowed_chats (
        chat_id BIGINT PRIMARY KEY, username TEXT)''')
    # ตารางรหัสเติมเงิน
    cursor.execute('''CREATE TABLE IF NOT EXISTS codes (
        code TEXT PRIMARY KEY, is_used BOOLEAN DEFAULT FALSE)''')
    conn.commit()
    cursor.close()
    conn.close()
    print("✅ ระบบฐานข้อมูลและรหัสเติมเงินพร้อมใช้งาน")

def is_allowed(chat_id):
    if str(chat_id) == str(ADMIN_ID): return True
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM allowed_chats WHERE chat_id = %s', (chat_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return True if result else False

# --- ส่วนคำสั่งบอท ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '🚀 **AK บอทคำนวณ พร้อมใช้งาน!**\n\n'
        '• พิมพ์ `+เลข` หรือ `-เลข` เพื่อบันทึก\n'
        '• พิมพ์ `/reset` เพื่อล้างข้อมูล\n'
        '• พิมพ์ `/redeem รหัส` เพื่อเปิดใช้งาน'
    )

# [ADMIN] สร้างรหัสเติมเงิน
async def gen_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(ADMIN_ID): return
    new_code = "AK-" + secrets.token_hex(3).upper() # เช่น AK-A1B2C3
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO codes (code) VALUES (%s)', (new_code,))
    conn.commit()
    cursor.close()
    conn.close()
    
    await update.message.reply_text(f"🎟 **สร้างรหัสสำเร็จ:** `{new_code}`\n(ส่งรหัสนี้ให้ลูกค้าเพื่อเปิดใช้งาน)")

# [USER] ใช้รหัสเติมเงิน
async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("❌ กรุณาใส่รหัส เช่น: `/redeem AK-XXXXXX`")
        return
    
    input_code = context.args[0].upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT is_used FROM codes WHERE code = %s', (input_code,))
    result = cursor.fetchone()
    
    if result and not result[0]:
        # รหัสถูกต้องและยังไม่ถูกใช้
        cursor.execute('UPDATE codes SET is_used = TRUE WHERE code = %s', (input_code,))
        cursor.execute('INSERT INTO allowed_chats (chat_id, username) VALUES (%s, %s) ON CONFLICT DO NOTHING', 
                       (chat_id, update.effective_chat.title or update.effective_chat.username))
        conn.commit()
        await update.message.reply_text("✅ **ยินดีด้วย!** บอทถูกเปิดใช้งานสำหรับแชทนี้เรียบร้อยแล้ว")
    else:
        await update.message.reply_text("❌ รหัสไม่ถูกต้องหรือถูกใช้งานไปแล้ว")
    
    cursor.close()
    conn.close()

async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if not is_allowed(chat_id):
        await update.message.reply_text(f"⚠️ **แชทนี้ยังไม่ได้รับสิทธิ์**\nกรุณาใช้รหัสเติมเงินผ่านคำสั่ง `/redeem` หรือติดต่อแอดมิน\n(ID แชทนี้: `{chat_id}`)", parse_mode='Markdown')
        return

    text = update.message.text.strip()
    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        operator, value = match.group(1), int(match.group(2))
        amount = value if operator == '+' else -value

        # บันทึกข้อมูล (ดึงฟังก์ชันเดิมที่เคยเขียนไว้มาใส่)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount) VALUES (%s, %s)', (chat_id, amount))
        cursor.execute('SELECT amount FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
        history = [row[0] for row in cursor.fetchall()]
        conn.commit()
        cursor.close()
        conn.close()

        total = sum(history)
        count = len(history)
        response = "📋 **AK机器人: 记录**\n"
        
        if count > 10:
            response += "...\n"
            display_items = history[-10:]
            start_num = count - 9
        else:
            display_items = history
            start_num = 1

        for i, val in enumerate(display_items, start_num):
            symbol = "+" if val > 0 else ""
            response += f"{i}. {symbol}{val}\n"
        
        response += f"----------------\n📊 全部: {count} 项目\n💰 总金额: {total}"
        await update.message.reply_text(response, parse_mode='Markdown')

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_allowed(chat_id): return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE chat_id = %s', (chat_id,))
    conn.commit()
    cursor.close()
    conn.close()
    await update.message.reply_text("🧹 已清理数据!")

if __name__ == '__main__':
    init_db()
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("gen", gen_code)) # สำหรับแอดมินสร้างรหัส
    application.add_handler(CommandHandler("redeem", redeem)) # สำหรับลูกค้าใช้รหัส
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    
    application.run_polling()
