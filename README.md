# Stock Checker -> Telegram

บอทเช็ค stock สินค้าจาก store.google.com แล้วแจ้งเตือนผ่าน Telegram อัตโนมัติ
รันฟรีบน GitHub Actions (cron) ไม่ต้องมีเซิร์ฟเวอร์ของตัวเอง

## วิธีตั้งค่า (ทำครั้งเดียว)

### 1. สร้าง Telegram Bot
1. เปิดแชทกับ [@BotFather](https://t.me/BotFather) ใน Telegram
2. พิมพ์ `/newbot` แล้วทำตามขั้นตอน จะได้ **Bot Token** มา (หน้าตาแบบ `123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`)
3. เริ่มแชทกับบอทของตัวเอง (กด Start) อย่างน้อย 1 ครั้ง เพื่อให้บอทส่งข้อความหาเราได้

### 2. หา Chat ID ของตัวเอง
1. ส่งข้อความอะไรก็ได้ให้บอทที่สร้างไว้
2. เปิดลิงก์นี้ในเบราว์เซอร์ (ใส่ token ของตัวเอง):
   `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
3. หาเลข `"chat":{"id": ...}` นั่นคือ **Chat ID**

### 3. สร้าง GitHub repo แล้วอัปโหลดไฟล์ชุดนี้
โครงสร้างไฟล์:
```
stock-checker/
├── .github/workflows/check-stock.yml
├── check_stock.py
├── requirements.txt
└── README.md
```

### 4. ใส่ Secrets ใน GitHub repo
ไปที่ repo -> Settings -> Secrets and variables -> Actions -> New repository secret
เพิ่ม 2 ตัว:
- `TELEGRAM_BOT_TOKEN` = token จากขั้นตอนที่ 1
- `TELEGRAM_CHAT_ID` = chat id จากขั้นตอนที่ 2

### 5. เปิดใช้งาน
- ไปที่แท็บ **Actions** ของ repo แล้วกด "I understand my workflows, go ahead and enable them" (ถ้าเป็น repo ใหม่)
- ลองรันด้วยมือก่อน: Actions -> Check Stock -> Run workflow เพื่อทดสอบว่าทำงานถูกต้อง
- จากนั้นมันจะรันอัตโนมัติทุก 10 นาทีตาม cron ที่ตั้งไว้

## ปรับแต่ง

- **เปลี่ยนสินค้าที่เช็ค**: แก้ตัวแปร `PRODUCT_URL` ใน `check_stock.py` (หรือส่งผ่าน secret `PRODUCT_URL` แล้วเปิดคอมเมนต์บรรทัดที่เกี่ยวข้องใน workflow)
- **เปลี่ยนความถี่**: แก้ `cron: "*/10 * * * *"` ใน workflow (syntax แบบ cron ปกติ) — อย่าตั้งถี่เกินไป (ต่ำกว่า 5 นาที) เพราะ GitHub Actions มี rate limit และการรัน Playwright ทุกครั้งใช้เวลา ~20-30 วินาที
- **เพิ่มสินค้าหลายชิ้น**: ทำ list ของ URL ใน `check_stock.py` แล้ว loop เช็คทีละอัน พร้อมเก็บ state แยกไฟล์ต่อสินค้า (บอกมาได้ถ้าต้องการให้ช่วยขยายส่วนนี้)

## ข้อควรรู้

- หน้าเว็บ Google Store เป็น JS-heavy app เลยต้องใช้ Playwright (headless browser) แทนการ fetch HTML ตรงๆ ทำให้แต่ละรอบใช้เวลาและทรัพยากรมากกว่าการเช็ค API ปกติเล็กน้อย — ปกติแล้ว GitHub Actions free tier (2,000 นาที/เดือนสำหรับ private repo, ไม่จำกัดสำหรับ public repo) เพียงพอสำหรับรันทุก 10 นาที
- สคริปต์เช็คจากข้อความบนปุ่ม (เช่น "Buy" vs "Notify me" / "Sold out") ถ้า Google เปลี่ยน UI/wording อาจต้องปรับ selector หรือ keyword ใน `OUT_OF_STOCK_PHRASES` / `IN_STOCK_PHRASES`
- แจ้งเตือนจะส่งเฉพาะตอน "สถานะเปลี่ยน" เท่านั้น (จากหมด -> มี หรือ มี -> หมด) ไม่ใช่ทุกรอบที่รัน เพื่อไม่ให้สแปม
