import os
import psycopg2

DATABASE_URL = os.getenv('DATABASE_URL')

def get_db_connection():
    # แก้ไข Prefix สำหรับ SQLAlchemy/Psycopg2 compatibility
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection(); cursor = conn.cursor()
    # 1. ตารางลูกค้า (เก็บวันหมดอายุ)
    cursor.execute('''CREATE TABLE IF NOT EXISTS customers (
        user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP, username TEXT
    )''')
    # 2. ตารางลูกทีม (เก็บสิทธิ์รายกลุ่ม)
    cursor.execute('''CREATE TABLE IF NOT EXISTS team_members (
        member_id BIGINT PRIMARY KEY, allowed_chat_id BIGINT
    )''')
    # 3. ตารางประวัติ (ระบบจดบัญชี)
    cursor.execute('''CREATE TABLE IF NOT EXISTS history (
        id SERIAL PRIMARY KEY, chat_id BIGINT, amount INTEGER, 
        user_name TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit(); cursor.close(); conn.close()
