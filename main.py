import os
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from database import init_db, get_db_connection

# ดึงค่าจาก Environment Variables
MASTER_ADMIN = os.getenv('ADMIN_ID')
BASE_WEB_URL = "https://tgbot-production-d541.up.railway.app" # เปลี่ยนเป็นโดเมนของคุณ

# --- 🛠 ฟังก์ชันหน้าแรก (New UI) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🍎 **黑糖果 记账小程序**\n"
        "ยินดีต้อนรับสู่ระบบจดบัญชี Black Candy\n\n"
        "👇 **请选择操作 (โปรดเลือกรายการ):**"
    )
    keyboard = [
        [InlineKeyboardButton("💳 购买权限 (ชำระเงิน)", callback_data='pay'),
         InlineKeyboardButton("📖 使用教程 (วิธีใช้งาน)", callback_data='help')],
        [InlineKeyboardButton("🎁 免费试用 (ทดลองฟรี 1 วัน)", callback_data='free_trial')],
        [InlineKeyboardButton("📅 查询有效期 (เช็กวันใช้งาน)", callback_data='check_status')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.effective_message.edit_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

# --- 🛡 คำสั่งแอดมิน: /setadmin [ID] [จำนวนวัน] ---
async def set_admin_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(MASTER_ADMIN): return
    try:
        target_id = int(context.args[0])
        days = int(context.args[1])
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO customers (user_id, expire_date) VALUES (%s, CURRENT_TIMESTAMP + interval '%s day') ON CONFLICT (user_id) DO UPDATE SET expire_date = EXCLUDED.expire_date", (target_id, days))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"✅ เพิ่มสิทธิ์ ID `{target_id}` จำนวน `{days}` วันเรียบร้อย")
    except:
        await update.message.reply_text("รูปแบบ: `/setadmin [ID] [จำนวนวัน]`")

# --- 📊 ระบบจดบัญชีพร้อมปุ่ม Mini App ---
async def handle_accounting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        # (เพิ่ม Logic เช็กสิทธิ์การใช้งานตรงนี้ได้)
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', 
                       (update.effective_chat.id, amt, update.message.from_user.first_name))
        conn.commit()
        
        # ดึงยอดสรุป
        cursor.execute('SELECT SUM(amount) FROM history WHERE chat_id = %s', (update.effective_chat.id,))
        total = cursor.fetchone()[0] or 0
        cursor.close(); conn.close()

        # ✅ ปุ่มเปิด Mini App
        keyboard = [[InlineKeyboardButton("📊 查看完整账单 (ดูรายงานฉบับเต็ม)", 
                    web_app=WebAppInfo(url=f"{BASE_WEB_URL}/index.php?c={update.effective_chat.id}"))]]
        
        await update.message.reply_text(f"📝 记录: `{text}`\n💰 总额: **{total}**", 
                                       reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# --- 🚀 เริ่มต้นบอท ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(os.getenv('TOKEN')).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setadmin", set_admin_manual))
    app.add_handler(CallbackQueryHandler(button_handler)) # ต้องมีฟังก์ชัน button_handler จากตัวอย่างก่อนหน้า
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_accounting))
    app.run_polling()
