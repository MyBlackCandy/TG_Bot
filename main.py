import os
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from database import init_db, get_db_connection

MASTER_ADMIN = os.getenv('ADMIN_ID')
BASE_WEB_URL = "https://tgbot-production-d541.up.railway.app"

# --- 🛠️ 1. ฟังก์ชันหน้าแรก (/start) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🍎 **欢迎使用 黑糖果 记账机器人**\n"
        "ยินดีต้อนรับสู่บอทจดบัญชี Black Candy\n\n"
        "🤖 **我能做什么？(บอททำอะไรได้บ้าง?)**\n"
        "• 自动记录群内账目 (จดบันทึกบัญชีในกลุ่มอัตโนมัติ)\n"
        "• 实时汇总总额 (สรุปยอดรวมแบบเรียลไทม์)\n"
        "• 在线查看完整账单 (ดูรายงานฉบับเต็มผ่านหน้าเว็บ)\n"
        "• 权限管理系统 (ระบบจัดการสิทธิ์และสมาชิก)\n\n"
        "👇 **请选择操作 (โปรดเลือกรายการด้านล่าง):**"
    )
    
    keyboard = [
        [InlineKeyboardButton("💳 购买权限 (ชำระเงิน)", callback_data='pay'),
         InlineKeyboardButton("📖 使用教程 (วิธีใช้งาน)", callback_data='help')],
        [InlineKeyboardButton("🎁 免费试用 (ทดลองใช้ฟรี 1 วัน)", callback_data='free_trial')],
        [InlineKeyboardButton("📅 查询有效期 (เช็กวันใช้งาน)", callback_data='check_status')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        # สำหรับกรณีเรียกซ้ำผ่าน Callback
        await update.effective_message.edit_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

# --- 🛡️ 2. ฟังก์ชันจัดการปุ่มกด (Callback Query) ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    
    if query.data == 'pay':
        pay_text = (
            "💳 **充值续费 (ชำระเงิน)**\n"
            "━━━━━━━━━━━━━━━\n"
            "• 30 天 / 100 USDT\n\n"
            f"📍 **转账地址 (TRC20):**\n`{os.getenv('USDT_ADDRESS')}`\n\n"
            "⚠️ *轉帳後請聯繫客服 (โอนเงินแล้วแจ้งแอดมิน):* @Mbcdcandy"
        )
        await query.edit_message_text(pay_text, parse_mode='Markdown', 
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回 (กลับหน้าแรก)", callback_data='back')]]))

    elif query.data == 'help':
        help_text = (
            "📖 **使用教程 (วิธีใช้งาน)**\n"
            "━━━━━━━━━━━━━━━\n"
            "1. **บันทึก:** พิมพ์ `+100` หรือ `-50` ในกลุ่ม\n"
            "2. **ยกเลิก:** พิมพ์ `/undo` เพื่อลบรายการล่าสุด\n"
            "3. **ล้างค่า:** พิมพ์ `/reset` เพื่อเริ่มใหม่ทั้งหมด\n"
            "4. **ดูรายงาน:** กดปุ่ม '查看完整账单' ใต้ยอดสรุป"
        )
        await query.edit_message_text(help_text, parse_mode='Markdown',
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回 (กลับหน้าแรก)", callback_data='back')]]))

    elif query.data == 'free_trial':
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM customers WHERE user_id = %s', (uid,))
        if cursor.fetchone():
            msg = "❌ **您已领过试用 (คุณเคยรับสิทธิ์ทดลองใช้ไปแล้ว)**"
        else:
            expire_trial = datetime.now() + timedelta(days=1)
            cursor.execute('INSERT INTO customers (user_id, expire_date) VALUES (%s, %s)', (uid, expire_trial))
            conn.commit()
            msg = f"✅ **试用成功! (รับสิทธิ์ฟรีแล้ว)**\n📅 到期: `{expire_trial.strftime('%Y-%m-%d %H:%M')}`"
        cursor.close(); conn.close()
        await query.edit_message_text(msg, parse_mode='Markdown',
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回 (กลับหน้าแรก)", callback_data='back')]]))

    elif query.data == 'check_status':
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (uid,))
        res = cursor.fetchone(); cursor.close(); conn.close()
        
        if str(uid) == str(MASTER_ADMIN):
            msg = "👑 **สถานะ: MASTER ADMIN**\n∞ อายุการใช้งาน: ถาวร (永久)"
        elif res:
            expire = res[0]
            if expire > datetime.now():
                msg = f"✅ **正常使用 (ใช้งานได้ปกติ)**\n📅 到期日期: `{expire.strftime('%Y-%m-%d')}`\n⏰ 到期时间: `{expire.strftime('%H:%M')}`"
            else:
                msg = f"❌ **已过期 (หมดอายุแล้ว)**\n📅 到期: `{expire.strftime('%Y-%m-%d %H:%M')}`"
        else:
            msg = "❌ **未开通权限 (ยังไม่มีข้อมูลการใช้งาน)**"
        
        await query.edit_message_text(msg, parse_mode='Markdown',
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回 (กลับหน้าแรก)", callback_data='back')]]))

    elif query.data == 'back':
        await start(update, context)

# --- 🚀 ฟังก์ชันหลัก (Main) ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(os.getenv('TOKEN')).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command)) # ฟังก์ชัน help เดิม
    app.add_handler(CommandHandler("undo", undo_last))   # ฟังก์ชัน undo เดิม
    app.add_handler(CommandHandler("reset", reset_history)) # ฟังก์ชัน reset เดิม
    
    # ตัวจัดการปุ่มกด Inline
    app.add_handler(update.callback_query_handler(button_handler))
    
    # ตัวจัดการจดบันทึกตัวเลข
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_accounting))
    
    print("New UI Bot is running...")
    app.run_polling()
