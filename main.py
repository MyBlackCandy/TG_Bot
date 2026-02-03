import os
import re
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from database import init_db, get_db_connection
from payment import generate_payment_amount, auto_verify_payment

MASTER_ADMIN = os.getenv('ADMIN_ID')

# --- 🛡️ ACCESS CONTROL ---
async def check_access(user_id, chat_id):
    if str(user_id) == str(MASTER_ADMIN): return True
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM customers WHERE user_id = %s AND expire_date > CURRENT_TIMESTAMP', (user_id,))
    if cursor.fetchone(): 
        cursor.close(); conn.close(); return True
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    res = cursor.fetchone(); cursor.close(); conn.close()
    return True if res else False

# --- 📊 ACCOUNTING LOGIC (ย่อรายการเมื่อเกิน 6) ---
async def send_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
    rows = cursor.fetchall(); total = sum(r[0] for r in rows); count = len(rows)
    
    if count == 0: return await update.message.reply_text("📋 **当前无记录**")

    history_text = "...\n" if count > 6 else ""
    display_rows = rows[-6:] if count > 6 else rows
    start_num = max(1, count - 5) if count > 6 else 1
    for i, r in enumerate(display_rows):
        history_text += f"{start_num + i}. {'+' if r[0] > 0 else ''}{r[0]} ({r[1]})\n"
    
    cursor.close(); conn.close()
    await update.message.reply_text(f"📊 **账目汇总**\n━━━━━━━━━━━━━━━\n{history_text}━━━━━━━━━━━━━━━\n💰 **总额: {total}**", parse_mode='Markdown')

# --- 🤖 COMMAND HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    amt = await generate_payment_amount(update.effective_user.id)
    await update.message.reply_text(f"🚀 **激活系统**\n💳 金额: `{amt:.3f}` USDT\n地址: `{os.getenv('USDT_ADDRESS')}`")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = ("📖 **使用说明**\n━━━━━━━━━━━━━━━\n"
           "• `+เลข` หรือ `-เลข` เพื่อจดบันทึก\n"
           "• `/undo` : ยกเลิกรายการล่าสุด\n"
           "• `/reset` : ล้างบัญชีทั้งหมด\n"
           "• `/add` : เพิ่มลูกทีม (Reply คนนั้น)\n"
           "• `/remove` : ลบลูกทีม (Reply คนนั้น)\n"
           "• `/check` : เช็ควันหมดอายุ")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def add_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("⚠️ โปรด Reply ข้อความของคนที่ต้องการเพิ่ม")
    if not await check_access(update.message.from_user.id, update.effective_chat.id): return
    target = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO team_members (member_id, allowed_chat_id) VALUES (%s, %s) ON CONFLICT DO NOTHING', (target.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"✅ เพิ่ม {target.first_name} เรียบร้อย")

async def remove_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return
    if not await check_access(update.message.from_user.id, update.effective_chat.id): return
    target = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (target.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"🚫 ลบสิทธิ์ {target.first_name} เรียบร้อย")

async def reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE chat_id = %s', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("🧹 **已清除所有数据 (Reset Success)**")

async def set_admin_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    try:
        uid, days = int(context.args[0]), int(context.args[1])
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute("INSERT INTO customers (user_id, expire_date) VALUES (%s, CURRENT_TIMESTAMP + interval '%s day') ON CONFLICT (user_id) DO UPDATE SET expire_date = EXCLUDED.expire_date", (uid, days))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"👑 **Admin Set:** ID {uid} (+{days} วัน)")
    except: await update.message.reply_text("`/setadmin [ID] [วัน]`")

async def undo_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ **已撤销**")
    await send_summary(update, context)

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (uid,))
    res = cursor.fetchone(); cursor.close(); conn.close()
    if str(uid) == str(MASTER_ADMIN): return await update.message.reply_text("👑 **MASTER ADMIN**")
    msg = f"📅 ถึง: `{res[0].strftime('%Y-%m-%d %H:%M')}`" if res else "❌ ยังไม่เปิดสมาชิก"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def handle_accounting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip(); match = re.match(r'^([+-])(\d+)$', text)
    if match:
        if not await check_access(update.message.from_user.id, update.effective_chat.id): return
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', (update.effective_chat.id, amt, update.message.from_user.first_name))
        conn.commit(); cursor.close(); conn.close()
        await send_summary(update, context)

# --- 🚀 RUN BOT ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(os.getenv('TOKEN')).build()
    if app.job_queue: app.job_queue.run_repeating(auto_verify_payment, interval=60)
    
    # ลงทะเบียน Handler (ลำดับฟังก์ชันถูกต้อง)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add", add_member))
    app.add_handler(CommandHandler("remove", remove_member))
    app.add_handler(CommandHandler("reset", reset_history))
    app.add_handler(CommandHandler("undo", undo_last))
    app.add_handler(CommandHandler("check", check_status))
    app.add_handler(CommandHandler("show", send_summary))
    app.add_handler(CommandHandler("setadmin", set_admin_manual))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_accounting))
    app.run_polling()
