"""客户名录页面截图（无显示器）：列表 + 新增弹窗 + 填写说明。

用法：.venv/Scripts/python.exe scripts/_shot_customers.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TMP = Path(tempfile.mkdtemp(prefix="mscm_cust_shot_"))
os.environ["MSCM_DATA_DIR"] = str(TMP / "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mscm.core import bootstrap, repo  # noqa: E402
from mscm.core.db import open_database  # noqa: E402
from mscm.ui import theme  # noqa: E402
from mscm.ui.dialogs import FormDialog  # noqa: E402
from mscm.ui.main_window import MainWindow  # noqa: E402

SHOTS = ROOT / "scripts" / "_shots_customers"
SHOTS.mkdir(parents=True, exist_ok=True)

app = QApplication(sys.argv)
theme.apply_theme(app)

conn = open_database(TMP / "data" / "shot.mscm.json")
bootstrap.ensure_seed_data(conn)
for row in (
    {"org": "屠宰场", "name": "昭通小串烧烤", "credit_code": "91530600MA6K7X8L2A",
     "contact": "马老三", "phone": "13800006621", "address": "昭通市昭阳区龙泉路 8 号",
     "settle": "现结", "first_date": "2026-08-15", "owner": "李伟", "remark": "每周五要货"},
    {"org": "屠宰场", "name": "鲁甸回民食堂", "credit_code": "91530621MA6N000001",
     "contact": "马经理", "phone": "13908701234", "address": "鲁甸县文屏镇世纪大道 66 号",
     "settle": "半月结", "first_date": "2026-09-02", "owner": "李伟", "remark": ""},
    {"org": "门店", "name": "李记羊肉馆", "credit_code": "92530102MA6P1234X7",
     "contact": "李老板", "phone": "13700009012", "address": "昆明市五华区人民中路 120 号",
     "settle": "月结", "first_date": "2026-11-01", "owner": "王芳", "remark": "老客户，月结 30 天"},
    {"org": "门店", "name": "关街农贸市场 12 号摊", "credit_code": "",
     "contact": "张姐", "phone": "13600001234", "address": "富民县关街农贸市场 12 号摊",
     "settle": "", "first_date": "", "owner": "王芳", "remark": "散客，现款为主"},
):
    repo.save_customer(conn, row)

win = MainWindow(conn)
win.resize(1600, 900)
win.show()
win.show_page("customers")
app.processEvents()
win.grab().save(str(SHOTS / "customers.png"))

page = win.pages["customers"]
page.toggle_help(True)
app.processEvents()
win.grab().save(str(SHOTS / "customers_help.png"))
page.toggle_help(False)

dlg = FormDialog("新增客户 · 客户名录", page.FIELDS, values=page.blank(), parent=win,
                 hint=page.DIALOG_HINT)
dlg.show()
app.processEvents()
dlg.grab().save(str(SHOTS / "customers_dialog.png"))
print("[ok]", SHOTS)
conn.close()
