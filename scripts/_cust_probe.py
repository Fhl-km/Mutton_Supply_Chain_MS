"""客户名录临时核查：落库 / 排序 / 应收下拉 / 删除保护 / 出表版式。

用法：.venv/Scripts/python.exe scripts/_cust_probe.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TMP = Path(tempfile.mkdtemp(prefix="mscm_cust_"))
os.environ["MSCM_DATA_DIR"] = str(TMP / "data")

import openpyxl  # noqa: E402

from mscm.core import bootstrap, repo  # noqa: E402
from mscm.core.db import open_database  # noqa: E402
from mscm.core.services import export  # noqa: E402

conn = open_database(TMP / "data" / "cust.mscm.json")
bootstrap.ensure_seed_data(conn)

a = repo.save_customer(conn, {
    "org": "门店", "name": "李记羊肉馆", "credit_code": "91530100MA6K000000",
    "contact": "李老板", "phone": "13700009012", "address": "昆明市五华区人民中路 120 号",
    "settle": "月结", "first_date": "2026-11-01", "owner": "王芳", "remark": "老客户", "is_active": True,
})
b = repo.save_customer(conn, {
    "org": "屠宰场", "name": "昭通小串烧烤", "credit_code": "身份证 5321**********1234",
    "contact": "马老三", "phone": "13800006621", "address": "昭通市昭阳区龙泉路 8 号",
    "settle": "现结", "first_date": "", "owner": "李伟", "remark": "", "is_active": True,
})
c = repo.save_customer(conn, {
    "org": "屠宰场", "name": "试删客户", "settle": "", "first_date": "", "is_active": True,
})

print("[rows]", [(x["org"], x["name"]) for x in repo.list_customers(conn)])
names = [x["name"] for x in repo.list_customers(conn)]
orgs = [x["org"] for x in repo.list_customers(conn)]
assert orgs.index("屠宰场") < orgs.index("门店"), "屠宰场应排前面"
assert "昭通小串烧烤" in names, "新存的客户应在名录里"

print("[ar slaughter]", repo.ar_customers(conn, "slaughter")[:5])
print("[ar store]", repo.ar_customers(conn, "store")[:5])
assert "昭通小串烧烤" in repo.ar_customers(conn, "slaughter")
assert "李记羊肉馆" in repo.ar_customers(conn, "store")

# 已被挂账的客户不能删
conn.insert("ar_invoice", {"biz": "store", "store_id": 1, "date": "2026-11-20",
                           "customer": "李记羊肉馆", "amount": 100.0})
conn.commit()
ok, msg = repo.delete_customer(conn, int(a["id"]))
print("[del used]", ok, msg)
assert not ok
ok2, _ = repo.delete_customer(conn, int(c["id"]))
print("[del free]", ok2)
assert ok2

out = export.export_customers(TMP / "客户名录-核查.xlsx", repo.list_customers(conn))
print("[export]", out.name, out.stat().st_size, "bytes")

wb = openpyxl.load_workbook(out)
ws = wb.active
print("[sheet]", ws.title, ws.max_row, ws.max_column, "merged", ws.merged_cells.ranges,
      "freeze", ws.freeze_panes)
print("[head]", [ws.cell(row=2, column=i).value for i in range(1, 12)])
print("[row3]", [ws.cell(row=3, column=i).value for i in range(1, 12)])
print("[row4]", [ws.cell(row=4, column=i).value for i in range(1, 12)])
print("[widths]", {k: v.width for k, v in ws.column_dimensions.items()})
print("[dv]", [(d.type, d.formula1, str(d.sqref)) for d in ws.data_validations.dataValidation])
print("[fonts]", ws["A1"].font.name, ws["A1"].font.sz, ws["A1"].font.b,
      ws["A2"].font.sz, ws["C3"].font.sz)
print("[align]", ws["C3"].alignment.horizontal, ws["A3"].alignment.horizontal,
      ws["H3"].alignment.horizontal)
print("[rowh]", ws.row_dimensions[1].height, ws.row_dimensions[2].height,
      ws.row_dimensions[3].height)
print("[page]", ws.page_setup.orientation, ws.page_setup.paperSize, ws.print_title_rows,
      ws.sheet_view.zoomScale)

conn.close()
print("OK", TMP)
