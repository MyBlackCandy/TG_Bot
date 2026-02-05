import os
import re
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from database import init_db, get_db_connection

# --- ⚙️ Setup ---
logging.basicConfig(level=logging.INFO)
MASTER_ADMIN = os.getenv('ADMIN_ID')

# --- 🛡️ Role Check ---
async def get_role(uid, chat_id):
    if str(uid) == str(MASTER_ADMIN): return "master"
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM admins WHERE user_id = %s', (uid,))
    res = cursor.fetchone()
    if res and res[0] > datetime.utcnow():
        cursor.close(); conn.close(); return "admin"
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND chat_id = %s', (uid, chat_id))
    is_team = cursor.fetchone(); cursor.close(); conn.close()
    return "team" if is_team else None

# --- 📊 สรุปยอด ---
async def send_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"✅ บอททำงานปกติในกลุ่ม ID: {chat_id}\nตารางใน DB พร้อมใช้งานแล้ว!")

# --- 🚀 ฟังก์ชันหลักป้องกัน Crash ---
def main():
    # 1. สั่งสร้างตารางทันทีที่เริ่มโปรแกรม
    print("🚀 Starting Bot and Initializing DB...")
    init_db() 
    
    # 2. ตั้งค่าบอท
    token = os.getenv('TOKEN')
    if not token:
        print("❌ ERROR: TOKEN not found in environment variables!")
        return

    application = Application.builder().token(token).build()
    
    # 3. ใส่คำสั่งต่างๆ
    application.add_handler(CommandHandler(["start", "bot"], send_summary))
    # เพิ่มคำสั่งอื่นๆ ตรงนี้...

    # 4. รันบอทแบบ Polling (ไม่ใช่ Webhook เพื่อเลี่ยงปัญหา ASGI)
    print("📡 Bot is polling...")
    application.run_polling()

if __name__ == '__main__':
    main()
