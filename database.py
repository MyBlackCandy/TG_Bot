import os
import re
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ChatMemberHandler
import database as db

ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

def format_history(logs):
    if not logs: return "ยังไม่มีรายการ"
    count = len(logs)
    lines = [f"{i+1}. {log['amount']:+d} (@{log['username']})" for i, log in enumerate(logs)]
    if count <= 6: return "\n".join(lines)
    # แสดง 3 อันแรก และ 3 อันสุดท้ายตามเงื่อนไขที่ตั้งไว้
    return "\n".join(lines[:3]) + "\n... (ย่อรายการ) ...\n" + "\n".join(lines[-3:])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    role = db.get_user_role(chat_id, user_id)
    if user_id == ADMIN_ID or db.is_global_user(user_id) or role:
        await update.message.reply_text("✨ บอทพร้อมทำงานแล้ว!")
    else:
        await update.message.reply_text("❌ คุณยังไม่มีสิทธิการใช้งาน โปรดติดต่อแอดมิน")

async def handle_record(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username or str(user_id)
    text = update.message.text
    
    match = re.match(r'^([+-])(\d+)$', text)
    if not match: return

    # ระบบ Auto-Wakeup: ถ้าคนพิมพ์คือคนมีสิทธิ์แต่กลุ่มยังไม่ลงทะเบียน ให้ตั้งเป็นเจ้าของทันที
    if not db.get_user_role(chat_id, user_id) and (db.is_global_user(user_id) or user_id == ADMIN_ID):
        db.set_group_permission(chat_id, user_id, username, 'owner')

    role = db.get_user_role(chat_id, user_id)
    if user_id == ADMIN_ID: role = 'admin'
    
    if not role:
        await update.message.reply_text("❌ ไม่มีสิทธิ์ใช้งานในกลุ่มนี้ โปรดติดต่อแอดมิน")
        return

    # บันทึกยอดและแสดงสรุป
    db.save_transaction(chat_id, user_id, username, int(text))
    logs = db.get_logs(chat_id)
    total = sum(log['amount'] for log in logs)
    await update.message.reply_text(
        f"✅ บันทึก: {text}\n\n{format_history(logs)}\n\n💰 ยอดรวม: {total:,.0f}", 
        parse_mode='Markdown'
    )

async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sub = db.get_subscription(user_id)
    res = f"🔍 ID: `{user_id}`\n"
    if user_id == ADMIN_ID:
        res += "👑 สถานะ: แอดมินสูงสุด"
    elif sub:
        now = datetime.now()
        diff = sub['expiry_date'] - now
        if diff.total_seconds() > 0:
            res += f"✅ สถานะ: ผู้ใช้งาน\n⏳ คงเหลือ: {diff.days} วัน {diff.seconds//3600} ชม. { (diff.seconds//60)%60 } นาที"
        else:
            res += "🔴 สถานะ: หมดอายุแล้ว"
    else:
        res += "❌ ไม่มีสิทธิ์ใช้งาน"
    await update.message.reply_text(res, parse_mode='Markdown')

async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    last = db.get_last_transaction(chat_id)
    if not last: return await update.message.reply_text("❌ ไม่พบรายการ")
    
    role = db.get_user_role(chat_id, user_id)
    if user_id == ADMIN_ID: role = 'admin'
    
    # คนช่วยงานยกเลิกได้เฉพาะของตัวเอง
    if role == 'helper' and last['user_id'] != user_id:
        await update.message.reply_text("❌ ลบได้เฉพาะรายการของตัวเอง")
    elif role in ['admin', 'owner', 'helper']:
        db.delete_transaction(last['id'])
        await update.message.reply_text(f"🔄 ยกเลิกรายการ {last['amount']} สำเร็จ")

async def on_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.my_chat_member.new_chat_member.status == "member":
        await context.bot.send_message(
            update.effective_chat.id, 
            "⚠️ บอทเข้ากลุ่มแล้ว! รอผู้ใช้งานที่มีสิทธิ์เริ่มพิมพ์ข้อความเพื่อเปิดระบบ"
        )

# --- คำสั่งจัดการทีม ---
async def add_helper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("⚠️ โปรด Reply ข้อความของคนช่วยงาน")
    target = update.message.reply_to_message.from_user
    db.set_group_permission(update.effective_chat.id, target.id, target.username, 'helper')
    await update.message.reply_text(f"✅ เพิ่ม @{target.username} เป็นคนช่วยงานแล้ว")

if __name__ == '__main__':
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check))
    app.add_handler(CommandHandler("undo", undo))
    app.add_handler(CommandHandler("add", add_helper))
    app.add_handler(CommandHandler("reset", lambda u, c: db.clear_transactions(u.effective_chat.id) or u.message.reply_text("🗑 รีเซ็ตยอดแล้ว")))
    app.add_handler(CommandHandler("resetadd", lambda u, c: db.clear_helpers(u.effective_chat.id) or u.message.reply_text("👥 ล้างคนช่วยงานแล้ว")))
    app.add_handler(ChatMemberHandler(on_join, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.Regex(r'^[+-]\d+$'), handle_record))
    app.run_polling()
