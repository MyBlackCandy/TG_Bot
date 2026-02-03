import os
import psycopg2

DATABASE_URL = os.getenv('DATABASE_URL')

def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # ตารางสมาชิกหลัก
    cursor.execute('''CREATE TABLE IF NOT EXISTS customers (
        user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP, username TEXT, first_name TEXT
    )''')
    # ตารางลูกทีม
    cursor.execute('CREATE TABLE IF NOT EXISTS team_members (member_id BIGINT PRIMARY KEY, allowed_chat_id BIGINT)')
    # ตารางประวัติบัญชี
    cursor.execute('CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, chat_id BIGINT, amount INTEGER, user_name TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    # ตารางรอชำระเงิน (ต้องมีคอลัมน์ decimal_points)
    cursor.execute('''CREATE TABLE IF NOT EXISTS pending_payments (
        user_id BIGINT PRIMARY KEY, base_amount INTEGER, decimal_points DECIMAL, expire_at TIMESTAMP
    )''')
    conn.commit()
    cursor.close()
    conn.close()
