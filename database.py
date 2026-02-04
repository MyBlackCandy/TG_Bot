import os
import psycopg2
from psycopg2.extras import RealDictCursor

def get_db_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"), sslmode='require')

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

def set_group_owner(chat_id, user_id, username):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO group_permissions (group_id, user_id, username, role) 
        VALUES (%s, %s, %s, 'owner')
        ON CONFLICT (group_id, user_id) DO UPDATE SET role = 'owner'
    """, (chat_id, user_id, username))
    conn.commit()
    conn.close()

def save_transaction(group_id, user_id, username, amount):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO transactions (group_id, user_id, username, amount) VALUES (%s, %s, %s, %s)", 
                (group_id, user_id, username, amount))
    conn.commit()
    conn.close()

def get_logs(group_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT username, amount FROM transactions WHERE group_id = %s ORDER BY created_at ASC", (group_id,))
    logs = cur.fetchall()
    conn.close()
    return logs
