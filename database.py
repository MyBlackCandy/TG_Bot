import os
import psycopg2

def get_db_connection():
    DATABASE_URL = os.getenv('DATABASE_URL')
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

def init_db():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS admins (user_id BIGINT PRIMARY KEY, expire_date TIMESTAMP)')
    cursor.execute('CREATE TABLE IF NOT EXISTS chat_settings (chat_id BIGINT PRIMARY KEY, timezone INTEGER DEFAULT 0)')
    cursor.execute('CREATE TABLE IF NOT EXISTS team_members (member_id BIGINT, chat_id BIGINT, username TEXT, PRIMARY KEY(member_id, chat_id))')
    cursor.execute('CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, chat_id BIGINT, amount INTEGER, user_name TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    conn.commit(); cursor.close(); conn.close()
