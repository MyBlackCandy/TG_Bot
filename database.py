import os
import psycopg2
import logging

def get_db_connection():
    """เชื่อมต่อกับ PostgreSQL โดยรองรับ URL จาก Railway"""
    try:
        # เปลี่ยน prefix จาก postgres:// เป็น postgresql:// เพื่อความเข้ากันได้ของ Library
        url = os.getenv('DATABASE_URL').replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(url, sslmode='require')
        return conn
    except Exception as e:
        logging.error(f"❌ Database Connection Error: {e}")
        return None

def init_db():
    """สร้างตารางที่จำเป็นทั้งหมดหากยังไม่มีในระบบ"""
    conn = get_db_connection()
    if conn is None:
        return

    try:
        cursor = conn.cursor()

        # 1. ตารางแอดมิน (Global Admin - ใช้ได้ทุกกลุ่ม)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY,
                expire_date TIMESTAMP NOT NULL
            )
        ''')

        # 2. ตารางทีมงาน/ผู้ช่วยจด (Local Team - แยกตามกลุ่ม)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS team_members (
                member_id BIGINT,
                chat_id BIGINT,
                username TEXT,
                PRIMARY KEY (member_id, chat_id)
            )
        ''')

        # 3. ตารางตั้งค่ากลุ่ม (Timezone และการลงทะเบียนกลุ่ม)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id BIGINT PRIMARY KEY,
                timezone INTEGER DEFAULT 0
            )
        ''')

        # 4. ตารางประวัติการจดบัญชี (Transaction History)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                amount INTEGER NOT NULL,
                user_name TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        cursor.close()
        conn.close()
        logging.info("✅ Database initialized successfully with 4 tables.")
    except Exception as e:
        logging.error(f"❌ Database Init Error: {e}")
