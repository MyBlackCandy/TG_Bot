import os
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set")


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 群组设置
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_settings (
        chat_id BIGINT PRIMARY KEY,
        timezone INTEGER DEFAULT 0,
        work_start TIME DEFAULT '00:00'
    );
    """)

    # 账单记录
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS history (
        id SERIAL PRIMARY KEY,
        chat_id BIGINT NOT NULL,
        amount INTEGER NOT NULL,
        user_name TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_history_chat_time
    ON history(chat_id, timestamp);
    """)

    # 操作者
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS team_members (
        member_id BIGINT,
        chat_id BIGINT,
        username TEXT,
        PRIMARY KEY (member_id, chat_id)
    );
    """)

    # Owner（有期限）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        user_id BIGINT PRIMARY KEY,
        expire_date TIMESTAMP NOT NULL
    );
    """)

    conn.commit()
    cursor.close()
    conn.close()
