import os
import psycopg2
from datetime import datetime

def get_db_connection():
    url = os.getenv('DATABASE_URL').replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def get_user_info(user_id):
    """ดึงข้อมูลวันหมดอายุของผู้ใช้"""
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT expire_date FROM admins WHERE user_id = %s", (user_id,))
    res = cursor.fetchone()
    cursor.close(); conn.close()
    return res[0] if res else None

def get_user_role(user_id, chat_id):
    master_id = os.getenv('ADMIN_ID')
    if str(user_id) == str(master_id): return "master"
    
    expire_date = get_user_info(user_id)
    if expire_date and expire_date > datetime.utcnow(): 
        return "admin"
    
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM team_members WHERE member_id = %s AND chat_id = %s", (user_id, chat_id))
    is_team = cursor.fetchone()
    cursor.close(); conn.close()
    return "team" if is_team else None
