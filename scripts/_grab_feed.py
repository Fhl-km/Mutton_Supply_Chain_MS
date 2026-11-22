"""目视核对用截图：序号列插入、操作列两枚图标、就地编辑态、多功能菜单。

只用于开发期核对版式，不属于交付物。运行：
    .venv/Scripts/python.exe scripts/_grab_feed.py
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
TMP = Path(tempfile.mkdtemp(prefix="mscm_feed_"))
os.environ["MSCM_DATA_DIR"] = str(TMP / "data")
os.environ["QT_QPA_PLATFORM"] = "windows"

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from mscm.core import bootstrap  # noqa: E402
from mscm.core.db import open_database  # noqa: E402
from mscm.ui import icons, theme  # noqa: E402
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


def shot(widget, name):
    widget.grab().save(str(SHOTS / f"{name}.png"))


def go():
    win.show_page("feed")
    app.processEvents()
    page = win._page("feed")
    shot(win, "01_normal")

    # 序号格悬停：模拟鼠标移上去，看「＋」和 tooltip 的位置
    cell = page.table.cellWidget(1, 0)
    cell._hover = True
    cell.update()
    app.processEvents()
    shot(page.table, "02_seq_hover")

    # 就地编辑态（连右边操作列一起拍）
    page._begin_edit(1)
    app.processEvents()
    shot(page.card, "03_editing")
    page.cancel_edit()
    app.processEvents()

    # 灌 40 行，看竖滚时操作列图标是否跟着行走
    from mscm.core import repo as _repo
    batch_id = page._rows[0]["batch_id"] if page._rows else 0
    for k in range(40):
        _repo.save_row(conn, "feed", {
            "date": "2026-11-%02d" % (1 + k % 20), "batch_id": batch_id, "category": "育肥羊",
            "in_supplier": "滚动测试", "in_tag": "", "in_count": 1, "in_weight": 40.0,
            "in_price": 26.0, "out_use": "", "out_count": 0, "out_weight": 0, "remark": "",
        })
    page.refresh()
    app.processEvents()
    page.table.verticalScrollBar().setValue(page.table.verticalScrollBar().maximum())
    app.processEvents()
    shot(page.card, "06_scrolled")
    page.table.verticalScrollBar().setValue(0)
    app.processEvents()

    # 列头排序 / 筛选的指示
    page._sort_col, page._sort_desc = 1, True
    page.refresh()
    app.processEvents()
    shot(page.card, "08_sorted")
    page._col_filters = {2: {page._cell(page._rows[0], page.FIELDS[1])}}
    page._sort_col, page._sort_desc = None, False
    page.refresh()
    app.processEvents()
    shot(page.card, "09_filtered")
    page._col_filters.clear()
    page.refresh()
    app.processEvents()

    # 列少的台账（门店入库）：操作列同样在最右
    win.show_page("store-1-in")
    app.processEvents()
    shot(win, "07_store_in")

    # 多功能集菜单（照 _more_menu 的构成单独摆一个，便于截图）
    menu = QMenu(win)
    menu.addAction(icons.trash_icon(), "删除本行")
    menu.addSeparator()
    menu.addAction(icons.undo_icon(), "撤消")
    menu.addAction(icons.redo_icon(), "恢复")
    menu.show()
    app.processEvents()
    shot(menu, "04_more_menu")
    menu.close()

    # 图标放大看：编辑 / 多功能集 / 垃圾桶 / 撤消 / 恢复（24px 与 16px 各一遍）
    sheet = QPixmap(430, 150)
    sheet.fill(0xFFFFFF)
    p = QPainter(sheet)
    p.setRenderHint(QPainter.Antialiasing, True)
    items = [("保存", icons.save_icon()), ("撤消", icons.undo_icon()),
             ("恢复", icons.redo_icon()), ("多功能", icons.more_icon()),
             ("删除", icons.trash_icon()), ("编辑", icons.edit_icon())]
    x = 12
    for label, icon in items:
        icon.paint(p, 12 + (x - 12), 24, 32, 32)
        icon.paint(p, 12 + (x - 12) + 4, 72, 24, 24)
        icon.paint(p, 12 + (x - 12) + 8, 110, 16, 16)
        p.drawText(x - 2, 140, label)
        x += 68
    p.end()
    sheet.save(str(SHOTS / "05_icons.png"))

    app.quit()


QTimer.singleShot(600, go)
app.exec()
conn.close()
print("done", SHOTS)
