import os
import psycopg2
import logging

def get_db_connection():
    try:
        # เปลี่ยน postgres:// เป็น postgresql:// เพื่อความเข้ากันได้
        url = os.getenv('DATABASE_URL').replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url, sslmode='require')
    except Exception as e:
        logging.error(f"❌ DB Connect Error: {e}")
        return None

def init_db():
    """ฟังก์ชันบังคับสร้างตารางทั้งหมด"""
    conn = get_db_connection()
    if not conn: return
    try:
        cursor = conn.cursor()
        # 1. ตารางตั้งค่ากลุ่ม
        cursor.execute('''CREATE TABLE IF NOT EXISTS chat_settings (
            chat_id BIGINT PRIMARY KEY, title TEXT, 
            timezone INTEGER DEFAULT 0, is_active BOOLEAN DEFAULT TRUE)''')
        # 2. ตารางแอดมินสากล
        cursor.execute('''CREATE TABLE IF NOT EXISTS admins (
            user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP NOT NULL)''')
        # 3. ตารางทีมงานรายกลุ่ม
        cursor.execute('''CREATE TABLE IF NOT EXISTS team_members (
            member_id BIGINT, chat_id BIGINT, username TEXT, 
            PRIMARY KEY (member_id, chat_id))''')
        # 4. ตารางประวัติบัญชี
        cursor.execute('''CREATE TABLE IF NOT EXISTS history (
            id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, amount INTEGER NOT NULL, 
            user_name TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        cursor.close(); conn.close()
        print("✅ [Database] All tables created successfully!")
    except Exception as e:
        print(f"❌ [Database] Error creating tables: {e}")
