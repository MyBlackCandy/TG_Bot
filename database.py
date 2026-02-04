import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta

def get_db_connection():
    # ดึงค่า DATABASE_URL จาก Railway อัตโนมัติ
    return psycopg2.connect(os.getenv("DATABASE_URL"), sslmode='require')

# --- การจัดการสิทธิ์ ---
def is_global_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users_subscription WHERE user_id = %s AND expiry_date > NOW()", (user_id,))
    res = cur.fetchone()
    conn.close()
    return True if res else False

def get_user_role(chat_id, user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT role FROM group_permissions WHERE group_id = %s AND user_id = %s", (chat_id, user_id))
    res = cur.fetchone()
    conn.close()
    return res[0] if res else None

def set_group_permission(chat_id, user_id, username, role):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO group_permissions (group_id, user_id, username, role) 
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (group_id, user_id) DO UPDATE SET role = EXCLUDED.role
    """, (chat_id, user_id, username, role))
    conn.commit()
    conn.close()

def get_subscription(user_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT expiry_date FROM users_subscription WHERE user_id = %s", (user_id,))
    res = cur.fetchone()
    conn.close()
    return res

# --- การจัดการรายการบันทึก ---
def save_transaction(group_id, user_id, username, amount):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO transactions (group_id, user_id, username, amount) VALUES (%s, %s, %s, %s)", 
                (group_id, user_id, username, amount))
    conn.commit()
    conn.close()

def get_logs(group_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT username, amount FROM transactions WHERE group_id = %s ORDER BY created_at ASC", (group_id,))
    res = cur.fetchall()
    conn.close()
    return res

def get_last_transaction(group_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, amount, user_id FROM transactions WHERE group_id = %s ORDER BY created_at DESC LIMIT 1", (group_id,))
    res = cur.fetchone()
    conn.close()
    return res

def delete_transaction(t_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM transactions WHERE id = %s", (t_id,))
    conn.commit()
    conn.close()

def clear_transactions(group_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM transactions WHERE group_id = %s", (group_id,))
    conn.commit()
    conn.close()

def clear_helpers(chat_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM group_permissions WHERE group_id = %s AND role = 'helper'", (chat_id,))
    conn.commit()
    conn.close()
    

# --- ฟังก์ชันสำหรับ Admin เท่านั้น ---

def add_subscription_by_username(username, days, user_id=None):
    """เพิ่มหรืออัปเดตวันหมดอายุของผู้ใช้"""
    conn = get_db_connection()
    cur = conn.cursor()
    expiry_date = datetime.now() + timedelta(days=days)
    
    # ถ้ามี user_id (เช็คจากประวัติการพิมพ์) ให้ใช้ ID จะแม่นยำกว่า
    cur.execute("""
        INSERT INTO users_subscription (user_id, username, expiry_date, status)
        VALUES (%s, %s, %s, 'active')
        ON CONFLICT (user_id) DO UPDATE 
        SET expiry_date = users_subscription.expiry_date + INTERVAL '%s days',
            username = EXCLUDED.username
    """, (user_id, username.replace("@",""), expiry_date, days))
    
    conn.commit()
    conn.close()

def get_all_users():
    """ดึงรายชื่อผู้ใช้ทั้งหมด"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT username, expiry_date FROM users_subscription ORDER BY expiry_date DESC")
    res = cur.fetchall()
    conn.close()
    return res

def get_all_groups():
    """ดึงรายชื่อกลุ่มที่มีการลงทะเบียน Owner ไว้"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT DISTINCT group_id, username FROM group_permissions WHERE role = 'owner'")
    res = cur.fetchall()
    conn.close()
    return res
