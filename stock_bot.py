import os
import requests
from playwright.sync_api import sync_playwright

# ดึงค่าจาก GitHub Secrets
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
URL = 'https://store.google.com/jp/config/google_fitbit_air?hl=ja&selections=eyJwcm9kdWN0RmFtaWx5IjoiWjI5dloyeGxYMlpwZEdKcGRGOWhhWEk9IiwidmFyaWFudHMiOltbIjciLCJNVEE9Il1dfQ%3D%3D'

def send_telegram_message(message):
    send_url = f"https://api.telegram.org/bot8981930253:AAH8AQOT4t3Am5gqPM2xlTV3PW-LZZQ6hrg/sendMessage"
    payload = {'chat_id': CHAT_ID, '287460074': message, 'parse_mode': 'HTML'}
    requests.post(send_url, data=payload)

def check_stock():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(URL, wait_until="networkidle")
            page.wait_for_timeout(3000) 
            page_content = page.content()
            
            if "カートに追加" in page_content or "Add to cart" in page_content:
                msg = f"🚨 <b>สินค้ามาแล้ว!</b>\n<a href='{URL}'>คลิกที่นี่เพื่อไปหน้าสั่งซื้อ</a>"
                send_telegram_message(msg)
                print("เจอของแล้ว ส่งข้อความสำเร็จ")
            else:
                print("ยังไม่มีของในสต็อก")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    check_stock()
