"""客户名录页面级核查：新增 / 编辑 / 删除 / 筛选 / 导出（不用点弹窗，直接走页面接口）。

用法：.venv/Scripts/python.exe scripts/_cust_page_probe.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TMP = Path(tempfile.mkdtemp(prefix="mscm_cust_page_"))
os.environ["MSCM_DATA_DIR"] = str(TMP / "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import openpyxl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mscm import config  # noqa: E402
from mscm.core import bootstrap  # noqa: E402
from mscm.core.db import open_database  # noqa: E402
from mscm.ui import theme  # noqa: E402
from mscm.ui.dialogs import FormDialog  # noqa: E402
from mscm.ui.main_window import MainWindow  # noqa: E402

config.EXPORT_DIR = TMP / "导出报表"          # 别往项目目录里写测试文件
app = QApplication(sys.argv)
theme.apply_theme(app)

conn = open_database(TMP / "data" / "page.mscm.json")
bootstrap.ensure_seed_data(conn)
win = MainWindow(conn)
win.resize(1600, 900)
win.show()
win.show_page("customers")
app.processEvents()
page = win.pages["customers"]

print("[empty]", page.table.rowCount(), page.sums.left.text())

page.save({"org": "屠宰场", "name": "昭通小串烧烤", "credit_code": "91530600MA6K7X8L2A",
           "contact": "马老三", "phone": "13800006621", "address": "昭通市昭阳区龙泉路 8 号",
           "settle": "现结", "first_date": "2026-08-15", "owner": "李伟", "remark": ""}, None)
page.save({"org": "门店", "name": "李记羊肉馆", "credit_code": "", "contact": "李老板",
           "phone": "13700009012", "address": "昆明市五华区人民中路 120 号",
           "settle": "（未填）", "first_date": "", "owner": "王芳", "remark": "老客户"}, None)
page.save({"org": "门店", "name": "关街农贸市场 12 号摊", "settle": "（未填）"}, None)
page.refresh()
app.processEvents()
print("[rows]", page.table.rowCount())
print("[row0]", [page.table.item(0, c).text() for c in range(11)])
print("[seq]", [page.table.item(i, 0).text() for i in range(3)])
print("[sums]", page.sums.left.text())
print("[settle blank]", conn.rows("customer")[1]["settle"] == "")

# 按归属筛
page.f_org.setCurrentText("门店")
app.processEvents()
print("[filter 门店]", page.table.rowCount(), page.sums.left.text())
page.f_org.setCurrentText("全部归属")
app.processEvents()

# 搜索
page.f_kw.setText("马老三")
app.processEvents()
print("[search]", page.table.rowCount())
page.f_kw.clear()
app.processEvents()

# 编辑一个（保留 id）
rec = conn.rows("customer")[0]
page.save({"org": "屠宰场", "name": "昭通小串烧烤（新店）", "credit_code": "91530600MA6K7X8L2A",
           "contact": "马老三", "phone": "13800006621", "address": "昭通市昭阳区龙泉路 8 号",
           "settle": "月结", "first_date": "2026-08-15", "owner": "李伟", "remark": ""},
          int(rec["id"]))
page.refresh()
print("[edited]", page.table.item(0, 2).text(), page.table.item(0, 7).text())
print("[count stays]", len(conn.rows("customer")))

# 删除未挂账的
page.delete(int(conn.rows("customer")[2]["id"]))
page.refresh()
print("[after del]", len(conn.rows("customer")))

# 导出（走页面按钮那段逻辑；弹窗在无头环境里会卡住，先摘掉）
import mscm.ui.pages.customers as cust_mod  # noqa: E402

cust_mod.info = lambda *a, **k: None
page.on_export()
files = list((TMP / "导出报表").glob("客户名录*.xlsx"))
print("[export files]", [f.name for f in files])
ws = openpyxl.load_workbook(files[0]).active
print("[export rows]", ws.max_row, [ws.cell(row=3, column=i).value for i in range(1, 12)])

# date_opt 空值
dlg = FormDialog("t", page.FIELDS, values=page.blank(), parent=win, hint=page.DIALOG_HINT)
print("[dialog size]", dlg.width(), dlg.height(), "min", dlg.minimumWidth())
print("[date_opt empty]", repr(dlg.value("first_date")), "settle", repr(dlg.value("settle")))
dlg.show()
app.processEvents()
print("[shown size]", dlg.width(), dlg.height())

conn.close()
print("OK", TMP)
