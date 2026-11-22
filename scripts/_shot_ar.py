"""只为验收截图：offscreen 下换用 SimHei 让中文能显示（不影响产品代码）。

用法：QT_QPA_FONTDIR=C:/Windows/Fonts .venv/Scripts/python.exe scripts/_shot_ar.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TMP = Path(tempfile.mkdtemp(prefix="mscm_shot_"))
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
win = MainWindow(conn)
win.resize(1600, 960)
win.show()
app.processEvents()

for key, tabs in (("receivable", (0, 1)), ("store-1-ar", (0,)), ("slaughter_out", ())):
    win.show_page(key)
    page = win.pages[key]
    if key == "slaughter_out":
        app.processEvents()
        win.grab().save(str(SHOTS / "sout.png"))
        print("[shot] sout.png")
        continue
    for idx in tabs:
        page.tabs.setCurrentIndex(idx)
        app.processEvents()
        name = f"ar-{key}-{idx}.png"
        win.grab().save(str(SHOTS / name))
        print("[shot]", name)

conn.close()
print("[tmp]", TMP)
