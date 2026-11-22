"""冒烟：活羊入库&结余（行内录入版）—— 列顺序 / 序号插行 / 现算金额 / 落库 / 删除拦截 / 导出。

用法：.venv/Scripts/python.exe scripts/smoke_batches.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TMP = Path(tempfile.mkdtemp(prefix="mscm_batch_"))
os.environ["MSCM_DATA_DIR"] = str(TMP / "data")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QDate  # noqa: E402
from PySide6.QtWidgets import QComboBox, QLineEdit, QPushButton  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mscm.core import bootstrap, repo  # noqa: E402
from mscm.core.db import open_database  # noqa: E402
from mscm.core.services import export as xl_export  # noqa: E402
from mscm.ui import theme  # noqa: E402
from mscm.ui.main_window import MainWindow  # noqa: E402
from mscm.ui.pages import base_ledger as bl  # noqa: E402
from mscm.ui.pages.batches import BatchInUse  # noqa: E402

app = QApplication(sys.argv)
theme.apply_theme(app)
conn = open_database(TMP / "data" / "b.mscm.json")
bootstrap.ensure_seed_data(conn)
win = MainWindow(conn)
win.resize(1560, 940)
win.show()
app.processEvents()


def check(name, cond, extra=""):
    print(("  [OK]  " if cond else "  [FAIL]") + f" {name} {extra}")
    if not cond:
        raise SystemExit(1)


def set_edit(page, key, value):
    w = page._editors[key]
    if isinstance(w, QComboBox):
        idx = w.findText(str(value))
        if idx >= 0:
            w.setCurrentIndex(idx)
    elif isinstance(w, QLineEdit):
        w.setText(str(value))


page = win._page("batches")
app.processEvents()
heads = [page.table.horizontalHeaderItem(i).text() for i in range(page.table.columnCount())]
check("首列序号、次列入库日期", heads[:3] == ["序号", "入库日期", "批次编号"], str(heads[:3]))
check("结余两列在表内", "当前存栏(只)" in heads and "暂养结存(kg)" in heads)
check("不摆供应商电话 / 状态列", "供应商电话" not in heads and "状态" not in heads, str(heads))
check("序号格可插入", isinstance(page.table.cellWidget(0, 0), bl.SeqCell))
check("操作列冻结", isinstance(page.ops, bl.OpsStrip))
page.ops._relayout()
box = page.ops._btns.get(0)
check("操作列只有一枚多功能集", box is not None and len(box.findChildren(QPushButton)) == 1)

# ---------------- 序号「＋」插行 → 填 → 离开即存 ----------------
before = len(page._rows)
page.table.cellWidget(0, 0).insertRequested.emit()
check("插行位置在本行下面", page._editing_row() == 1, str(page._editing_row()))
set_edit(page, "entry_date", "2026-11-25")
page._editors["entry_date"].setDate(QDate(2026, 11, 25))
set_edit(page, "category", "绵羊")
set_edit(page, "supplier", "会泽测试牧场")
set_edit(page, "count", 40)
set_edit(page, "weight", 1600)
set_edit(page, "price", 29.5)
page._on_edit_changed()
code_preview = page._editors["code"].text()
amount_preview = page._editors["_amount"].text()
check("编号随日期现算", code_preview == "20261125", code_preview)
check("金额随 kg × 均价现算", abs(float(amount_preview) - 47200.0) < 0.01, amount_preview)
page._editors["price"].setFocus()
app.processEvents()
page.f_kw.setFocus()                       # 点别处＝离开本行
app.processEvents()
check("离开即存", len(page._rows) == before + 1 and not page._editors,
      f"{before} → {len(page._rows)}")
saved = next(r for r in page._rows if str(r.get("code")) == "20261125")
check("落入库金额＝kg × 均价", abs(float(saved.get("amount") or 0) - 47200.0) < 0.01,
      saved.get("amount"))
check("列表带现算结余列", saved.get("_bal_weight") is not None and saved.get("_stock") is not None,
      f'{saved.get("_stock")} / {saved.get("_bal_weight")}')
inb = repo.feed_inbound_row(conn, int(saved["id"]))
check("暂养入库行同步生成",
      inb is not None and inb.get("date") == "2026-11-25"
      and abs(float(inb.get("in_weight") or 0) - 1600.0) < 0.01,
      f'{inb and inb.get("date")} / {inb and inb.get("in_weight")}')

# ---------------- 改日期 → 编号与暂养入库日期跟着变 ----------------
row = page._rows.index(saved)
page._begin_edit(row)
page._editors["entry_date"].setDate(QDate(2026, 11, 26))
page._on_edit_changed()
page.save_row()
saved = next(r for r in page._rows if int(r["id"]) == int(saved["id"]))
inb = repo.feed_inbound_row(conn, int(saved["id"]))
check("改日期 → 编号重算", str(saved.get("code")) == "20261126", saved.get("code"))
check("改日期 → 暂养入库行跟着改成 2026-11-26", inb.get("date") == "2026-11-26", inb.get("date"))

# ---------------- 只数校验：0 只不许存 ----------------
page.on_new()
set_edit(page, "supplier", "空批次测试")
page._editors["supplier"].setFocus()
app.processEvents()
page.f_kw.setFocus()
app.processEvents()
check("只数为 0 不落库（草稿原样搁着）",
      page._draft is not None and len(page._rows) == before + 1,
      f"draft={page._draft is not None}")
page.cancel_edit()

# ---------------- 删除：已被台账引用的批次拦得住 ----------------
ok, msg = repo.delete_batch(conn, int(saved["id"]))
check("有入库行的批次不能删", not ok and "台账记录" in msg, msg)
try:
    page.delete_record(int(saved["id"]))
    raise SystemExit("应当抛 BatchInUse")
except BatchInUse as exc:
    check("页面删除也拦得住", "台账记录" in str(exc), str(exc))

# ---------------- 撤消 / 恢复 ----------------
page.undo()
check("撤消：新增的批次收回", not any(str(r.get("code")) == "20261126" for r in page._rows))
page.redo()
check("恢复：批次回来了", any(str(r.get("code")) == "20261126" for r in page._rows))

# ---------------- 删掉的两列：老数据不能被抹掉 ----------------
seed = next(r for r in repo.list_batches(conn) if str(r.get("supplier_phone") or "").strip())
page.refresh()
row = next(i for i, r in enumerate(page._rows) if int(r["id"]) == int(seed["id"]))
page._begin_edit(row)
page._editors["pen"].setText("A9")
page.save_row()
after = repo.get_batch(conn, int(seed["id"])) or {}
check("改了别的字段：供应商电话原样留着",
      str(after.get("supplier_phone") or "") == str(seed.get("supplier_phone") or ""),
      f'{seed.get("supplier_phone")} → {after.get("supplier_phone")}')
check("改了别的字段：状态原样留着",
      str(after.get("status") or "") == str(seed.get("status") or ""),
      f'{seed.get("status")} → {after.get("status")}')
check("没编辑器的字段也照旧（回库比对）", str(after.get("pen")) == "A9", str(after.get("pen")))

# ---------------- 导出 ----------------
out = TMP / "活羊入库&结余.xlsx"
xl_export.export_batches(out, page._rows)
check("导出成功", out.exists() and out.stat().st_size > 4000, f"{out.stat().st_size} B")
from openpyxl import load_workbook  # noqa: E402

ws = load_workbook(out).active
check("导出首列是入库日期", ws.cell(row=3, column=1).value == "入库日期", ws.cell(row=1, column=1).value)
heads_x = [ws.cell(row=3, column=c).value for c in range(1, ws.max_column + 1)]
check("导出不含电话 / 状态列", "联系电话" not in heads_x and "状态" not in heads_x, str(heads_x))
check("导出带合计行", any(str(ws.cell(row=r, column=1).value or "") == "合计"
                          for r in range(1, ws.max_row + 1)))

print("[OK] 活羊入库&结余 冒烟全部通过", TMP)
conn.close()
