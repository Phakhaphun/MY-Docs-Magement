"""Create a reviewable report from saved baseline and improved OCR measurements."""
import argparse
import json
from pathlib import Path


def generate(folder):
    baseline=json.loads((folder/'baseline-corrected.json').read_text(encoding='utf-8'))
    improved=json.loads((folder/'improved.json').read_text(encoding='utf-8'))
    before={(item['condition'],item['profile']):item for item in baseline['results']}
    after={(item['condition'],item['profile']):item for item in improved['results']}
    text_unchanged=all([row['actual'] for row in item['rows']]==[row['actual'] for row in before[key]['rows']] for key,item in after.items())
    visuals=all(item['visual_identical'] for item in improved['results']+baseline['results'])
    if not text_unchanged or not visuals:raise ValueError('Text or page appearance changed. Review the results before reporting success.')
    def cer(item):
        return sum(row['errors'] for row in item['rows'])/sum(row['characters'] for row in item['rows'])*100
    lines=[
        '# ผลทดสอบ OCR: ฟอนต์ ขนาดตัวอักษร และทรัพยากร CPU',
        '', 'วันที่ทดสอบ: 2026-11-08 · branch `feature/searchable-pdf-ocr`', '',
        'ทดสอบบนเครื่องพัฒนา Windows x64 ด้วย PyMuPDF/Tesseract Fast, ภาษา English + Thai, OCR thread เดียว ไม่ใช้ GPU ผลนี้จำกัดเฉพาะชุดตัวอย่างสังเคราะห์นี้ ไม่ใช่การรับรองขนาดตัวอักษรขั้นต่ำหรือความแม่นยำของเอกสารจริงทุกประเภท', '',
        '## ไฟล์สำหรับลองด้วยตัวเอง', '',
        '- [ภาพสแกนชัด 300 DPI](samples-clean.pdf): 6 หน้า ไม่มีชั้นข้อความเดิม ใช้ทดสอบ OCR โดยตรง',
        '- [ภาพคุณภาพต่ำ](samples-low-quality.pdf): ขนาดตัวอักษรเท่าเดิม แต่ลดต้นฉบับเป็น 150 DPI, blur 0.35 px และ JPEG quality 45',
        '- [ต้นฉบับอ้างอิงที่มีข้อความ](reference-selectable.pdf): ใช้เทียบหน้าตาเท่านั้น แอปจะข้ามหน้าที่มีข้อความอยู่แล้ว',
        '- [ข้อความที่คาดหวังและพิกัดแต่ละแถว](ground-truth.json)',
        '- [ผลทุกแถว CSV](improved.csv) และ [ผลดิบ JSON](improved.json)', '',
        '## ขอบเขตและวิธีวัด', '',
        '- อังกฤษ: Tahoma, Arial, Times New Roman; ไทย: Tahoma, Angsana New, Cordia New',
        '- ขนาด 6, 8, 9, 10, 12, 14 และ 16 pt; 42 แถวต่อสภาพภาพ รวม 84 แถวต้นฉบับ และ 252 ผลวัดเมื่อทดสอบ 3 โปรไฟล์',
        '- ข้อความไทยสร้างด้วย MuPDF Story เพื่อจัดรูปสระ/วรรณยุกต์ ไม่ใช้ Pillow basic layout ที่เครื่องนี้ไม่มี RAQM',
        '- CER = จำนวนเพิ่ม/ลบ/แทนตัวอักษรขั้นต่ำ (Levenshtein) หารด้วยจำนวนตัวอักษรต้นฉบับ ยิ่งต่ำยิ่งดี',
        '- ตัด whitespace และทำ Unicode NFKC ก่อนเทียบ เพื่อไม่ลงโทษรูปแบบการเข้ารหัสสระอำที่เทียบเท่ากัน แต่ยังนับข้อผิดพลาดตัวพิมพ์ใหญ่/เล็ก เครื่องหมาย และตัวเลข',
        '- เวลาเป็น OCR engine ต่อไฟล์ 6 หน้า ไม่รวมการสร้างตัวอย่าง/เปิดหน้าจอ/เริ่ม Python process; เวลารายการละหนึ่งรอบ จึงไม่ตีความส่วนต่างเล็กน้อยว่าเร็วขึ้น',
        '- หน่วยความจำเป็น peak working set ของ process OCR บน Windows รวม Python/เอนจิน/เอกสาร วัดก่อนเรนเดอร์ตรวจผล', '',
        '## ก่อนและหลังคืนแคชภาพระหว่างหน้า', '',
        '| ภาพ | โปรไฟล์ | CER ก่อน/หลัง | เวลา ก่อน → หลัง (s) | Peak RAM ก่อน → หลัง (MB) | RAM ลดลง |',
        '|---|---|---:|---:|---:|---:|',
    ]
    for key,item in after.items():
        old=before[key];label='ชัด' if key[0]=='clean' else 'คุณภาพต่ำ'
        lines.append(f"| {label} | {key[1]} | {cer(old):.2f}% / {cer(item):.2f}% | {old['seconds']:.2f} → {item['seconds']:.2f} | {old['peak_mb']:.1f} → {item['peak_mb']:.1f} | {(1-item['peak_mb']/old['peak_mb'])*100:.1f}% |")
    lines += ['',
        f'ข้อความที่อ่านได้ตรงกันก่อน/หลังทุกแถว: **{text_unchanged}** · ภาพทุกหน้าตรงต้นฉบับแบบ pixel comparison ที่ 72 DPI: **{visuals}**', '',
        'การปรับปรุงที่นำเข้าแอปคือคืน decoded-image cache หลังจบแต่ละหน้า ลดการเก็บภาพที่หน้าอื่นไม่ต้องใช้ ความเร็วใกล้เดิมและความแม่นยำไม่เปลี่ยน ไม่ได้เพิ่มความแม่นยำจากการคืนแคช', '',
        'ทดลอง grayscale โดยตรงแล้วได้ข้อความว่างในชุดนี้ จึงปฏิเสธและคง RGB ตามเส้นทาง OCR เดิม ไม่มีการนำ candidate นี้เข้าแอป', '',
        '## ผลแยกฟอนต์/ขนาด: ภาพชัด, Detailed 300 DPI', '',
        'ค่าต่อช่องคือ CER (%) ไม่ใช่เปอร์เซ็นต์คำที่ถูก และค่า 0 หมายถึงตรงเฉพาะข้อความตัวอย่างนี้', '',
        '| ภาษา / ฟอนต์ | 6 pt | 8 pt | 9 pt | 10 pt | 12 pt | 14 pt | 16 pt |',
        '|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    detailed=after[('clean','detailed')]['rows']
    fonts=list(dict.fromkeys((row['language'],row['font']) for row in detailed))
    for language,font in fonts:
        values=[100*row['errors']/row['characters'] for row in detailed if (row['language'],row['font'])==(language,font)]
        lines.append('| '+language+' / '+font+' | '+' | '.join(f'{value:.1f}' for value in values)+' |')
    lines += ['', '## ข้อสรุปสำหรับการใช้งาน', '',
        '- ฟอนต์มีผลชัด เช่น Cordia New 6 pt ผิดพลาดมากในชุดนี้ ขณะที่ฟอนต์อื่นบางขนาดเล็กอ่านได้ครบ จึงไม่มีขั้นต่ำเดียวที่รับรองได้ทุกฟอนต์',
        '- ขนาดใหญ่กว่าไม่ได้แม่นกว่าทุกกรณี โมเดลที่เลือก ภาษา ระยะห่างและการแบ่งบรรทัดมีผลด้วย ชุดนี้เลือกสองภาษาทั้งหน้า รวมหน้าที่มีภาษาเดียว จึงอาจสับสนข้ามภาษา ควรเลือกเฉพาะภาษาที่มีจริง',
        '- ใช้ Detailed เมื่อข้อความเล็กและภาพต้นฉบับชัด แต่กรณีต้นฉบับคุณภาพต่ำ Balanced ได้ CER ดีกว่า Detailed ในชุดนี้ การเรนเดอร์เพิ่ม DPI ไม่กู้รายละเอียดที่หายไป',
        '- ควรตรวจชื่อ เลขเอกสาร วันที่ และจำนวนเงินเสมอ ผลนี้ไม่ครอบคลุมลายมือ ภาพถ่ายเอียง เงา เอกสารจริงทุก layout หรือทุกภาษา', '',
        '## ผลลัพธ์ PDF ที่ผ่าน OCR แล้ว', '',
    ]
    for key,item in after.items():lines.append(f"- [{key[0]} / {key[1]}]({item['pdf']})")
    lines += ['', '## ทำซ้ำ', '', 'ใช้ Python จาก `.venv` ในโปรเจกต์:', '', '```powershell',
        '.\\.venv\\Scripts\\python.exe tools\\benchmark_ocr_quality.py --generate --output output\\pdf\\ocr-test-kit-new --label baseline-corrected --variant retain-cache',
        '.\\.venv\\Scripts\\python.exe tools\\benchmark_ocr_quality.py --output output\\pdf\\ocr-test-kit-new --label improved',
        '.\\.venv\\Scripts\\python.exe tools\\report_ocr_quality.py output\\pdf\\ocr-test-kit-new', '```', '',
        '`retain-cache` ใช้ code ปัจจุบันโดยปิดการคืนแคชเพื่อจำลองพฤติกรรมก่อนแก้ เปลี่ยนเฉพาะการเก็บแคช ไม่ mock ผล OCR ต้องมี Windows fonts ตามรายการในสคริปต์ จึงไม่รับรองว่าจะสร้างชุดฟอนต์นี้บนระบบอื่นได้ทันที', '',
        'แนวทางการเลือกภาพและ DPI: [Tesseract ImproveQuality](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html)',
    ]
    (folder/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('Saved REPORT.md; all recognized rows unchanged and all page images verified')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder',type=Path)
    generate(parser.parse_args().folder.resolve())
