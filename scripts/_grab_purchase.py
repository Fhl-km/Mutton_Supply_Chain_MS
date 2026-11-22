"""目视核对：采购批次进导航、暂养入库取批次、批次编号按日期、填写说明。

只用于开发期核对，不属于交付物。
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
TMP = Path(tempfile.mkdtemp(prefix="mscm_buy_"))
os.environ["MSCM_DATA_DIR"] = str(TMP / "data")
os.environ["QT_QPA_PLATFORM"] = "windows"

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mscm.core import bootstrap  # noqa: E402
from mscm.core.db import open_database  # noqa: E402
from mscm.ui import theme  # noqa: E402
from mscm.ui.main_window import MainWindow  # noqa: E402

SHOTS = ROOT / "scripts" / "_shots_feed"
SHOTS.mkdir(exist_ok=True)

app = QApplication(sys.argv)
theme.apply_theme(app)
conn = open_database(TMP / "data" / "g.mscm.json")
bootstrap.ensure_seed_data(conn)
win = MainWindow(conn)
win.resize(1560, 940)
win.show()


def go():
    # 1) 暂养台账：入库行只读、出库行不摆入库数字
    win.show_page("feed")
    app.processEvents()
    page = win._page("feed")
    page.card.grab().save(str(SHOTS / "30_feed_inbound.png"))

    # 1b) 入库行正在编辑：日期与入库列灰底只读
    inbound_row = next((i for i, r in enumerate(page._rows) if r.get("row_kind") == "in"), None)
    if inbound_row is not None:
        page._begin_edit(inbound_row)
        app.processEvents()
        page.card.grab().save(str(SHOTS / "35_feed_inbound_edit.png"))
        page.cancel_edit()
        app.processEvents()

    # 2) 批次档案（导航在采购组下）
    win.show_page("batches")
    app.processEvents()
    win.grab().save(str(SHOTS / "31_batches.png"))
    win.sidebar.grab().save(str(SHOTS / "32_sidebar.png")) if hasattr(win, "sidebar") else None

    # 3) 序号插行：编号与金额随日期 / kg / 均价现算
    page = win._page("batches")
    if page._rows:
        page.table.cellWidget(0, 0).insertRequested.emit()
        app.processEvents()
        page.card.grab().save(str(SHOTS / "33_batch_draft.png"))
        page.cancel_edit()
        app.processEvents()

    app.quit()


QTimer.singleShot(700, go)
app.exec()
conn.close()
print("done", SHOTS)
