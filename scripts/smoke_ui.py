"""界面冒烟测试：无显示器环境下把所有页面搭起来、刷新一遍、截图。

用法：.venv/Scripts/python.exe scripts/smoke_ui.py
截图输出到 scripts/_shots/。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TMP = Path(tempfile.mkdtemp(prefix="mscm_ui_"))
os.environ["MSCM_DATA_DIR"] = str(TMP / "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mscm.core import bootstrap  # noqa: E402
from mscm.core.db import open_database  # noqa: E402
from mscm.ui import theme  # noqa: E402
from mscm.ui.main_window import MainWindow  # noqa: E402

SHOTS = ROOT / "scripts" / "_shots"
SHOTS.mkdir(parents=True, exist_ok=True)

app = QApplication(sys.argv)
theme.apply_theme(app)

conn = open_database(TMP / "data" / "ui.mscm.json")
print("[seed]", bootstrap.ensure_seed_data(conn).message)

win = MainWindow(conn)
win.resize(1600, 960)
win.show()
app.processEvents()

keys = ["dashboard", "check", "batches", "products", "stores", "customers",
        "feed", "breeding", "slaughter", "slaughter_out", "receivable", "payable",
        "store-1-pnl", "store-1-ledger", "store-1-in", "store-1-sale", "store-1-stock",
        "store-1-ar", "settings"]
for key in keys:
    win.show_page(key)
    app.processEvents()
    page = win.pages.get(key)
    print(f"[page] {key:16s} rows/ok  {type(page).__name__}")
    shot = SHOTS / f"{key}.png"
    win.grab().save(str(shot))

# 各页刷新两遍，暴露二次渲染的问题（行内控件残留、列宽抖动）
for key in keys:
    page = win.pages.get(key)
    if hasattr(page, "refresh"):
        page.refresh()
        page.refresh()
app.processEvents()
print("[ok] 全部页面刷新两轮无异常")
conn.close()
print("[tmp]", TMP)
