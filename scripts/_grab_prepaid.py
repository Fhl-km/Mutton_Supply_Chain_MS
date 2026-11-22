"""只为验收截图：造一笔「收多了」的预收，看未收金额是不是负的、绿字。

用法：QT_QPA_FONTDIR=C:/Windows/Fonts .venv/Scripts/python.exe scripts/_grab_prepaid.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TMP = Path(tempfile.mkdtemp(prefix="mscm_prepaid_"))
os.environ["MSCM_DATA_DIR"] = str(TMP / "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mscm.core import bootstrap  # noqa: E402
from mscm.core.db import open_database  # noqa: E402
from mscm.ui import theme  # noqa: E402
from mscm.ui.main_window import MainWindow  # noqa: E402

SHOTS = ROOT / "scripts" / "_shots"
SHOTS.mkdir(parents=True, exist_ok=True)

app = QApplication(sys.argv)
theme.apply_theme(app)
app.setFont(QFont("SimHei", 9))

conn = open_database(TMP / "data" / "shot.mscm.json")
bootstrap.ensure_seed_data(conn)

# 给第一张应收单多收一笔：应收 6,232、已收 1,000，再收 6,000 → 未收 −768（预收）
inv = next(r for r in conn.rows("ar_invoice") if r.get("biz") == "slaughter")
conn.insert("ar_receipt", {
    "biz": "slaughter", "store_id": 0, "invoice_id": int(inv["id"]),
    "date": "2026-11-20", "customer": str(inv.get("customer") or ""),
    "amount": 6000.0, "waiver": 20.0, "pay_method": "银行转账", "ref": "",
    "remark": "客户预付下一批货款，抹零 20",
})
conn.commit()

win = MainWindow(conn)
win.resize(1600, 960)
win.show()
win.show_page("receivable")
app.processEvents()

page = win.pages["receivable"]
win.grab().save(str(SHOTS / "ar-prepaid.png"))
print("[shot] ar-prepaid.png")
print("[sums]", page.tab_inv.sums.right.text())
conn.close()
print("[tmp]", TMP)
