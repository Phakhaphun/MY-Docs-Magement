# Changelog

## 0.0.2 — 2026-11-06

- เพิ่มการยกเลิกการแปลง PDF ระหว่างทำงาน พร้อมผลสรุปแยกจากข้อผิดพลาด เก็บภาพที่บันทึกแล้ว และเริ่มแปลงใหม่ได้
- เพิ่มการลากวาง PDF หลายไฟล์บนหน้า PDF และแถบด้านซ้ายของหน้าต่างหลัก โดยไม่มีข้อความ remark หรือกล่องลากวาง ใช้ full path จาก native pywebview bridge ตาม [เอกสาร pywebview](https://pywebview.flowrl.com/examples/drag_drop)
- เพิ่ม dropdown เลือกหน้าส่งออกแยกตามไฟล์: All pages, Current page, Custom pages, Even pages และ Odd pages โดย Current page อ้างอิงหน้าที่แสดงในตัวอย่าง ช่องกรอกช่วงหน้าแสดงเฉพาะ Custom pages
- รองรับเลขหน้าและช่วง เช่น `1-3, 5` รวมหน้าซ้ำ คงเลขหน้าต้นฉบับในชื่อภาพ และเพิ่ม `--pages` ใน CLI
- เพิ่ม unit tests และ WebView2 smoke test สำหรับการลากวาง เลือกหน้า ยกเลิก และขนาดหน้าต่างที่รองรับ
- ปรับปุ่มยกเลิกเป็นสีแดง พร้อมสถานะระหว่างรอหยุดงาน
- จำขนาด ตำแหน่ง และสถานะเต็มจอของหน้าต่างหลักใน `workspace_settings.json` คืนขนาดก่อนขยายได้ และตรวจตำแหน่งเมื่อเปลี่ยนจอ
- ใช้ SVG สำหรับโลโก้และไอคอนเมนูหลัก สร้าง PNG 512×512 กับ ICO 9 ขนาดจาก SVG และปรับโลโก้หน้าจอโหลดตาม DPI
- แยกการเรนเดอร์และเข้ารหัสภาพ PDF ไป process เบื้องหลัง ลดการแย่งเวลาประมวลผลกับ Python bridge และลด priority บน Windows พร้อมส่ง progress/คำขอยกเลิกผ่าน IPC ตามแนวทาง [PyMuPDF multiprocessing](https://pymupdf.readthedocs.io/en/latest/recipes-multiprocessing.html)
- การวัด PDF vector ทดสอบ 3 หน้า 300 DPI บนเครื่องพัฒนา: ช่วงสะดุดสูงสุดของ Python heartbeat ลดจาก 783.7 ms เป็น 23.9 ms เวลาแปลง 3.25 → 3.45 วินาที เป็นผลจากไฟล์สังเคราะห์ ไม่ใช่การรับรองเวลาแปลงของทุกไฟล์

ผลตรวจบนเครื่องพัฒนา: Python 3.10 ใน `.venv`, unit tests ผ่าน 45 รายการ รวม renderer ผ่าน `pythonw.exe`, การยกเลิกและ cleanup process; `smoke_management.py`, `smoke_pdf_workflow.py` และ `smoke_window_settings.py` ผ่าน รวมถึงการเปิดหน้าต่างข้าม process เพื่อตรวจการคืนค่าขนาด/ตำแหน่ง/เต็มจอ, `pip check` ผ่าน และตัวเปิดโปรแกรมแสดง workspace พร้อมใช้งานได้ผ่าน `check_startup.py` ยังไม่ได้สร้าง Git tag หรือแพ็กเกจแจกจ่ายสำหรับรุ่นนี้

## 0.0.1

- รวม PDF to Image และ Temperature Heatmap ในหน้าต่าง Desktop เดียว
