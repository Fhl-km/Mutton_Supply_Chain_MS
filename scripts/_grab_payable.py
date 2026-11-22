"""应付款项页面截图 + 采购对账单样例（用于目视核对版式）。

用法：.venv/Scripts/python.exe scripts/_grab_payable.py
出：scripts/_shots/payable-*.png、导出报表/采购对账单-会泽五星牧场-2026-11-20.xlsx
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TMP = Path(tempfile.mkdtemp(prefix="mscm_ap_shot_"))
os.environ["MSCM_DATA_DIR"] = str(TMP / "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mscm import config  # noqa: E402
from mscm.core import bootstrap  # noqa: E402
from mscm.core.db import open_database  # noqa: E402
from mscm.core.services import export as xl_export  # noqa: E402
from mscm.ui import theme  # noqa: E402
from mscm.ui.main_window import MainWindow  # noqa: E402

SHOTS = ROOT / "scripts" / "_shots"
SHOTS.mkdir(parents=True, exist_ok=True)

app = QApplication(sys.argv)
theme.apply_theme(app)
conn = open_database(TMP / "data" / "ap_shot.mscm.json")
bootstrap.ensure_seed_data(conn)

win = MainWindow(conn)
win.resize(1600, 940)
win.show()
app.processEvents()

page = win._page("payable")
win.show_page("payable")
app.processEvents()
win.grab().save(str(SHOTS / "payable-1-应付.png"))

page.tabs.setCurrentIndex(1)
app.processEvents()
win.grab().save(str(SHOTS / "payable-2-未付.png"))

page.tabs.setCurrentIndex(0)
win.toggle_help(True) if hasattr(win, "toggle_help") else page.toggle_help(True)
app.processEvents()
win.grab().save(str(SHOTS / "payable-3-说明.png"))

config.ensure_dirs()
path = Path(config.EXPORT_DIR) / "采购对账单-会泽五星牧场-2026-11-20.xlsx"
xl_export.export_ap_statement(path, conn, "会泽五星牧场", "王老板", "139****2208",
                              "2026-11-20", "李伟", "134****2238")
print("[ok]", path, path.stat().st_size, "bytes")
conn.close()
print("[tmp]", TMP)
