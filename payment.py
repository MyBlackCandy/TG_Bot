import os
import requests
from datetime import datetime, timedelta
from database import get_db_connection

MY_USDT_ADDR = os.getenv('USDT_ADDRESS')

async def generate_payment_amount(user_id):
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('SELECT decimal_points FROM pending_payments WHERE user_id = %s', (user_id,))
    res = cursor.fetchone()
    decimal = float(res[0]) if res else 0.001
    if not res:
        cursor.execute('SELECT MAX(decimal_points) FROM pending_payments')
        max_val = cursor.fetchone()[0] or 0.000
        decimal = float(max_val) + 0.001
    
    base_price = 100.0
    expire_at = datetime.now() + timedelta(hours=24)
    cursor.execute('INSERT INTO pending_payments VALUES (%s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_at = EXCLUDED.expire_at', (user_id, base_price, decimal, expire_at))
    conn.commit(); cursor.close(); conn.close()
    return base_price + decimal

async def auto_verify_payment(context):
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('SELECT user_id, (base_amount + decimal_points) FROM pending_payments WHERE expire_at > %s', (datetime.now(),))
        pending = cursor.fetchall()
        if not pending: return

        url = "https://apilist.tronscan.org/api/token_trc20/transfers"
        params = {"limit": 20, "direction": "in", "relatedAddress": MY_USDT_ADDR}
        resp = requests.get(url, params=params, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json().get('token_transfers', [])
            for uid, target_amt in pending:
                for tx in data:
                    t_info = tx.get('tokenInfo', {})
                    if t_info.get('symbol') == 'USDT':
                        # คำนวณยอดโอนจริง
                        actual_amt = float(tx.get('quant', 0)) / (10 ** int(t_info.get('decimals', 6)))
                        if abs(actual_amt - float(target_amt)) < 0.0001:
                            new_exp = datetime.now() + timedelta(days=30)
                            cursor.execute('INSERT INTO customers (user_id, expire_date) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date', (uid, new_exp))
                            cursor.execute('DELETE FROM pending_payments WHERE user_id=%s', (uid,))
                            conn.commit()
                            await context.bot.send_message(chat_id=uid, text=f"✅ **支付成功!**\n📅 到期: `{new_exp.strftime('%Y-%m-%d %H:%M')}`")
        cursor.close(); conn.close()
    except: pass
