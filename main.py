from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

async def send_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # ดึงข้อมูลและสรุปยอดเหมือนเดิม
    # ... (ส่วน SQL ดึงข้อมูล) ...

    # ✅ เปลี่ยนจาก url= เป็น web_app=WebAppInfo(url=...)
    # ลิงก์ต้องเป็น HTTPS เท่านั้น
    report_url = f"https://tgbot-production-d541.up.railway.app/index.php?c={chat_id}"
    
    keyboard = [[
        InlineKeyboardButton(
            text="📊 打开账单小程序 (เปิดรายงานแบบ Mini App)", 
            web_app=WebAppInfo(url=report_url)
        )
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        text=f"📊 **账目汇总**\n💰 总额: {total}",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
