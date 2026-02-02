import os
import re
import psycopg2
import random
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, redirect, session
from threading import Thread
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- Configuration ---
TOKEN = os.getenv('TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
MASTER_ADMIN = os.getenv('ADMIN_ID')
WEB_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin1234')

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- Database Utils ---
def get_db_connection():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode='require')

# --- Flask Web Routes (Admin Panel) ---
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>AK Bot Admin Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    <div class="container mt-5">
        <h2 class="mb-4">🚀 AK Bot Management</h2>
        
        <div class="card shadow-sm mb-4">
            <div class="card-header bg-primary text-white">รายชื่อ Admin (ผู้ชำระเงิน)</div>
            <div class="card-body">
                <table class="table">
                    <thead><tr><th>User ID</th><th>วันหมดอายุ</th><th>จัดการ</th></tr></thead>
                    <tbody>
                        {% for user in users %}
                        <tr>
                            <td>{{ user[0] }}</td>
                            <td>{{ user[1].strftime('%Y-%m-%d %H:%M') }}</td>
                            <td><a href="/delete/{{ user[0] }}" class="btn btn-danger btn-sm">ลบ</a></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
'''

@app.route('/')
def dashboard():
    if not session.get('logged_in'):
        return '''<form action="/login" method="post" class="p-5">
                    <input type="password" name="password" placeholder="Password">
                    <button type="submit">Login</button>
                  </form>'''
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, expire_date FROM paid_users ORDER BY expire_date DESC')
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template_string(HTML_TEMPLATE, users=users)

@app.route('/login', method=['POST'])
def login():
    if request.form.get('password') == WEB_PASSWORD:
        session['logged_in'] = True
    return redirect('/')

@app.route('/delete/<int:user_id>')
def delete_user(user_id):
    if session.get('logged_in'):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM paid_users WHERE user_id = %s', (user_id,))
        conn.commit()
        cursor.close()
        conn.close()
    return redirect('/')

# --- Telegram Bot Logic ---
# (ใช้ฟังก์ชัน handle_calc, start, check_payment จากโค้ดก่อนหน้า)
async def handle_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... logic คำนวณเดิมของคุณ ...
    pass

# --- Runner ---
def run_flask():
    # Railway จะให้ Port มาทาง Environment Variable
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    # รัน Web Dashboard แยก Thread
    Thread(target=run_flask).start()
    
    # รัน Telegram Bot
    application = Application.builder().token(TOKEN).build()
    # add handlers...
    application.run_polling()
