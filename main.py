import os
import re
import psycopg2
import requests
import random
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- ⚙️ CONFIGURATION ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')
MY_USDT_ADDR = os.getenv('USDT_ADDRESS')

# --- 🗄️ DATABASE SYSTEM ---
def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS customers (
        user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP, username TEXT, first_name TEXT
    )''')
    cursor.execute('CREATE TABLE IF NOT EXISTS team_members (member_id BIGINT PRIMARY KEY, leader_id BIGINT, allowed_chat_id BIGINT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, chat_id BIGINT, amount INTEGER, user_name TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cursor.execute('CREATE TABLE IF NOT EXISTS used_transactions (tx_id TEXT PRIMARY KEY, user_id BIGINT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS pending_payments (user_id BIGINT PRIMARY KEY, amount DECIMAL, expire_at TIMESTAMP)')
    conn.commit(); cursor.close(); conn.close()

def check_access(user_id, chat_id):
    if str(user_id) == str(MASTER_ADMIN): return True
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM customers WHERE user_id = %s AND expire_date > %s', (user_id, datetime.now()))
    is_cust = cursor.fetchone()
    if is_cust: 
        cursor.close(); conn.close(); return True
    cursor.execute('SELECT 1 FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (user_id, chat_id))
    res = cursor.fetchone(); cursor.close(); conn.close()
    return True if res else False

# ==========================================
# ส่วนที่ 1: การชำระเงินและการตรวจสอบอัตโนมัติ
# ==========================================


# ส่วนนี้จะทำงานทุกๆ 30 วินาทีในพื้นหลัง
async def auto_verify_task(context: ContextTypes.DEFAULT_TYPE):
    # ... (ดึงข้อมูลจาก TronScan API) ...
    
    if abs(tx_amt - float(amt)) < 0.001: # 1. ถ้าตรวจเจอว่าโอนเงินมาตรงเป๊ะ
        if not already_used: # 2. และเป็นรายการใหม่ (ไม่เคยใช้มาก่อน)
            
            # --- [ ส่วนการคำนวณเวลาอัตโนมัติ ] ---
            cursor.execute('SELECT expire_date FROM customers WHERE user_id=%s', (uid,))
            old_data = cursor.fetchone()
            
            # ถ้ายังมีวันเหลือ ให้บวกเพิ่มจากวันเดิม / ถ้าหมดแล้วหรือเป็นคนใหม่ ให้เริ่มนับจากวันนี้
            base_date = old_data[0] if old_data and old_data[0] > datetime.now() else datetime.now()
            new_expire = base_date + timedelta(days=30) 
            
            # อัปเดตลงฐานข้อมูล
            cursor.execute('''INSERT INTO customers (user_id, expire_date) VALUES (%s, %s) 
                           ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date''', (uid, new_expire))
            
            # --- [ ส่วนการตอบกลับอัตโนมัติ ] ---
            await context.bot.send_message(
                chat_id=uid, 
                text=f"✅ **支付成功! (ชำระเงินสำเร็จ)**\n📅 อายุการใช้งานถูกเพิ่มแล้วถึง: `{new_expire.strftime('%Y-%m-%d %H:%M')}`"
            )
            
            # ลบรายการค้างชำระออก
            cursor.execute('DELETE FROM pending_payments WHERE user_id=%s', (uid,))
            conn.commit()

# ==========================================
# ส่วนที่ 2: การทำงานของบอท (Core Bot Logic)
# ==========================================


async def send_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT amount, user_name FROM history WHERE chat_id = %s ORDER BY timestamp ASC', (chat_id,))
    rows = cursor.fetchall()
    total = sum(r[0] for r in rows)
    count = len(rows)
    
    if count == 0: return await update.message.reply_text("📋 **当前无记录**")

    history_text = "...\n" if count > 5 else ""
    display_rows = rows[-5:] if count > 5 else rows
    start_num = max(1, count - 4) if count > 5 else 1
    
    for i, r in enumerate(display_rows):
        sign = "+" if r[0] > 0 else ""
        history_text += f"{start_num + i}. {sign}{r[0]} ({r[1]})\n"
    
    cursor.close(); conn.close()
    await update.message.reply_text(f"📊 **账目汇总**\n━━━━━━━━━━━━━━━\n{history_text}━━━━━━━━━━━━━━━\n💰 **总额: {total}**", parse_mode='Markdown')

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = ("📖 **帮助菜单 (Manual)**\n"
           "➕ พิมพ์ `+100` หรือ `-50` เพื่อจดบัญชี\n"
           "🔍 `/show` - ดูสรุปยอดล่าสุด\n"
           "↩️ `/undo` - ยกเลิกรายการล่าสุด\n"
           "🧹 `/reset` - ล้างบัญชีทั้งหมดในกลุ่ม\n"
           "✅ `/check` - เช็กสถานะวันหมดอายุ\n"
           "👥 `/add` / `/remove` - จัดการลูกทีม (Reply)\n"
           "📋 `/list` - ดูรายชื่อลูกทีม\n"
           "👑 `/setadmin` - ตั้งวันหมดอายุ (Admin Only)\n"
           "⏰ `/timenow` - เช็กเวลาปัจจุบันของระบบ")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE id = (SELECT id FROM history WHERE chat_id = %s ORDER BY timestamp DESC LIMIT 1)', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("↩️ **已撤销上一笔记录**")
    await send_summary(update, context)

async def reset_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM history WHERE chat_id = %s', (update.effective_chat.id,))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text("🧹 **账目已清空**")

async def add_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return await update.message.reply_text("⚠️ 请回复成员")
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    t = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO team_members VALUES (%s, %s, %s) ON CONFLICT (member_id) DO UPDATE SET allowed_chat_id=EXCLUDED.allowed_chat_id', (t.id, update.message.from_user.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"✅ **授权成功:** {t.first_name}")

async def remove_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message: return await update.message.reply_text("⚠️ 请回复成员")
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    t = update.message.reply_to_message.from_user
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM team_members WHERE member_id = %s AND allowed_chat_id = %s', (t.id, update.effective_chat.id))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"🚫 **已取消授权:** {t.first_name}")

async def list_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update.message.from_user.id, update.effective_chat.id): return
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT member_id FROM team_members WHERE allowed_chat_id = %s', (update.effective_chat.id,))
    rows = cursor.fetchall(); cursor.close(); conn.close()
    msg = "📋 **授权成员列表:**\n" + "\n".join([f"- `{r[0]}`" for r in rows]) if rows else "📋 **暂无授权成员**"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def set_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) != str(MASTER_ADMIN): return
    try:
        uid, days = int(context.args[0]), int(context.args[1])
        new_exp = datetime.now() + timedelta(days=days)
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO customers (user_id, expire_date) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date', (uid, new_exp))
        conn.commit(); cursor.close(); conn.close()
        await update.message.reply_text(f"✅ ID `{uid}` 已激活 {days} 天")
    except: await update.message.reply_text("`/setadmin [ID] [天数]`")

async def time_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"⏰ **System Time:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`")

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    match = re.match(r'^([+-])(\d+)$', text)
    if match:
        if not check_access(update.message.from_user.id, update.effective_chat.id): return
        amt = int(match.group(2)) if match.group(1) == '+' else -int(match.group(2))
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO history (chat_id, amount, user_name) VALUES (%s, %s, %s)', (update.effective_chat.id, amt, update.message.from_user.first_name))
        conn.commit(); cursor.close(); conn.close()
        await send_summary(update, context)

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if str(uid) == str(MASTER_ADMIN): return await update.message.reply_text("👑 **主管理员 | 永久有效**")
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT expire_date FROM customers WHERE user_id = %s', (uid,))
    res = cursor.fetchone(); cursor.close(); conn.close()
    if res and res[0] > datetime.now():
        return await update.message.reply_text(f"✅ **正常**\n📅 到期: `{res[0].strftime('%Y-%m-%d %H:%M')}`")
    await update.message.reply_text("❌ **权限未激活**")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private': return
    amt = 100 + (random.randint(1, 99) / 100)
    exp = datetime.now() + timedelta(minutes=15)
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO pending_payments VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET amount=EXCLUDED.amount, expire_at=EXCLUDED.expire_at', (update.message.from_user.id, amt, exp))
    conn.commit(); cursor.close(); conn.close()
    await update.message.reply_text(f"🚀 **激活系统**\n💳 金额: `{amt:.2f}` USDT\n地址: `{MY_USDT_ADDR}`")

# --- 🚀 RUN BOT ---
if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    if app.job_queue: app.job_queue.run_repeating(auto_verify_task, interval=30)
    
    # Register Commands
    cmds = [("help", help_cmd), ("undo", undo), ("reset", reset_history), ("add", add_member), 
            ("remove", remove_member), ("list", list_members), ("setadmin", set_admin), 
            ("check", check_status), ("show", send_summary), ("start", start), ("timenow", time_now)]
    for cmd, func in cmds: app.add_handler(CommandHandler(cmd, func))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.run_polling()
