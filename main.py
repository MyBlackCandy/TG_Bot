# แก้ไขฟังก์ชัน get_now_cn ให้เป็น Aware datetime เสมอ
def get_now_cn():
    return datetime.now(timezone(timedelta(hours=8)))

# แก้ไขฟังก์ชัน check_status เพื่อป้องกัน TypeError
async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if str(uid) == str(MASTER_ADMIN):
        return await update.message.reply_text("👑 **身份: 系统主管理员**\n🌟 **状态: 永久有效**")
    
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (uid,))
    res = cursor.fetchone(); cursor.close(); conn.close()
    
    if res and res[0]:
        db_time = res[0]
        # บังคับให้เป็น Aware datetime ก่อนเปรียบเทียบ
        if db_time.tzinfo is None:
            db_time = db_time.replace(tzinfo=timezone(timedelta(hours=8)))
            
        if db_time > get_now_cn():
            exp_cn = db_time.astimezone(timezone(timedelta(hours=8)))
            await update.message.reply_text(f"✅ **状态: 正常**\n📅 **到期:** `{exp_cn.strftime('%Y-%m-%d %H:%M')}`")
            return

    await update.message.reply_text("❌ **权限未激活**\n请私聊 /start 获取支付地址。")
