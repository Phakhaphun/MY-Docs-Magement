# Docspace · Main Management

Version **0.0.1** (Git tag: `0.0.1`)

รวมโปรแกรมจาก Doc_management และ Heat-Map เป็นแอป Desktop หน้าต่างเดียว
ใช้เมนูด้านซ้ายสลับเครื่องมือ โดยรายการ PDF และค่าที่กรอกใน Heatmap ยังคงอยู่เมื่อสลับหน้า
เปิดหน้า PDF ก่อน และโหลดการคำนวณ Heatmap เมื่อเลือกเมนู Heatmap ครั้งแรก เพื่อลดเวลารอเข้าโปรแกรม

- **PDF to Image**: เพิ่ม PDF หลายไฟล์ ดูตัวอย่างแต่ละหน้า ซูม และส่งออก JPG, PNG หรือ WebP
- **Heatmap**: กรอกอุณหภูมิ 6 จุด ปรับพื้นที่ ตำแหน่ง ชื่อจุด ช่วงสี และขนาดภาพ ดูตัวอย่างและส่งออก PNG
- ทำงานภายในเครื่อง ไม่ต้องใช้เว็บเซิร์ฟเวอร์
- คัดลอกซอร์สที่จำเป็นมาไว้ในโฟลเดอร์นี้แล้ว สามารถใช้งานโดยไม่อ้างอิงสองโฟลเดอร์ต้นฉบับ
- ไฟล์งานและผลลัพธ์เดิมในสองโฟลเดอร์ต้นฉบับยังอยู่ที่เดิม เลือกเปิดหรือเลือกปลายทางจากหน้าจอได้

## เปิดใช้งานบน Windows

ดับเบิลคลิก `start_ui.vbs` หรือ `start_ui.bat`
ตัวเปิดโปรแกรมใช้ `.venv` ในโฟลเดอร์นี้ มีหน้าจอโหลดและบันทึกข้อผิดพลาดที่ `.webview/startup.log`

ติดตั้งใหม่เมื่อย้ายเครื่อง (Python 3.10+ และ Microsoft Edge WebView2 Runtime):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

เปิดผ่านคำสั่ง:

```powershell
.\.venv\Scripts\python.exe main_app.py
```

## การเก็บข้อมูล

- การตั้งค่า PDF: `ui_settings.json`
- การตั้งค่า Heatmap: `heatmap_settings.json`
- ค่าเริ่มต้น Heatmap: `config.json`
- ผลลัพธ์เริ่มต้น: `output/` หรือโฟลเดอร์ที่เลือกในแต่ละเครื่องมือ

เริ่มด้วยการตั้งค่าเริ่มต้น เพื่อไม่ให้เขียนผลลัพธ์ลงโฟลเดอร์ต้นฉบับโดยไม่ตั้งใจ
Heatmap จะเติมเลขท้ายชื่อเมื่อไฟล์ส่งออกมีอยู่แล้ว
ระหว่างแปลง PDF หรือสร้าง Heatmap โปรแกรมจะรอให้งานเสร็จก่อนยอมปิดหน้าต่าง

## โครงสร้างและการทดสอบ

`main_app.py` เป็นตัวรวมหน้าต่างและส่งคำสั่งไปยัง `DocumentAPI` และ `HeatmapAPI`
`ui/management.html` เป็นเมนูหลัก หน้าของแต่ละเครื่องมือแยกบริบท HTML/CSS/JS และใช้ Python bridge ร่วมกัน
`heatmap/` เป็นแกนคำนวณเดิม และ `pdf_to_jpg.py` เป็นแกนแปลง PDF เดิม
เวอร์ชันโปรแกรมระบุในไฟล์ `VERSION`

เครื่องมือตามคำสั่งยังใช้ได้ผ่าน `pdf_to_jpg.py` และ `heatmap_cli.py --config config.json`

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
.\.venv\Scripts\python.exe tools\smoke_management.py
```

Smoke test เปิดหน้าต่างชั่วคราว ตรวจทั้งสองเครื่องมือ การสลับหน้า และการส่งออกจริง แล้วปิดเอง
