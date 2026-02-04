import os
import psycopg2
import logging

def get_db_connection():
    try:
        url = os.getenv('DATABASE_URL').replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url, sslmode='require')
    except Exception as e:
        logging.error(f"❌ Connection Error: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if not conn: return
    try:
        cursor = conn.cursor()
        # 1. แอดมิน (Global - ใช้งานได้ทุกกลุ่ม)
        cursor.execute('''CREATE TABLE IF NOT EXISTS admins (
            user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP NOT NULL)''')
        # 2. ตั้งค่ากลุ่มและ Timezone (หัวใจของ Auto-Register)
        cursor.execute('''CREATE TABLE IF NOT EXISTS chat_settings (
            chat_id BIGINT PRIMARY KEY, timezone INTEGER DEFAULT 0)''')
        # 3. ทีมงานช่วยจด (Local - แยกรายกลุ่ม)
        cursor.execute('''CREATE TABLE IF NOT EXISTS team_members (
            member_id BIGINT, chat_id BIGINT, username TEXT, PRIMARY KEY (member_id, chat_id))''')
        # 4. ประวัติการบันทึก (แยกรายกลุ่ม)
        cursor.execute('''CREATE TABLE IF NOT EXISTS history (
            id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, amount INTEGER NOT NULL, 
            user_name TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        cursor.close(); conn.close()
    except Exception as e:
        logging.error(f"❌ Init DB Error: {e}")
