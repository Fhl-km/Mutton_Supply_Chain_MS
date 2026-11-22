"""目视核对：活羊入库&结余 页（导航标签 / 列顺序 / 序号插入 / 操作列）。

只用于开发期核对，不属于交付物。
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
TMP = Path(tempfile.mkdtemp(prefix="mscm_batch_"))
os.environ["MSCM_DATA_DIR"] = str(TMP / "data")
os.environ["QT_QPA_PLATFORM"] = "windows"

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mscm.core import bootstrap  # noqa: E402
from mscm.core.db import open_database  # noqa: E402
from mscm.ui import theme  # noqa: E402
from mscm.ui.main_window import MainWindow  # noqa: E402

TAG = sys.argv[1] if len(sys.argv) > 1 else "shot"
SHOTS = ROOT / "scripts" / "_shots_batches"
SHOTS.mkdir(exist_ok=True)

app = QApplication(sys.argv)
theme.apply_theme(app)
conn = open_database(TMP / "data" / "g.mscm.json")
bootstrap.ensure_seed_data(conn)
win = MainWindow(conn)
win.resize(1560, 940)
win.show()


def go():
    win.show_page("batches")
    app.processEvents()
    win.grab().save(str(SHOTS / f"{TAG}_window.png"))

    page = win._page("batches")
    page.card.grab().save(str(SHOTS / f"{TAG}_card.png"))

    # 序号悬停 + 插入行
    if page._rows:
        page.on_insert_at(0)
        app.processEvents()
        page.card.grab().save(str(SHOTS / f"{TAG}_draft.png"))
        page.cancel_edit()
        app.processEvents()

    # 双击第一行就地编辑
    if page._rows:
        page._begin_edit(0)
        app.processEvents()
        page.card.grab().save(str(SHOTS / f"{TAG}_edit.png"))
        page.cancel_edit()
        app.processEvents()

    # 横向滚到最右：状态 / 备注与冻结的操作列对不对得上
    page.table.horizontalScrollBar().setValue(page.table.horizontalScrollBar().maximum())
    app.processEvents()
    page.card.grab().save(str(SHOTS / f"{TAG}_scrolled.png"))

    # 填写说明：HTML 里的 & 要对
    page.toggle_help(True)
    app.processEvents()
    win.grab().save(str(SHOTS / f"{TAG}_help.png"))

    print("列：", [c.title for c in page.table.columns] if hasattr(page.table, "columns") else "—")
    print("行数：", len(page._rows))
    app.quit()


QTimer.singleShot(800, go)
app.exec()
conn.close()
print("done", SHOTS)
