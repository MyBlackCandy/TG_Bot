import os
import psycopg2

def get_db_connection():
    # แก้ไข Prefix สำหรับ Railway PostgreSQL
    url = os.getenv('DATABASE_URL').replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection(); cursor = conn.cursor()
    # ตารางแอดมิน (เก็บวันหมดอายุ)
    cursor.execute('CREATE TABLE IF NOT EXISTS admins (user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP)')
    # ตารางตั้งค่าโซนเวลาแต่ละกลุ่ม
    cursor.execute('CREATE TABLE IF NOT EXISTS chat_settings (chat_id BIGINT PRIMARY KEY, timezone INTEGER DEFAULT 0)')
    # ตารางทีมงานบันทึก (Team)
    cursor.execute('CREATE TABLE IF NOT EXISTS team_members (member_id BIGINT, chat_id BIGINT, username TEXT, PRIMARY KEY(member_id, chat_id))')
    # ตารางประวัติบันทึก (แก้ไข Type cast เพื่อป้องกัน Error ในภาพ 5f2694)
    cursor.execute('CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, chat_id BIGINT, amount INTEGER, user_name TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    conn.commit(); cursor.close(); conn.close()
