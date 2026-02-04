import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta

# เชื่อมต่อ Database โดยใช้ URL จาก Railway Environment Variable
def get_db_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"), sslmode='require')

# --- ส่วนจัดการสิทธิ์ (Permissions) ---

def is_global_user(user_id):
    """ตรวจสอบว่า User ID นี้มีแพ็กเกจการใช้งานที่ยังไม่หมดอายุหรือไม่"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM users_subscription WHERE user_id = %s AND expiry_date > NOW() AND status = 'active'",
        (user_id,)
    )
    res = cur.fetchone()
    conn.close()
    return True if res else False

def get_user_role(chat_id, user_id):
    """ดึงบทบาทของผู้ใช้ในกลุ่มนั้นๆ (owner/helper)"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT role FROM group_permissions WHERE group_id = %s AND user_id = %s",
        (chat_id, user_id)
    )
    res = cur.fetchone()
    conn.close()
    return res[0] if res else None

def get_group_owner(chat_id):
    """หาว่าใครเป็นเจ้าของกลุ่มนี้"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM group_permissions WHERE group_id = %s AND role = 'owner'", (chat_id,))
    res = cur.fetchone()
    conn.close()
    return res[0] if res else None

def set_group_owner(chat_id, user_id, username):
    """ตั้งค่าเจ้าของกลุ่ม (Auto-Register)"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO group_permissions (group_id, user_id, username, role)
        VALUES (%s, %s, %s, 'owner')
        ON CONFLICT (group_id, user_id) DO UPDATE SET role = 'owner'
    """, (chat_id, user_id, username))
    conn.commit()
    conn.close()

def set_group_helper(chat_id, user_id, username):
    """เพิ่มคนช่วยงานในกลุ่ม"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO group_permissions (group_id, user_id, username, role)
        VALUES (%s, %s, %s, 'helper')
        ON CONFLICT (group_id, user_id) DO UPDATE SET role = 'helper'
    """, (chat_id, user_id, username))
    conn.commit()
    conn.close()

def clear_helpers(chat_id):
    """ล้างรายชื่อคนช่วยงานทั้งหมดในกลุ่ม (เหลือแต่ Owner)"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM group_permissions WHERE group_id = %s AND role = 'helper'", (chat_id,))
    conn.commit()
    conn.close()

# --- ส่วนจัดการวันใช้งาน (Subscription) ---

def get_subscription(user_id):
    """ดึงข้อมูลวันหมดอายุของผู้ใช้"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT expiry_date FROM users_subscription WHERE user_id = %s", (user_id,))
    res = cur.fetchone()
    conn.close()
    return res

def add_subscription_by_username(username, days):
    """แอดมินตั้งวันใช้งานให้ผ่าน Username"""
    conn = get_db_connection()
    cur = conn.cursor()
    new_expiry = datetime.now() + timedelta(days=days)
    cur.execute("""
        INSERT INTO users_subscription (username, expiry_date, status)
        VALUES (%s, %s, 'active')
        ON CONFLICT (user_id) DO UPDATE SET expiry_date = users_subscription.expiry_date + INTERVAL '%s days'
    """, (username, new_expiry, days))
    # หมายเหตุ: ในทางปฏิบัติควรใช้ user_id แต่ถ้าใช้ username ต้องปรับ logic ค้นหา ID ก่อน
    conn.commit()
    conn.close()

# --- ส่วนจัดการรายการบันทึก (Transactions) ---

def save_transaction(group_id, user_id, username, amount):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO transactions (group_id, user_id, username, amount) VALUES (%s, %s, %s, %s)",
        (group_id, user_id, username, amount)
    )
    conn.commit()
    conn.close()

def get_logs(group_id):
    """ดึงรายการทั้งหมดในกลุ่มนั้นๆ"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT username, amount FROM transactions WHERE group_id = %s ORDER BY created_at ASC",
        (group_id,)
    )
    res = cur.fetchall()
    conn.close()
    return res

def get_last_transaction(group_id):
    """ดึงรายการล่าสุดเพื่อทำ Undo"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT id, amount, user_id FROM transactions WHERE group_id = %s ORDER BY created_at DESC LIMIT 1",
        (group_id,)
    )
    res = cur.fetchone()
    conn.close()
    return res

def delete_last_transaction(transaction_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM transactions WHERE id = %s", (transaction_id,))
    conn.commit()
    conn.close()

def clear_transactions(group_id):
    """ล้างยอดทั้งหมดในกลุ่มนั้นๆ (คำสั่ง /reset)"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM transactions WHERE group_id = %s", (group_id,))
    conn.commit()
    conn.close()
