import os, re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from database import get_db_connection, get_user_role, get_user_info

TOKEN = os.getenv('TOKEN')
MASTER_ID = os.getenv('ADMIN_ID')

# --- 🆔 คำสั่งเช็ค ID และสถานะตัวเอง ---
async def check_self(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = update.effective_user.first_name
    expire_date = get_user_info(uid)
    
    status = "❌ ไม่มีแพ็กเกจ"
    if str(uid) == str(MASTER_ID):
        status = "👑 Master Admin"
    elif expire_date:
        if expire_date > datetime.utcnow():
            status = f"✅ Admin (หมดอายุ: {expire_date.strftime('%Y-%m-%d')})"
        else:
            status = f"⚠️ หมดอายุเมื่อ: {expire_date.strftime('%Y-%m-%d')}"

    msg = (f"👤 **ข้อมูลผู้ใช้**\n"
           f"━━━━━━━━━━━━━━━\n"
           f"ชื่อ: {name}\n"
           f"ไอดี: `{uid}` (แตะเพื่อก๊อปปี้)\n"
           f"สถานะ: {status}\n"
           f"━━━━━━━━━━━━━━━\n"
           f"💡 ส่งไอดีนี้ให้มาสเตอร์เพื่อต่ออายุ")
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- 🗑️ คำสั่งลบรายการ (เฉพาะ Master/Admin) ---
async def delete_ops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = get_user_role(update.effective_user.id, update.effective_chat.id)
    if role not in ['master', 'admin']: return

    cmd = update.message.text.split()[0]
    conn = get_db_connection(); cursor = conn.cursor()

    if "/del" in cmd: # ลบรายการล่าสุด
        cursor.execute("DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)", (update.effective_chat.id,))
        await update.message.reply_text("🗑 ลบรายการล่าสุดเรียบร้อย")
    elif "/clear" in cmd: # ลบทั้งหมดของวันนี้
        cursor.execute("DELETE FROM history WHERE chat_id = %s AND timestamp::date = CURRENT_DATE", (update.effective_chat.id,))
        await update.message.reply_text("🧹 ล้างรายการทั้งหมดของวันนี้แล้ว")
    
    conn.commit(); cursor.close(); conn.close()

# --- ระบบบันทึกยอด ---
async def handle_accounting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        role = get_user_role(update.effective_user.id, update.effective_chat.id)
        if not role: return
        
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)", 
                       (update.effective_chat.id, amt, update.effective_user.first_name))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"📝 บันทึก {amt} เรียบร้อย")

def main():
    app = Application.builder().token(TOKEN).build()
    
    # เพิ่มคำสั่งต่างๆ
    app.add_handler(CommandHandler(["id", "check", "start"], check_self))
    app.add_handler(CommandHandler(["del", "clear"], delete_ops))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_accounting))
    
    # อย่าลืม Handler สำหรับ /setuser และ /add จากโค้ดก่อนหน้า
    # ...
    
    app.run_polling()

if __name__ == '__main__':
    main()
