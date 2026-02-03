from telegram.ext import Application, CommandHandler, MessageHandler, filters
from database import init_db
from payment import generate_payment_amount, auto_verify_payment

async def start(update, context):
    uid = update.effective_user.id
    amount = await generate_payment_amount(uid)
    await update.message.reply_text(
        f"🚀 **ระบบเปิดสิทธิ์อัตโนมัติ**\n\n"
        f"💳 ยอดที่ต้องโอน: `{amount:.3f}` USDT\n"
        f"📍 ที่อยู่ TRC20: `{os.getenv('USDT_ADDRESS')}`\n\n"
        f"⚠️ **โปรดโอนยอดให้ตรงทศนิยมเป๊ะๆ** เพื่อให้ระบบเปิดสิทธิ์ทันที"
    )

# ... (เพิ่ม Handler อื่นๆ เช่น handle_msg, undo, reset) ...

if __name__ == '__main__':
    init_db()
    app = Application.builder().token(os.getenv('TOKEN')).build()
    app.job_queue.run_repeating(auto_verify_payment, interval=60) # เช็กทุก 1 นาที
    app.add_handler(CommandHandler("start", start))
    app.run_polling()
