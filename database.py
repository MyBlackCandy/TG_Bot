import os
import psycopg2
import logging

def get_db_connection():
    try:
        url = os.getenv('DATABASE_URL').replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url, sslmode='require')
    except Exception as e:
        logging.error(f"❌ Database Connection Error: {e}")
        return None

def init_db():
    """สร้างตารางทั้งหมดหากยังไม่มีในระบบ"""
    conn = get_db_connection()
    if not conn:
        logging.error("❌ Cannot connect to DB to initialize tables")
        return
    try:
        cursor = conn.cursor()
        # 1. ข้อมูลกลุ่มและการตั้งค่า
        cursor.execute('''CREATE TABLE IF NOT EXISTS chat_settings (
            chat_id BIGINT PRIMARY KEY, 
            title TEXT, 
            timezone INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE)''')
        # 2. แอดมินสากล (Global Admin)
        cursor.execute('''CREATE TABLE IF NOT EXISTS admins (
            user_id BIGINT PRIMARY KEY, 
            expire_date TIMESTAMP NOT NULL)''')
        # 3. คนบันทึกรายกลุ่ม (Local Team)
        cursor.execute('''CREATE TABLE IF NOT EXISTS team_members (
            member_id BIGINT, chat_id BIGINT, username TEXT, 
            PRIMARY KEY (member_id, chat_id))''')
        # 4. ประวัติการจดบันทึก
        cursor.execute('''CREATE TABLE IF NOT EXISTS history (
            id SERIAL PRIMARY KEY, 
            chat_id BIGINT NOT NULL, 
            amount INTEGER NOT NULL, 
            user_name TEXT, 
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        cursor.close(); conn.close()
        logging.info("✅ All tables initialized or verified successfully")
    except Exception as e:
        logging.error(f"❌ Init DB Error: {e}")
