"""验收截图 + 对账单样例：用真实账套的**副本**跑（不动 data/mscm.mscm.json）。

用法：QT_QPA_FONTDIR=C:/Windows/Fonts .venv/Scripts/python.exe scripts/_grab_open.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TMP = Path(tempfile.mkdtemp(prefix="mscm_open_"))
os.environ["MSCM_DATA_DIR"] = str(TMP / "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mscm import config  # noqa: E402
from mscm.core import bootstrap, calc  # noqa: E402
from mscm.core.db import open_database  # noqa: E402
from mscm.core.services import export as xl_export  # noqa: E402
from mscm.ui import theme  # noqa: E402
from mscm.ui.main_window import MainWindow  # noqa: E402

SHOTS = ROOT / "scripts" / "_shots"
SHOTS.mkdir(parents=True, exist_ok=True)

app = QApplication(sys.argv)
theme.apply_theme(app)
app.setFont(QFont("SimHei", 9))

# 拿真实账套的副本跑，原文件一个字节都不动
src = ROOT / "data" / "mscm.mscm.json"
copy = TMP / "data" / "real_copy.mscm.json"
copy.parent.mkdir(parents=True, exist_ok=True)
if src.exists():
    shutil.copy2(src, copy)
conn = open_database(copy)
bootstrap.ensure_seed_data(conn)

win = MainWindow(conn)
win.resize(1600, 960)
win.show()
win.show_page("receivable")
app.processEvents()

page = win.pages["receivable"]
page.tabs.setCurrentIndex(1)
app.processEvents()
win.grab().save(str(SHOTS / "ar-open.png"))
print("[shot] ar-open.png")
print("[sums]", page.tab_open.sums.right.text())
for r in page.tab_open._rows:
    print("   ", r.get("sale_batch"), r.get("customer"), r.get("_amount"),
          r.get("_received"), r.get("_waiver"), r.get("_unpaid"), r.get("salesman"))

# 对账单弹窗长什么样：把 FormDialog 换成「建出来、拍一张、返回取消」
import mscm.ui.pages.receivable as rp  # noqa: E402

_real_form = rp.FormDialog


class _Stop:
    def exec(self):
        return 0


def _spy(*args, **kwargs):
    dlg = _real_form(*args, **kwargs)
    dlg.show()
    app.processEvents()
    dlg.grab().save(str(SHOTS / "statement-dialog.png"))
    print("[shot] statement-dialog.png", dlg.size())
    dlg.close()
    return _Stop()


rp.FormDialog = _spy
page.tab_open.on_statement()
rp.FormDialog = _real_form

# 用第一户有未收的客户出一张对账单样例（落在项目 导出报表/，可以直接打开看版式）
names = [str(r.get("customer") or "") for r in page.tab_open._rows if r.get("customer")]
if names:
    cust = names[0]
    out = Path(config.EXPORT_DIR) / f"对账单-{cust}-{page.ctx.biz_date}.xlsx"
    xl_export.export_statement(out, conn, "slaughter", 0, cust,
                               "马老三", "138****6621", page.ctx.biz_date,
                               "李伟", "134****2238")
    print("[statement]", out)

conn.close()
print("[tmp]", TMP)
