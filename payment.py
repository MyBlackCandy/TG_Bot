import requests
from datetime import datetime, timedelta
from database import get_db_connection

MY_USDT_ADDR = os.getenv('USDT_ADDRESS')

async def generate_payment_amount(user_id):
    """กำหนดทศนิยมคงที่ให้ลูกค้าแต่ละคน เริ่มที่ 0.001"""
    conn = get_db_connection(); cursor = conn.cursor()
    
    # เช็กว่าเคยมีทศนิยมประจำตัวหรือยัง
    cursor.execute('SELECT decimal_points FROM pending_payments WHERE user_id = %s', (user_id,))
    res = cursor.fetchone()
    
    if res:
        decimal = res[0]
    else:
        # ถ้ายังไม่มี ให้หาทศนิยมล่าสุดในระบบแล้ว +0.001
        cursor.execute('SELECT MAX(decimal_points) FROM pending_payments')
        max_decimal = cursor.fetchone()[0] or 0.000
        decimal = max_decimal + 0.001
    
    base_price = 100 # ยอดหลักคือ 100 USDT
    final_amount = float(base_price) + float(decimal)
    expire_at = datetime.now() + timedelta(hours=24) # ให้เวลาโอน 24 ชม.
    
    cursor.execute('''INSERT INTO pending_payments (user_id, base_amount, decimal_points, expire_at) 
                   VALUES (%s, %s, %s, %s) ON CONFLICT (user_id) 
                   DO UPDATE SET expire_at = EXCLUDED.expire_at''', (user_id, base_price, decimal, expire_at))
    conn.commit(); cursor.close(); conn.close()
    return final_amount

async def auto_verify_payment(context):
    """ตรวจสอบการชำระเงินอัตโนมัติจาก TronScan"""
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('SELECT user_id, (base_amount + decimal_points) FROM pending_payments WHERE expire_at > %s', (datetime.now(),))
        pending = cursor.fetchall()
        
        if not pending: return

        url = "https://apilist.tronscan.org/api/token_trc20/transfers"
        params = {"limit": 20, "direction": "in", "relatedAddress": MY_USDT_ADDR}
        data = requests.get(url, params=params).json().get('token_transfers', [])

        for uid, target_amt in pending:
            for tx in data:
                t_info = tx.get('tokenInfo', {})
                if t_info.get('symbol') == 'USDT':
                    actual_amt = float(tx.get('quant', 0)) / (10 ** int(t_info.get('decimals', 6)))
                    if abs(actual_amt - float(target_amt)) < 0.0001:
                        # อัปเดตวันหมดอายุ +30 วัน
                        cursor.execute('SELECT expire_date FROM customers WHERE user_id=%s', (uid,))
                        old = cursor.fetchone()
                        base = old[0] if old and old[0] > datetime.now() else datetime.now()
                        new_exp = base + timedelta(days=30)
                        
                        cursor.execute('''INSERT INTO customers (user_id, expire_date) VALUES (%s, %s) 
                                       ON CONFLICT (user_id) DO UPDATE SET expire_date=EXCLUDED.expire_date''', (uid, new_exp))
                        cursor.execute('DELETE FROM pending_payments WHERE user_id=%s', (uid,))
                        conn.commit()
                        await context.bot.send_message(chat_id=uid, text=f"✅ **ชำระเงินสำเร็จ!**\nอายุการใช้งานถึง: `{new_exp.strftime('%Y-%m-%d %H:%M')}`")
        cursor.close(); conn.close()
    except Exception as e:
        print(f"Verify Error: {e}")
