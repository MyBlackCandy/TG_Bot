import os
import psycopg2


# ==============================
# connect
# ==============================
def get_conn():
    return psycopg2.connect(os.getenv("DATABASE_URL"))


# ==============================
# init all tables
# ==============================
def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # --------------------------
    # groups (multi group core)
    # --------------------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS groups(
        chat_id BIGINT PRIMARY KEY,
        name TEXT,
        timezone INT DEFAULT 0,
        active BOOLEAN DEFAULT TRUE
    );
    """)

    # --------------------------
    # history (ledger records)
    # --------------------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS history(
        id SERIAL PRIMARY KEY,
        chat_id BIGINT,
        amount INT,
        user_name TEXT,
        timestamp TIMESTAMP DEFAULT NOW()
    );
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_history_chat
    ON history(chat_id);
    """)

    # --------------------------
    # team members
    # --------------------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS team(
        chat_id BIGINT,
        user_id BIGINT,
        name TEXT,
        PRIMARY KEY(chat_id, user_id)
    );
    """)

    # --------------------------
    # global admins
    # --------------------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS admins(
        user_id BIGINT PRIMARY KEY,
        expire_at TIMESTAMP
    );
    """)

    conn.commit()
    conn.close()
