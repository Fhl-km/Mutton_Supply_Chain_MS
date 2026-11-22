"""把对账单 xlsx 用 WPS 导出 PDF，再渲染成 PNG，方便目视检查打印版式。

用法：/c/Users/fhl13/.workbuddy/binaries/python/envs/default/Scripts/python.exe scripts/_grab_statement_pdf.py 对账单-xxx.xlsx
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import win32com.client as win32

ROOT = Path(__file__).resolve().parents[1]
arg = sys.argv[1] if len(sys.argv) > 1 else "对账单-马老三-2026-11-20.xlsx"
xlsx = ROOT / "导出报表" / arg if not Path(arg).is_absolute() else Path(arg)
pdf = ROOT / "scripts" / "_shots" / (xlsx.stem + ".pdf")
pdf.parent.mkdir(parents=True, exist_ok=True)

app = win32.DispatchEx("Ket.Application")
app.Visible = False
app.DisplayAlerts = False
wb = app.Workbooks.Open(str(xlsx))
try:
    wb.ExportAsFixedFormat(0, str(pdf))
finally:
    wb.Close(False)
    app.Quit()

doc = fitz.open(str(pdf))
print("[pdf]", pdf.name, doc.page_count, "页")
for i, page in enumerate(doc):
    pix = page.get_pixmap(dpi=170)
    png = pdf.with_name(f"{pdf.stem}_p{i + 1}.png")
    pix.save(str(png))
    print("[png]", png.name, pix.width, "x", pix.height)
doc.close()
