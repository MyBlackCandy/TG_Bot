import os
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from database import init_db, get_db_connection
from payment import generate_payment_amount, auto_verify_payment

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    uid = update.effective_user.id
    amt = await generate_payment_amount(uid)
    await update.message.reply_text(f"🚀 **激活系统**\n💳 金额: `{amt:.3f}` USDT\n地址: `{os.getenv('USDT_ADDRESS')}`\n⚠️ 请务必转账**精确金额**")



# ดึงค่าแอดมินหลักจาก Environment Variable
MASTER_ADMIN = os.getenv('ADMIN_ID')
async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/check - ตรวจสอบวันหมดอายุสมาชิกและสถานะสิทธิ์"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # กรณีเป็นแอดมินหลัก
    if str(user_id) == str(MASTER_ADMIN):
        return await update.message.reply_text("👑 **สถานะ: แอดมินหลัก (MASTER)**\n∞ อายุการใช้งาน: ถาวร")

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. เช็กวันหมดอายุสมาชิกหลัก
    cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (user_id,))
    customer_data = cursor.fetchone()
    
    # 2. เช็กสถานะลูกทีมในกลุ่มนี้
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    is_team_member = cursor.fetchone()
    
    cursor.close()
    conn.close()

    status_msg = f"👤 **ข้อมูลผู้ใช้:** `{user_id}`\n"
    
    if customer_data:
        expire_date = customer_data[0]
        if expire_date > datetime.now():
            status_msg += f"✅ **权限:** 正常使用\n📅 **到期日期:** `{expire_date.strftime('%Y-%m-%d %H:%M')}`"
        else:
            status_msg += f"❌ **权限:** 已过期 `{expire_date.strftime('%Y-%m-%d %H:%M')}`"
    else:
        status_msg += "❓ **权限:** 没有开通 (`@Mbcd_ACC_bot` 输入`/start`)"

    if is_team_member:
        status_msg += "\n\n👥 **สถานะในกลุ่มนี้:** ได้รับสิทธิ์เป็นลูกทีม"
    
    await update.message.reply_text(status_msg, parse_mode='Markdown')

# --- 🛡️ ACCESS CONTROL ---
def check_access(user_id, chat_id):
    """ตรวจสอบสิทธิ์: แอดมินหลัก | สมาชิกที่ยังไม่หมดอายุ | ลูกทีมในกลุ่มนั้น"""
    if str(user_id) == str(MASTER_ADMIN): return True
    
    conn = get_db_connection(); cursor = conn.cursor()
    # 1. เช็กสมาชิกหลัก
    cursor.execute('SELECT 1 FROM customers WHERE user_id = %s AND expire_date > CURRENT_TIMESTAMP', (user_id,))
    if cursor.fetchone(): 
        cursor.close(); conn.close(); return True
    
    # 2. เช็กสิทธิ์ลูกทีมในกลุ่มที่กำหนด
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    res = cursor.fetchone()
    cursor.close(); conn.close()
    return True if res else False

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help - อธิบายการใช้งานบอทแบบละเอียด"""
    help_text = (
        "📖 **黑糖果机器人使用说明**\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💰 **1. 群里记录**\n"
        "• 直接输入`+100`\n"
        "• 直接输入`-50` \n"
        "*(机器人会自动总计金额)*\n\n"
        
        "📋 **2.**\n"
        "• `/undo` : 撤销上一条记录 (用于登记错误，需要重新输入的情况下)\n"
        "• `/reset` : 清除所有记录（清空）\n\n"
        
        "👥 **3.操作者设置**\n"
        "*(先让想要设置的人发任何一条信息，然后授权者回复信息)*\n"
        "• 回复`/add` : 增加操作者\n"
        "• 回复`/remove` : 移除操作者\n"
        
        
        "💳 **4. 续费及查权限**\n"
        "• `/start` : (私聊机器人 `@Mbcd_ACC_bot`) 开通权限\n"
        "• 系统会自动生成付款金额及付款地址（USDT-TRC20）\n\n"
         "• `/check` : 查权限及使用日期\n\n"
        
        "👑 **5. คำสั่งแอดมิน (MASTER)**\n"
        "• `/setadmin [ID] [วัน]` : เพิ่มอายุการใช้งานแบบระบุตัวตน\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ *备注：转账请务必包含 **精准小数点金额**，系统将自动秒入账，无需截图。\n"
        "⚠️ 付款后还没有授权，联系客服 `@Mbcdcandy`*"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

# --- 🤖 GROUP MANAGEMENT COMMANDS ---

async def add_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/add - มอบสิทธิ์ให้ลูกทีม (ต้อง Reply ข้อความของคนนั้น)"""
    if not update.message.reply_to_message:
        return await update.message.reply_text("⚠️ 没有回复操作者的信息，请回复操作者的信息来进行增加操作者")
    
    if not check_access(update.message.from_user.id, update.effective_chat.id): return

    target = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('''INSERT INTO team_members (member_id, allowed_chat_id) 
                   VALUES (%s, %s) ON CONFLICT DO NOTHING''', (target.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"✅ 已增加操作者 {target.first_name} เรียบร้อยแล้ว")

async def remove_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/remove - ยกเลิกสิทธิ์ลูกทีม (ต้อง Reply)"""
    if not update.message.reply_to_message: return
    if not check_access(update.message.from_user.id, update.effective_chat.id): return

    target = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', 
                   (target.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"🚫 移除操作者 {target.first_name} แล้ว")

async def reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/reset - ล้างบัญชีทั้งหมดในกลุ่มนี้"""
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE chat_id = %s', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("🧹 已清除所有数据")

async def undo_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/undo - ยกเลิกรายการบันทึกล่าสุด"""
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('''DELETE FROM history WHERE id = (
        SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1
    )''', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ 已撤销上一条记录")

async def set_admin_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/setadmin [ID] [Days] - แอดมินหลักใช้เพิ่มวันสมาชิกด้วยตนเอง"""
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    try:
        user_id = int(context.args[0])
        days = int(context.args[1])
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('''INSERT INTO customers (user_id, expire_date) 
                       VALUES (%s, CURRENT_TIMESTAMP + interval '%s day')
                       ON CONFLICT (user_id) DO UPDATE SET expire_date = EXCLUDED.expire_date''', 
                       (user_id, days))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"👑 เปิดสิทธิ์ ID {user_id} จำนวน {days} วันสำเร็จ")
    except:
        await update.message.reply_text("รูปแบบ: `/setadmin [ID] [จำนวนวัน]`")

# --- 📊 ACCOUNTING LOGIC ---

async def handle_accounting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """จดบันทึก +ตัวเลข หรือ -ตัวเลข"""
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    match = re.match(r'^([+-])(\d+)$', text)
    
    if match:
        if not check_access(update.message.from_user.id, update.effective_chat.id): return
        
        amount = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', 
                       (update.effective_chat.id, amount, update.message.from_user.first_name))
        conn.commit()
        
        # ดึงยอดรวม
        cursor.execute('SELECT SUM(amount) FROM history WHERE chat_id = %s', (update.effective_chat.id,))
        total = cursor.fetchone()[0] or 0
        cursor.close(); conn.close()
        
        await update.message.reply_text(f"📝 บันทึก: {text}\n💰 总额: {total}")

# --- 🚀 STARTUP & RUN ---

if __name__ == '__main__':
    init_db()
    app = Application.builder().token(os.getenv('TOKEN')).build()
    if app.job_queue:
        app.job_queue.run_repeating(auto_verify_payment, interval=60)
    # ลงทะเบียนคำสั่ง
    app.add_handler(CommandHandler("start", start)) # ฟังก์ชันจาก payment.py
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("remove", remove_member))
    app.add_handler(CommandHandler("reset", reset_history))
    app.add_handler(CommandHandler("undo", undo_last))
    app.add_handler(CommandHandler("setadmin", set_admin_manual))
    
    # MessageHandler สำหรับจดบันทึกตัวเลข
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_accounting))
    
    print("Bot is running...")
    app.run_polling()
