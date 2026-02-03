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

# --- คำสั่งสำหรับคุณ (Master Admin) ---
async def set_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. เช็คว่าเป็นคุณ (เจ้าของ ID) หรือเปล่า
    if str(update.message.from_user.id) != str(MASTER_ADMIN):
        return

    # 2. ต้องเป็นการ Reply เท่านั้น
    if not update.message.reply_to_message:
        await update.message.reply_text("💡 **วิธีใช้:** ให้กด **Reply (ตอบกลับ)** ข้อความของลูกค้า แล้วพิมพ์ `/setadmin [จำนวนวัน]` เช่น `/setadmin 30`")
        return

    try:
        # ดึงข้อมูลจากข้อความที่ถูก Reply
        target_user = update.message.reply_to_message.from_user
        target_id = target_user.id
        target_name = target_user.first_name
        
        # ดึงจำนวนวัน (ถ้าไม่ใส่จะตั้งไว้ที่ 30 วัน)
        days = int(context.args[0]) if context.args else 30
        exp_date = datetime.now() + timedelta(days=days)

        # บันทึกลงฐานข้อมูล
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO customers (user_id, expire_date) 
            VALUES (%s, %s) 
            ON CONFLICT (user_id) 
            DO UPDATE SET expire_date = EXCLUDED.expire_date
        ''', (target_id, exp_date))
        conn.commit(); cursor.close(); conn.close()

        await update.message.reply_text(
            f"👑 **ตั้งหัวหน้าทีมสำเร็จ!**\n"
            f"👤 ชื่อ: {target_name}\n"
            f"🆔 ID: `{target_id}`\n"
            f"📅 ใช้งานได้ถึง: {exp_date.strftime('%Y-%m-%d')}\n"
            f"⏳ รวม: {days} วัน"
        )
    except ValueError:
        await update.message.reply_text("❌ กรุณาระบุจำนวนวันเป็นตัวเลข เช่น `/setadmin 30`")
    except Exception as e:
        await update.message.reply_text(f"❌ เกิดข้อผิดพลาด: {e}")

# --- ส่วนอื่นๆ (init_db, add_member, handle_calc) ใช้ตามโครงสร้างเดิม ---

if __name__ == '__main__':
    app = Application.builder().token(TOKEN).build()
    
    # คำสั่งสำหรับคุณ (Master Admin)
    app.add_handler(CommandHandler("setadmin", set_admin))
    
    # คำสั่งสำหรับหัวหน้าทีม (ลูกค้า) เพื่อเพิ่มลูกทีม
    # (แนะนำให้ใช้การ Reply ลูกทีมแล้วพิมพ์ /add เช่นกัน)
    app.add_handler(CommandHandler("add", add_member)) 
    
    # ระบบบวกลบเลข
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_calc))
    
    app.run_polling()
