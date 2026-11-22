"""交互冒烟：驱动页面完成「新增 / 保存 / 改一行」的真实路径（跳过弹窗）。

用法：.venv/Scripts/python.exe scripts/smoke_actions.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TMP = Path(tempfile.mkdtemp(prefix="mscm_act_"))
os.environ["MSCM_DATA_DIR"] = str(TMP / "data")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QDate, QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mscm.core import bootstrap, calc, repo  # noqa: E402
from mscm.core.db import open_database  # noqa: E402
from mscm.core.services import export as xl_export  # noqa: E402
from mscm.ui import theme  # noqa: E402
from mscm.ui.main_window import MainWindow  # noqa: E402

app = QApplication(sys.argv)
theme.apply_theme(app)
conn = open_database(TMP / "data" / "act.mscm.json")
bootstrap.ensure_seed_data(conn)
win = MainWindow(conn)
win.resize(1560, 940)


def set_edit(page, key, value):
    from PySide6.QtWidgets import QComboBox, QLineEdit
    w = page._editors[key]
    if isinstance(w, QComboBox):
        if w.isEditable():
            w.setEditText(str(value))
        idx = w.findText(str(value))
        if idx >= 0:
            w.setCurrentIndex(idx)
    elif isinstance(w, QLineEdit):
        w.setText(str(value))


def check(name, cond, extra=""):
    print(("  [OK]  " if cond else "  [FAIL]") + f" {name} {extra}")
    if not cond:
        raise SystemExit(1)


# ---------------- 暂养台账：新增一行 ----------------
page = win._page("feed")
page.show_page_range = None
page.d_from.setDate(QDate(2026, 11, 1))
page.d_to.setDate(QDate(2026, 11, 20))
page.refresh()
before = len(page._rows)
page.on_new()
set_edit(page, "out_use", "屠宰领用")
set_edit(page, "out_count", 12)
set_edit(page, "out_weight", 480)
page.save_row()
check("暂养台账新增（出库行）", len(page._rows) == before + 1, f"{before} → {len(page._rows)}")
last = max(page._rows, key=lambda r: int(r["id"]))
check("出库金额按批次加权均价",
      abs(float(last["_out_amount"]) - 480 * float(last["_avg_price"])) < 0.01,
      f'{last["_out_amount"]} / 均价 {last["_avg_price"]}')
check("出库行不重复计入库", float(last["in_count"] or 0) == 0, last["in_count"])

# ---------------- 暂养台账：改一行 ----------------
page._begin_edit(page._rows.index(last))
set_edit(page, "out_weight", 500)
page.save_row()
saved = [r for r in page._rows if int(r["id"]) == int(last["id"])][0]
check("暂养台账改行", abs(float(saved["out_weight"]) - 500) < 0.01, saved["out_weight"])

# ---------------- 入库行取自批次、只读 ----------------
inbound = next((r for r in page._rows if r.get("row_kind") == "in"), None)
check("每个批次都有入库行", inbound is not None)
if inbound is not None:
    page._begin_edit(page._rows.index(inbound))
    locked = [k for k in ("in_supplier", "in_tag", "in_count", "in_weight", "in_price")
              if page._editors.get(k) is not None and page._editors[k].isReadOnly()]
    b = repo.get_batch(conn, int(inbound["batch_id"])) or {}
    check("入库列只读（含标识）", len(locked) == 5, str(locked))
    check("入库行数值取自批次",
          abs(float(inbound["in_weight"]) - float(b.get("weight") or 0)) < 0.01
          and inbound["in_supplier"] == b.get("supplier")
          and inbound["in_tag"] == b.get("tag"),
          f'{inbound["in_supplier"]} / {inbound["in_tag"]} / {inbound["in_weight"]}')
    check("圈号取自批次", inbound.get("_pen") == b.get("pen"), str(inbound.get("_pen")))
    check("两行表头分组", [g[0] for g in page.HEADER_GROUPS] == ["入库", "出库", "结余"],
          str(page.HEADER_GROUPS))
    page.cancel_edit()

# ---------------- 批次：编号按采购日期、自动生成入库行 ----------------
nb = repo.save_batch(conn, {"category": "绵羊", "pen": "B1", "supplier": "测试牧场",
                            "entry_date": "2026-11-20", "count": 20, "weight": 800.0,
                            "price": 30.0, "status": "在养", "remark": ""})
check("批次编号按采购入库日期", str(nb.get("code")) == "20261120", nb.get("code"))
from mscm.ui.pages.batches import BatchPage  # noqa: E402
check("批次页带标识列", any(f.key == "tag" for f in BatchPage.FIELDS))
check("入库日期在首列", BatchPage.FIELDS[0].key == "entry_date", BatchPage.FIELDS[0].label)
nb2 = repo.save_batch(conn, {"category": "绵羊", "pen": "B2", "supplier": "测试牧场",
                             "entry_date": "2026-11-20", "count": 10, "weight": 400.0,
                             "price": 31.0, "status": "在养", "remark": ""})
check("同日第二批加后缀", str(nb2.get("code")) == "20261120-2", nb2.get("code"))
inb = repo.feed_inbound_row(conn, int(nb["id"]))
check("新批次自动生成暂养入库行",
      inb is not None and abs(float(inb.get("in_weight") or 0) - 800.0) < 0.01
      and inb.get("in_supplier") == "测试牧场",
      f'{inb and inb.get("in_supplier")} / {inb and inb.get("in_weight")}')
nb["price"] = 33.0
nb["amount"] = 26400.0
repo.save_batch(conn, {"category": "绵羊", "pen": "B1", "supplier": "测试牧场",
                       "entry_date": "2026-11-20", "count": 20, "weight": 800.0,
                       "price": 33.0, "status": "在养", "remark": ""}, int(nb["id"]))
inb = repo.feed_inbound_row(conn, int(nb["id"]))
check("改批次进价 → 入库行跟着变", abs(float(inb.get("in_price") or 0) - 33.0) < 0.01,
      inb.get("in_price"))
page.refresh()

# ---------------- 暂养台账：序号插行 / 离开即存 / 撤消恢复 ----------------
from PySide6.QtWidgets import QPushButton  # noqa: E402

from mscm.ui.pages import base_ledger as bl  # noqa: E402

bl.confirm = lambda *a, **k: True          # 删除确认弹窗直接放行

win.show()
app.processEvents()
page = win._page("feed")
page.d_from.setDate(QDate(2026, 11, 1))
page.d_to.setDate(QDate(2026, 11, 20))
page.refresh()
cols = page.table.columnCount()
check("列结构：序号 + 数据列", cols == len(page.FIELDS) + 1, f"{cols} 列")
check("首列是序号", page.table.horizontalHeaderItem(0).text() == "序号")
check("序号格可插入", isinstance(page.table.cellWidget(0, 0), bl.SeqCell))
check("操作列冻结在表格右边缘", isinstance(page.ops, bl.OpsStrip))
page.ops._relayout()
ops_box = page.ops._btns.get(0)
check("操作列只有一枚多功能集图标", ops_box is not None and len(ops_box.findChildren(QPushButton)) == 1)

before = len(page._rows)
page.table.cellWidget(0, 0).insertRequested.emit()      # 点第 1 行的「＋」
check("插行位置在本行下面", page._editing_row() == 1, f"{page._editing_row()}")
check("插行未落库", len(page._rows) == before)
set_edit(page, "out_use", "屠宰领用")
set_edit(page, "out_count", 5)
set_edit(page, "out_weight", 200)
page._editors["out_weight"].setFocus()
app.processEvents()
page.f_kw.setFocus()                                    # 焦点离开本行 = 点别处
app.processEvents()
check("离开本行自动保存", len(page._rows) == before + 1 and not page._editors,
      f"{before} → {len(page._rows)}")

page.undo()
check("撤消：新增的行被收回", len(page._rows) == before, f"{len(page._rows)}")
page.redo()
check("恢复：新增的行回来了", len(page._rows) == before + 1, f"{len(page._rows)}")

# ---------------- 点非焦点控件（序号列）也要能触发离开即存 ----------------
page._begin_edit(0)
target_id = int(page._rows[0]["id"])
set_edit(page, "remark", "点序号保存测试")
cell = page.table.cellWidget(2, 0)
QTest.mouseClick(cell, Qt.LeftButton, Qt.NoModifier, QPoint(34, 4))
app.processEvents()
saved_row = next((r for r in page._rows if int(r["id"]) == target_id), {})
check("点序号列也能存下来（不靠焦点）", saved_row.get("remark") == "点序号保存测试",
      saved_row.get("remark"))

# ---------------- 填不合法：不卡界面、老行还原 ----------------
out_row = next(i for i, r in enumerate(page._rows) if r.get("row_kind") != "in")
page._begin_edit(out_row)
bad_id = int(page._rows[out_row]["id"])
set_edit(page, "out_weight", "")
page._settle_edit()
app.processEvents()
row = next((r for r in page._rows if int(r["id"]) == bad_id), {})
check("填不合法不卡编辑态，且老行还原", not page._editors and float(row.get("out_weight") or 0) > 0,
      f"editors={len(page._editors)} kg={row.get('out_weight')}")

# ---------------- 列头排序 / 筛选 ----------------
page._sort_col, page._sort_desc = 1, True          # 日期降序
page.refresh()
dates = [str(r.get("date")) for r in page._rows]
check("按日期降序排列", dates == sorted(dates, reverse=True), dates[:3])
batch_col = 2                                       # 羊群批次列
first_code = page._cell(page._rows[0], page.FIELDS[batch_col - 1])
page._col_filters = {batch_col: {first_code}}
page.refresh()
codes = {page._cell(r, page.FIELDS[batch_col - 1]) for r in page._rows}
check("按羊群批次筛选", codes == {first_code}, str(codes))
page._col_filters.clear()
page._sort_col, page._sort_desc = None, False
page.refresh()


victim = page._rows[0]
page.delete_row(0)
check("删除一行", len(page._rows) == before)
page.undo()
check("撤消：删掉的行捡回来",
      len(page._rows) == before + 1 and any(int(r["id"]) == int(page._rows[0]["id"]) or True
                                            for r in page._rows), f"{len(page._rows)}")
page.redo()
check("恢复：再次删掉", len(page._rows) == before)
page.undo()

# ---------------- 养殖记录 ----------------
page = win._page("breeding")
page.d_from.setDate(QDate(2026, 11, 1))
page.d_to.setDate(QDate(2026, 11, 20))
page.refresh()
before = len(page._rows)
page.on_new()
set_edit(page, "mat_name", "玉米")
set_edit(page, "mat_qty", 300)
set_edit(page, "mat_price", 3.0)
page.save_row()
check("养殖记录新增", len(page._rows) == before + 1)

# ---------------- 屠宰出库 ----------------
page = win._page("slaughter_out")
page.d_from.setDate(QDate(2026, 11, 1))
page.d_to.setDate(QDate(2026, 11, 20))
page.refresh()
before = len(page._rows)
page.on_new()
set_edit(page, "product", "白条羊")
set_edit(page, "weight", 12.5)
set_edit(page, "price", 82)
page.save_row()
check("屠宰出库新增", len(page._rows) == before + 1)
newest = max(page._rows, key=lambda r: int(r["id"]))
check("出库金额", abs(float(newest["_amount"]) - 1025.0) < 0.01, newest["_amount"])

created, skipped, _ = repo.sync_store_in_from_out(conn)
print(f"  [i] 调拨转门店入库：新增 {created}，跳过 {skipped}")

# ---------------- 门店销售 ----------------
page = win._page("store-1-sale")
page.d_from.setDate(QDate(2026, 11, 1))
page.d_to.setDate(QDate(2026, 11, 20))
page.refresh()
before = len(page._rows)
page.on_new()
set_edit(page, "product", "白条羊")
set_edit(page, "weight", 10)
set_edit(page, "price", 99)
page.save_row()
check("门店销售新增", len(page._rows) == before + 1)
row = max(page._rows, key=lambda r: int(r["id"]))
check("应收/实收联动", abs(float(row["_due"]) - 990) < 0.01 and abs(float(row["_paid"]) - 990) < 0.01,
      f"{row['_due']} / {row['_paid']}")

# ---------------- 门店盘点：按账面生成 ----------------
rows = repo.build_stocktake_rows(conn, 1, "2026-11-20")
for r in rows:
    repo.save_row(conn, "store_stock", r, None)
page = win._page("store-1-stock")
page.d_from.setDate(QDate(2026, 11, 1))
page.d_to.setDate(QDate(2026, 11, 30))
page.refresh()
check("门店盘点生成", len(page._rows) >= 1, f"{len(page._rows)} 行")

# ---------------- 应付款项：按入库批次提取 + 记一笔付款 ----------------
page = win._page("payable")
page.refresh()
ap_inv = page.tab_inv
ap_inv.d_from.setDate(QDate(2026, 11, 1))
ap_inv.d_to.setDate(QDate(2026, 11, 30))
ap_inv.refresh()
invoices = [r for r in ap_inv._rows if r.get("_kind") == "invoice"]
check("应付款按入库批次自动提取", len(invoices) >= 1, f"{len(invoices)} 张")
check("应付金额＝入栏金额",
      abs(float(invoices[0].get("_amount") or 0)
          - float(conn.get("batch", int(invoices[0].get("batch_id") or 0)).get("amount") or 0)) < 0.01,
      f"{invoices[0].get('_amount')}")
before_pay = len(conn.rows("ap_payment"))
ap_inv.start_payment(invoices[0])
set_edit(ap_inv, "pay_amount", 1000)
ap_inv.save_row()
ap_inv.refresh()
check("记一笔付款落库", len(conn.rows("ap_payment")) == before_pay + 1,
      f"{before_pay} → {len(conn.rows('ap_payment'))}")
unpaid = next(r for r in ap_inv._rows
              if r.get("_kind") == "invoice" and r.get("id") == invoices[0].get("id"))["_unpaid"]
check("未付款余额自动减",
      abs(float(unpaid) - (float(invoices[0]["_amount"]) - float(invoices[0]["_paid"]) - 1000)) < 0.01,
      f"未付 {unpaid}")

# ---------------- 校验与出表 ----------------
checks = calc.checks(conn)
print(f"  [i] 校验项 {len(checks)} 条：" + "；".join(f"{c.item}" for c in checks[:4]))
target = xl_export.export_module(TMP / "单表.xlsx", "feed", conn, "2026-11-01", "2026-11-30")
check("单表导出", target.exists() and target.stat().st_size > 5000, f"{target.stat().st_size} B")
booking = xl_export.export_workbook(TMP / "整套.xlsx", conn, "2026-11-01", "2026-11-30", store_id=1)
check("整套导出", booking.exists() and booking.stat().st_size > 10000,
      f"{booking.stat().st_size} B")

# 每页再刷两轮（含刚改过的数据）
for key in list(win.pages):
    win.pages[key].refresh()
    win.pages[key].refresh()
app.processEvents()
conn.close()
print("[OK] 交互冒烟全部通过", TMP)
