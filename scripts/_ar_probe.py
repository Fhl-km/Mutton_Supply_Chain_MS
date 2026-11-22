"""应收款项交互冒烟（2026-11 改版后）：自动提取挂账、逐笔收款、未收现算、撤消与导出。

用法：.venv/Scripts/python.exe scripts/_ar_probe.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TMP = Path(tempfile.mkdtemp(prefix="mscm_ar_"))
os.environ["MSCM_DATA_DIR"] = str(TMP / "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from mscm import config  # noqa: E402
from mscm.core import bootstrap, calc, repo  # noqa: E402
from mscm.core.db import open_database  # noqa: E402
from mscm.core.services import export as xl_export  # noqa: E402
from mscm.ui import theme  # noqa: E402
import mscm.ui.pages.receivable as rp  # noqa: E402
from mscm.ui.main_window import MainWindow  # noqa: E402

rp.info = lambda *a, **k: None      # offscreen 下别弹模态框

app = QApplication(sys.argv)
theme.apply_theme(app)
config.EXPORT_DIR = TMP / "导出报表"      # 别把测试出的表写进项目导出目录
config.ensure_dirs()
conn = open_database(TMP / "data" / "ar.mscm.json")
print("[seed]", bootstrap.ensure_seed_data(conn).message)

win = MainWindow(conn)
win.resize(1500, 920)
win.show()
app.processEvents()

OK = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global OK
    OK = OK and bool(cond)
    print(f"  [{'OK' if cond else 'NG'}]   {name} {detail}")


def rows(tab):
    return tab._rows


win.show_page("receivable")
page = win.pages["receivable"]
inv, opn = page.tab_inv, page.tab_open
check("页签只剩 应收款 / 未收款", page.tabs.count() == 2, f"{page.tabs.count()} 个")

check("应收款按挂账自动提取", len(inv._rows) >= 3, f"{len(inv._rows)} 行")
check("收款子行挂在应收单下面",
      any(r.get("_kind") == "receipt" for r in inv._rows),
      f"{sum(1 for r in inv._rows if r.get('_kind') == 'receipt')} 笔")

first = next(r for r in inv._rows if r.get("_kind") == "invoice")
check("销售批次＝T+日期", first.get("sale_batch") == "T20261120", str(first.get("sale_batch")))
check("结算方式取客户名录", first.get("settle") == "周结", str(first.get("settle")))
check("约定收款日＝销售日期+账期", first.get("due_date") == "2026-11-27", str(first.get("due_date")))
seq_blank = [i for i, r in enumerate(inv._view) if r.get("_kind") == "receipt"]
check("收款行不占序号",
      all(inv.table.cellWidget(i, 0)._number == "" for i in seq_blank if i < inv.table.rowCount()))

# ---------------- 同一张单再加一笔收款（一对多） ----------------
inv_id = int(first.get("id"))
before_receipts = sum(1 for r in rows(inv)
                      if r.get("_kind") == "receipt" and r.get("invoice_id") == inv_id)
inv.start_receipt(first)
app.processEvents()
check("记一笔收款：开出收款行", inv._draft is not None
      and inv._draft.get("_kind") == "receipt" and inv._draft.get("invoice_id") == inv_id)
inv._editors["receipt_date"].setDate(inv._editors["receipt_date"].date())
inv._editors["receipt_amount"].setText("232")
inv.save_row()
app.processEvents()
after_receipts = sum(1 for r in rows(inv)
                     if r.get("_kind") == "receipt" and r.get("invoice_id") == inv_id)
check("收款行多了一条", after_receipts == before_receipts + 1,
      f"{before_receipts} → {after_receipts}")

inv_row = next(r for r in rows(inv) if r.get("_kind") == "invoice" and r.get("id") == inv_id)
check("未收自动减", abs(float(inv_row.get("_unpaid")) - 5000.0) < 0.01,
      f"未收 {inv_row.get('_unpaid')}")
# 应收单行：收款日期格写「小计」，收款金额格是下面几笔的合计
sub_idx = inv._view.index(inv_row)
col_due = inv._col_index("receipt_date")
col_amt = inv._col_index("receipt_amount")
check("应收单行「小计」列示",
      inv.table.item(sub_idx, col_due).text() == "小计"
      and inv.table.item(sub_idx, col_amt).text() == "1,232.00",
      f"{inv.table.item(sub_idx, col_due).text()} / {inv.table.item(sub_idx, col_amt).text()}")
labels = [f.label for f in inv.FIELDS]
check("列名：已收金额 / 抹零金额 / 未收金额",
      "已收金额" in labels and "抹零金额" in labels
      and labels.index("抹零金额") + 1 == labels.index("未收金额"),
      " | ".join(labels))

# ---------------- 收款行只能改日期 / 金额 ----------------
receipt_row = next(r for r in rows(inv) if r.get("_kind") == "receipt"
                   and r.get("invoice_id") == inv_id)
idx = inv._view.index(receipt_row)
inv._begin_edit(idx)
app.processEvents()
check("收款行只开三列录入框", set(inv._editors) == {"receipt_date", "receipt_amount", "waiver"},
      str(sorted(inv._editors)))
inv.cancel_edit()
app.processEvents()

# ---------------- 抹零：未收 = 应收 − 已收 − 抹零 ----------------
inv.refresh()
app.processEvents()
inv_id2 = int(first.get("id"))
base_unpaid = float(next(r for r in rows(inv)
                         if r.get("_kind") == "invoice" and r.get("id") == inv_id2)["_unpaid"])
inv.start_receipt(next(r for r in rows(inv)
                       if r.get("_kind") == "invoice" and r.get("id") == inv_id2))
app.processEvents()
inv._editors["receipt_amount"].setText("500")
inv._editors["waiver"].setText("12")
inv.save_row()
app.processEvents()
inv_row2 = next(r for r in rows(inv) if r.get("_kind") == "invoice" and r.get("id") == inv_id2)
check("抹零计入未收", abs(float(inv_row2.get("_unpaid")) - (base_unpaid - 512)) < 0.01,
      f"{base_unpaid} → {inv_row2.get('_unpaid')}")
i_w = inv._col_index("waiver")
check("应收单行抹零小计显示", inv.table.item(inv._view.index(inv_row2), i_w).text() != "",
      inv.table.item(inv._view.index(inv_row2), i_w).text())
inv.undo()
app.processEvents()

# ---------------- 撤消这笔收款 ----------------
inv.undo()
app.processEvents()
got = [r for r in rows(inv) if r.get("_kind") == "invoice" and r.get("id") == inv_id]
check("撤消：收款行收回、未收回原值",
      got and abs(float(got[0].get("_unpaid")) - 5232.0) < 0.01,
      f"未收 {got[0].get('_unpaid') if got else '—'}")

# ---------------- 销售单改金额，应收跟着变（自动提取） ----------------
src = conn.rows("slaughter_out")
target = next(r for r in src if r.get("pay_method") in ("挂账", "月结")
              and r.get("target") == "对外销售")
old_total = float(target.get("weight") or 0) * float(target.get("price") or 0)
conn.update("slaughter_out", int(target["id"]), {"price": float(target["price"]) + 2})
conn.commit()
created, updated, cancelled = repo.sync_ar_from_sales(conn, "slaughter")
ar = [r for r in calc.ar_invoices(conn, "slaughter")
      if r.get("link_key") == f"sout:{int(target['id'])}"]
check("销售单改价 → 应收金额同步", ar and abs(float(ar[0]["_amount"])
                                       - (old_total + 2 * float(target["weight"]))) < 0.01,
      f"{old_total:.2f} → {ar[0]['_amount'] if ar else '—'}")
conn.update("slaughter_out", int(target["id"]), {"price": float(target["price"]) - 2})
conn.commit()
repo.sync_ar_from_sales(conn, "slaughter")

# ---------------- 手工补一张应收：销售批次自动补 T、约定收款日算出 ----------------
page.tab_inv.on_new()
app.processEvents()
inv._editors["customer"].setCurrentText("昭通小串烧烤")
inv._editors["amount"].setText("1200")
inv.save_row()
app.processEvents()
manual = [r for r in calc.ar_invoices(conn, "slaughter", 0, "2026-11-01", "2026-11-20")
          if r.get("customer") == "昭通小串烧烤" and not r.get("link_key")]
check("手工应收：销售批次自动带 T", manual and manual[0]["sale_batch"].startswith("T"),
      manual[0]["sale_batch"] if manual else "—")
check("手工应收：结算方式/收款日按名录算",
      manual and manual[0]["settle"] == "月结" and bool(manual[0]["due_date"]),
      f"{manual[0]['settle']} / {manual[0]['due_date']}" if manual else "—")

# ---------------- 自动提取的应收单不许直接删 ----------------
inv.refresh()
app.processEvents()
linked = next(r for r in rows(inv) if r.get("_kind") == "invoice" and r.get("link_key"))
n_link = len([r for r in conn.rows("ar_invoice") if r.get("link_key") == linked["link_key"]])
inv._apply_delete(linked)
app.processEvents()
n_link2 = len([r for r in conn.rows("ar_invoice") if r.get("link_key") == linked["link_key"]])
check("自动提取的应收单删不掉（提示改销售单）", n_link == n_link2 == 1, f"{n_link} → {n_link2}")

# ---------------- 手工应收：删单连带收款、撤消一起回来 ----------------
rid = int(manual[0]["id"]) if manual else 0
for day, amt in (("2026-11-18", 500.0), ("2026-11-20", 300.0)):
    conn.insert("ar_receipt", {"biz": "slaughter", "store_id": 0, "invoice_id": rid,
                               "date": day, "customer": "昭通小串烧烤", "amount": amt})
conn.commit()
inv.refresh()
app.processEvents()
vivtim = next(r for r in rows(inv) if r.get("id") == rid)
before_kids = len([r for r in rows(inv) if r.get("_kind") == "receipt"
                   and r.get("invoice_id") == rid])
inv._apply_delete(vivtim)
app.processEvents()
still = [r for r in conn.rows("ar_receipt") if int(r.get("invoice_id") or 0) == rid]
check("手工应收单：删单连带删收款", not still and before_kids == 2, f"收款 {before_kids} → 0")
inv.undo()
app.processEvents()
back = [r for r in rows(inv) if r.get("_kind") == "invoice"
        and r.get("customer") == "昭通小串烧烤"]
back_kids = len([r for r in rows(inv) if r.get("_kind") == "receipt"
                 and back and r.get("invoice_id") == back[0].get("id")])
check("撤消：手工单与它的两笔收款一起回来", len(back) == 1 and back_kids == 2,
      f"收款 {before_kids} → {back_kids}")

# ---------------- 未收款 / 逾期筛选 ----------------
opn.refresh()
app.processEvents()
check("未收款＝应收−已收", opn._rows and
      abs(sum(float(r.get("_unpaid") or 0) for r in opn._rows)
          - (calc.ar_summary(conn, "slaughter")["unpaid"])) < 0.01,
      f"{len(opn._rows)} 笔")
opn.chk_overdue.setChecked(True)
app.processEvents()
print("[overdue only]", len(opn._rows), opn.sums.right.text())
opn.reset()

# ---------------- 导出 ----------------
for biz, sid, name in (("slaughter", 0, "屠宰"), ("store", 1, "门店")):
    p1 = xl_export.export_receivable_workbook(TMP / f"应收-{name}.xlsx", conn, biz, sid,
                                              "2026-11-01", "2026-11-20")
    p2 = xl_export.export_ar_open(TMP / f"未收-{name}.xlsx", conn, biz, sid, "2026-11-20")
    check(f"导出 {name} 应收+未收", p1.stat().st_size > 3000 and p2.stat().st_size > 3000,
          f"{p1.name} / {p2.name}")

p3 = xl_export.export_module(TMP / "出库.xlsx", "slaughter_out", conn, "2026-11-01", "2026-11-20")
check("屠宰出库导出含销售批次", p3.stat().st_size > 3000, p3.name)

# ---------------- 未收款页：列结构与数据来源 ----------------
opn_cols = [c.title for c in opn.COLS]
check("未收款列：销售批次在首位（取自应收款明细）",
      opn_cols[:2] == ["序号", "销售批次"], " | ".join(opn_cols))
check("未收款列：客户联系电话后接业务员",
      opn_cols.index("客户联系电话") + 1 == opn_cols.index("业务员"), " | ".join(opn_cols))
ar_open = calc.ar_open_items(conn, "slaughter", 0, page.ctx.biz_date)
check("未收款行数＝应收款明细里未收>0 的行",
      len(opn._rows) == len([r for r in calc.ar_invoices(conn, "slaughter")
                             if float(r.get("_unpaid") or 0) > 0.005]),
      f"{len(opn._rows)} 行")

# ---------------- 收多了：未收金额以负数列示（预收） ----------------
inv.on_new()
app.processEvents()
inv._editors["customer"].setCurrentText("昭通小串烧烤")
inv._editors["amount"].setText("1000")
inv.save_row()
app.processEvents()
pre = next(r for r in rows(inv) if r.get("_kind") == "invoice"
           and r.get("customer") == "昭通小串烧烤" and abs(float(r.get("_amount") or 0) - 1000) < 0.01)
inv.start_receipt(pre)
app.processEvents()
inv._editors["receipt_amount"].setText("1300")
inv.save_row()
app.processEvents()
pre = next(r for r in rows(inv) if r.get("_kind") == "invoice"
           and r.get("customer") == "昭通小串烧烤" and abs(float(r.get("_amount") or 0) - 1000) < 0.01)
i_pre = inv._view.index(pre)
c_unpaid = inv._col_index("_unpaid")
cell_text = inv.table.item(i_pre, c_unpaid).text()
fg = inv.table.item(i_pre, c_unpaid).foreground().color().name().lower()
check("实收大于应收：未收以负数（预收）列示",
      abs(float(pre.get("_unpaid") or 0) + 300) < 0.01 and cell_text == "-300.00",
      f"未收 {pre.get('_unpaid')} / 显示 {cell_text}")
check("预收行标绿（与欠款区分）", fg == theme.NEGATIVE.lower(), fg)
check("合计条单列预收", "预收 300.00" in inv.sums.right.text(), inv.sums.right.text())
summary = calc.ar_summary(conn, "slaughter")
check("汇总的预收金额", abs(float(summary.get("prepaid") or 0) - 300) < 0.01,
      f"prepaid={summary.get('prepaid')}")
check("校验页提示预收款", any(c.item.startswith("预收款") for c in calc.checks(conn)),
      next((c.item for c in calc.checks(conn) if c.item.startswith("预收款")), "—"))
# 收尾：把这笔预收单删掉（收据跟着走），别影响后面的合计
inv._apply_delete(pre)
app.processEvents()

# ---------------- 生成对账单（弹窗打桩，只验出表） ----------------
class _FakeForm:
    def __init__(self, *a, **k):
        self._v = {"customer": "昭通小串烧烤", "contact": "赵老板",
                   "phone": "139****3308", "as_of": "2026-11-20"}

    def exec(self):
        return QDialog.Accepted

    def values(self):
        return dict(self._v)


_orig_form, _orig_info = rp.FormDialog, rp.info
rp.FormDialog = _FakeForm
rp.info = lambda *a, **k: None
opn.refresh()
app.processEvents()
try:
    opn.on_statement()
finally:
    rp.FormDialog, rp.info = _orig_form, _orig_info
app.processEvents()
stmt = Path(config.EXPORT_DIR) / "对账单-昭通小串烧烤-2026-11-20.xlsx"
check("生成对账单：出表落到导出报表/", stmt.exists() and stmt.stat().st_size > 4000,
      stmt.name if stmt.exists() else "未生成")
if stmt.exists():
    from openpyxl import load_workbook
    ws = load_workbook(stmt).active
    head = [ws.cell(row=4, column=i).value for i in range(1, 9)]
    col_a = [str(ws.cell(row=r, column=1).value or "") for r in range(1, ws.max_row + 1)]
    check("对账单表头与合计（照模板对账单2）",
          head[:7] == ["序号", "销售批次", "商品 / 摘要", "应收金额(元)", "已收金额(元)",
                       "抹零金额(元)", "未收金额(元)"]
          and "合计" in col_a
          and any(x.startswith("截至") and "未收合计" in x for x in col_a),
          " | ".join(str(x) for x in head[:7]))

# ---------------- 日期框：点右端箭头能弹出日历（上次收成 0 宽就点不开了） ----------------
inv.refresh()
app.processEvents()
head = next(r for r in rows(inv) if r.get("_kind") == "invoice")
inv.start_receipt(head)
app.processEvents()
de = inv._editors["receipt_date"]
popup = de.calendarWidget().parentWidget()
QTest.mouseClick(de, Qt.LeftButton, Qt.NoModifier, QPoint(de.width() - 8, de.height() // 2))
app.processEvents()
check("收款日期点箭头能弹出日历", popup.isVisible() and popup.width() >= 260,
      f"{popup.width()}×{popup.height()}")
popup.hide()
inv.cancel_edit()
app.processEvents()

print("[checks]")
for c in calc.checks(conn):
    print("  ", c.label, c.item, "|", c.actual)
conn.close()
print("OK" if OK else "有断言没通过", TMP)
sys.exit(0 if OK else 1)
