import os
import psycopg2
import logging

def get_db_connection():
    url = os.getenv('DATABASE_URL').replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection()
    if conn is None: return
    try:
        cursor = conn.cursor()
        # 1. แอดมิน (สิทธิ์ Global - ใช้ได้ทุกกลุ่ม)
        cursor.execute('''CREATE TABLE IF NOT EXISTS admins (
            user_id BIGINT PRIMARY KEY, 
            expire_date TIMESTAMP NOT NULL,
            role TEXT DEFAULT 'admin' -- 'master' หรือ 'admin'
        )''')
        
        # 2. ตั้งค่ากลุ่ม (แยกตาม chat_id)
        cursor.execute('''CREATE TABLE IF NOT EXISTS chat_settings (
            chat_id BIGINT PRIMARY KEY, 
            timezone INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE
        )''')
        
        # 3. ทีมงานช่วยจด (สิทธิ์ Local - แยกตามกลุ่ม)
        cursor.execute('''CREATE TABLE IF NOT EXISTS team_members (
            member_id BIGINT, 
            chat_id BIGINT, 
            username TEXT, 
            PRIMARY KEY (member_id, chat_id)
        )''')
        
        # 4. ประวัติการจด (แยกตามกลุ่มชัดเจน)
        cursor.execute('''CREATE TABLE IF NOT EXISTS history (
            id SERIAL PRIMARY KEY, 
            chat_id BIGINT NOT NULL, 
            amount INTEGER NOT NULL, 
            user_name TEXT, 
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        conn.commit()
        cursor.close(); conn.close()
    except Exception as e:
        logging.error(f"❌ DB Init Error: {e}")
