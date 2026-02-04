import os
import psycopg2
import logging

def get_db_connection():
    try:
        # 适配 Railway 环境变量
        url = os.getenv('DATABASE_URL').replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url, sslmode='require')
    except Exception as e:
        logging.error(f"❌ 数据库连接失败: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if not conn: return
    try:
        cursor = conn.cursor()
        # 1. 群组设置表（增加 title 列以匹配您的新需求）
        cursor.execute('''CREATE TABLE IF NOT EXISTS chat_settings (
            chat_id BIGINT PRIMARY KEY, 
            title TEXT, 
            timezone INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE)''')
        
        # 2. 全局管理员表（由 Master 授权）
        cursor.execute('''CREATE TABLE IF NOT EXISTS admins (
            user_id BIGINT PRIMARY KEY, 
            expire_date TIMESTAMP NOT NULL)''')
        
        # 3. 群组操作员表 (Local Team)
        cursor.execute('''CREATE TABLE IF NOT EXISTS team_members (
            member_id BIGINT, 
            chat_id BIGINT, 
            username TEXT, 
            PRIMARY KEY (member_id, chat_id))''')
        
        # 4. 账目历史表
        cursor.execute('''CREATE TABLE IF NOT EXISTS history (
            id SERIAL PRIMARY KEY, 
            chat_id BIGINT NOT NULL, 
            amount INTEGER NOT NULL, 
            user_name TEXT, 
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        conn.commit()
        cursor.close(); conn.close()
        logging.info("✅ 数据库结构初始化完成")
    except Exception as e:
        logging.error(f"❌ 初始化失败: {e}")
