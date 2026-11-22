"""应付款项（活羊采购与付款）交互冒烟：自动提取、逐笔付款、未付现算、撤消、导出与采购对账单。

用法：.venv/Scripts/python.exe scripts/_ap_probe.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TMP = Path(tempfile.mkdtemp(prefix="mscm_ap_"))
os.environ["MSCM_DATA_DIR"] = str(TMP / "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from mscm import config  # noqa: E402
from mscm.core import bootstrap, calc, repo  # noqa: E402
from mscm.core.db import open_database  # noqa: E402
from mscm.core.models import r2  # noqa: E402
from mscm.core.services import export as xl_export  # noqa: E402
from mscm.ui import theme  # noqa: E402
import mscm.ui.pages.payable as pp  # noqa: E402
from mscm.ui.main_window import MainWindow  # noqa: E402

pp.info = lambda *a, **k: None      # offscreen 下别弹模态框

app = QApplication(sys.argv)
theme.apply_theme(app)
config.EXPORT_DIR = TMP / "导出报表"      # 别把测试出的表写进项目导出目录
config.ensure_dirs()
conn = open_database(TMP / "data" / "ap.mscm.json")
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


win.show_page("payable")
page = win.pages["payable"]
inv, opn = page.tab_inv, page.tab_open
check("页签：应付款 / 未付款", page.tabs.count() == 2, f"{page.tabs.count()} 个")
check("应付单按入库批次自动提取", len(inv._rows) >= 2,
      f"{sum(1 for r in inv._rows if r.get('_kind') == 'invoice')} 张")
check("付款子行挂在应付单下面",
      any(r.get("_kind") == "payment" for r in inv._rows),
      f"{sum(1 for r in inv._rows if r.get('_kind') == 'payment')} 笔")

first = next(r for r in inv._rows if r.get("_kind") == "invoice")
check("入库批次取批次编号", first.get("batch_code") == "20261101", str(first.get("batch_code")))
check("应付金额＝入栏金额", abs(float(first.get("_amount") or 0) - 111300) < 0.01,
      f"{first.get('_amount')}")
check("已付＝下面各笔小计", abs(float(first.get("_paid") or 0) - 90000) < 0.01,
      f"{first.get('_paid')}")
check("未付＝应付−已付", abs(float(first.get("_unpaid") or 0) - 21300) < 0.01,
      f"{first.get('_unpaid')}")
check("联系电话取批次档案的供应商电话", first.get("phone") == "138****1101",
      str(first.get("phone")))

labels = [f.label for f in inv.FIELDS]
check("表头照模板「应付款」",
      labels[:9] == ["入库批次", "供应商名称", "联系电话", "商品", "应付金额",
                     "付款日期", "已付款金额", "未付款余额", "备注"],
      " | ".join(labels))

idx = inv._view.index(first)
check("应付单行「小计」列示",
      inv.table.item(idx, inv._col_index("pay_date")).text() == "小计"
      and inv.table.item(idx, inv._col_index("pay_amount")).text() == "90,000.00",
      f"{inv.table.item(idx, inv._col_index('pay_date')).text()} / "
      f"{inv.table.item(idx, inv._col_index('pay_amount')).text()}")

check("自动提取行：入库批次 / 应付金额只读",
      inv.locked_keys(first) == {"batch_code", "amount"}, str(sorted(inv.locked_keys(first))))

pay_seq = [i for i, r in enumerate(inv._view) if r.get("_kind") == "payment"]
check("付款行不占序号",
      all(inv.table.cellWidget(i, 0)._number == "" for i in pay_seq if i < inv.table.rowCount()))

# ---------------- 再记一笔付款（一对多） ----------------
inv_id = int(first.get("id"))
before = sum(1 for r in rows(inv) if r.get("_kind") == "payment" and r.get("invoice_id") == inv_id)
inv.start_payment(first)
app.processEvents()
check("记一笔付款：开出付款行",
      inv._draft is not None and inv._draft.get("_kind") == "payment"
      and inv._draft.get("invoice_id") == inv_id)
inv._editors["pay_date"].setDate(inv._editors["pay_date"].date())
inv._editors["pay_amount"].setText("5000")
inv.save_row()
app.processEvents()
after = sum(1 for r in rows(inv) if r.get("_kind") == "payment" and r.get("invoice_id") == inv_id)
check("付款行多了一条", after == before + 1, f"{before} → {after}")
cur = next(r for r in rows(inv) if r.get("_kind") == "invoice" and r.get("id") == inv_id)
check("未付自动减", abs(float(cur.get("_unpaid")) - 16300) < 0.01, f"未付 {cur.get('_unpaid')}")

# ---------------- 付款行只能改日期 / 金额 ----------------
pay_row = next(r for r in rows(inv) if r.get("_kind") == "payment" and r.get("invoice_id") == inv_id)
inv._begin_edit(inv._view.index(pay_row))
app.processEvents()
check("付款行只开两列录入框", set(inv._editors) == {"pay_date", "pay_amount"},
      str(sorted(inv._editors)))
inv.cancel_edit()
app.processEvents()

inv.undo()
app.processEvents()
cur = next(r for r in rows(inv) if r.get("_kind") == "invoice" and r.get("id") == inv_id)
check("撤消：付款行收回、未付回原值", abs(float(cur.get("_unpaid")) - 21300) < 0.01,
      f"未付 {cur.get('_unpaid')}")

# ---------------- 批次改进价，应付跟着变 ----------------
batch = next(b for b in conn.rows("batch") if b.get("code") == "20261101")
old_amount = float(batch.get("amount") or 0)
conn.update("batch", int(batch["id"]), {"price": float(batch["price"]) + 1.0,
                                        "amount": r2(float(batch["weight"]) * (float(batch["price"]) + 1.0))})
conn.commit()
repo.sync_ap_from_batches(conn)
ap = [r for r in calc.ap_invoices(conn) if r.get("link_key") == f"batch:{int(batch['id'])}"]
check("批次改价 → 应付金额同步",
      ap and abs(float(ap[0]["_amount"]) - (old_amount + float(batch["weight"]))) < 0.01,
      f"{old_amount:,.2f} → {ap[0]['_amount'] if ap else '—'}")
conn.update("batch", int(batch["id"]), {"price": float(batch["price"]),
                                       "amount": r2(float(batch["weight"]) * float(batch["price"]))})
conn.commit()
repo.sync_ap_from_batches(conn)

# ---------------- 手工补一张应付：入库批次自动认批次 / 日期 ----------------
page.tab_inv.on_new()
app.processEvents()
inv._editors["batch_code"].setText("20261108")
inv._editors["supplier"].setCurrentText("会泽五星牧场")
inv._editors["amount"].setText("1200")
inv.save_row()
app.processEvents()
manual = [r for r in calc.ap_invoices(conn, "", "") if not r.get("link_key")
          and abs(float(r.get("_amount") or 0) - 1200) < 0.01]
check("手工应付：认批次编号 → 带上入库日期与批次 id",
      manual and manual[0].get("batch_id") and manual[0].get("date") == "2026-11-08",
      f"{manual[0].get('batch_id')} / {manual[0].get('date')}" if manual else "—")

# ---------------- 自动提取的应付单不许直接删 ----------------
inv.refresh()
app.processEvents()
linked = next(r for r in rows(inv) if r.get("_kind") == "invoice" and r.get("link_key"))
n1 = len([r for r in conn.rows("ap_invoice") if r.get("link_key") == linked["link_key"]])
inv._apply_delete(linked)
app.processEvents()
n2 = len([r for r in conn.rows("ap_invoice") if r.get("link_key") == linked["link_key"]])
check("自动提取的应付单删不掉（提示改批次）", n1 == n2 == 1, f"{n1} → {n2}")

# ---------------- 手工应付：删单连带付款、撤消一起回来 ----------------
rid = int(manual[0]["id"]) if manual else 0
for day, amt in (("2026-11-10", 500.0), ("2026-11-19", 300.0)):
    conn.insert("ap_payment", {"invoice_id": rid, "date": day,
                               "supplier": "会泽五星牧场", "amount": amt})
conn.commit()
inv.refresh()
app.processEvents()
rec = next(r for r in rows(inv) if r.get("id") == rid)
kids = len([r for r in rows(inv) if r.get("_kind") == "payment" and r.get("invoice_id") == rid])
inv._apply_delete(rec)
app.processEvents()
still = [r for r in conn.rows("ap_payment") if int(r.get("invoice_id") or 0) == rid]
check("手工应付单：删单连带删付款", not still and kids == 2, f"付款 {kids} → 0")
inv.undo()
app.processEvents()
back = [r for r in rows(inv) if r.get("_kind") == "invoice"
        and not r.get("link_key") and r.get("id") != linked.get("id")]
back_kids = len([r for r in rows(inv) if r.get("_kind") == "payment"
                 and back and r.get("invoice_id") == back[0].get("id")])
check("撤消：手工单与它的两笔付款一起回来", len(back) == 1 and back_kids == 2,
      f"付款 {kids} → {back_kids}")

# ---------------- 未付款 / 账龄筛选 ----------------
opn.refresh()
app.processEvents()
check("未付款＝应付−已付",
      abs(sum(float(r.get("_unpaid") or 0) for r in opn._rows)
          - calc.ap_summary(conn, "", opn.ctx.biz_date, opn.ctx.biz_date)["unpaid"]) < 0.01,
      f"{len(opn._rows)} 笔")
check("未付款列：账龄在未付余额之后",
      [c.title for c in opn.COLS].index("账龄(天)")
      == [c.title for c in opn.COLS].index("未付款余额") + 1,
      " | ".join(c.title for c in opn.COLS))
opn.chk_aged.setChecked(True)
app.processEvents()
print("[aged only]", len(opn._rows), opn.sums.right.text())
opn.reset()

# ---------------- 多付：未付以负数列示（绿字） ----------------
inv.on_new()
app.processEvents()
inv._editors["supplier"].setCurrentText("会泽五星牧场")
inv._editors["amount"].setText("1000")
inv.save_row()
app.processEvents()
over = next(r for r in rows(inv) if r.get("_kind") == "invoice" and not r.get("link_key")
            and abs(float(r.get("_amount") or 0) - 1000) < 0.01)
inv.start_payment(over)
app.processEvents()
inv._editors["pay_amount"].setText("1300")
inv.save_row()
app.processEvents()
over = next(r for r in rows(inv) if r.get("_kind") == "invoice" and not r.get("link_key")
            and abs(float(r.get("_amount") or 0) - 1000) < 0.01)
i_over = inv._view.index(over)
c_unpaid = inv._col_index("_unpaid")
check("付多了：未付以负数（预付 / 多付）列示",
      abs(float(over.get("_unpaid") or 0) + 300) < 0.01
      and inv.table.item(i_over, c_unpaid).text() == "-300.00",
      f"未付 {over.get('_unpaid')} / 显示 {inv.table.item(i_over, c_unpaid).text()}")
fg = inv.table.item(i_over, c_unpaid).foreground().color().name().lower()
check("多付行标绿", fg == theme.NEGATIVE.lower(), fg)
check("合计条单列预付 / 多付", "预付 / 多付 300.00" in inv.sums.right.text(),
      inv.sums.right.text())
check("校验页提示多付款", any(c.item.startswith("多付款") for c in calc.checks(conn)),
      next((c.item for c in calc.checks(conn) if c.item.startswith("多付款")), "—"))
inv._apply_delete(over)         # 收尾：删掉这张，别影响后面的合计
app.processEvents()

# ---------------- 导出 ----------------
p1 = xl_export.export_payable_workbook(TMP / "应付+未付.xlsx", conn, "2026-11-01", "2026-11-20")
p2 = xl_export.export_ap_open(TMP / "未付.xlsx", conn, "2026-11-20")
check("导出 应付+未付 / 未付款", p1.stat().st_size > 3000 and p2.stat().st_size > 3000,
      f"{p1.name} / {p2.name}")

# ---------------- 采购对账单（弹窗打桩，只验出表） ----------------
class _FakeForm:
    def __init__(self, *a, **k):
        self._v = {"supplier": "会泽五星牧场", "contact": "王老板",
                   "phone": "139****2208", "as_of": "2026-11-20"}

    def exec(self):
        return QDialog.Accepted

    def values(self):
        return dict(self._v)


_orig_form = pp.FormDialog
pp.FormDialog = _FakeForm
opn.refresh()
app.processEvents()
try:
    opn.on_statement()
finally:
    pp.FormDialog = _orig_form
app.processEvents()
stmt = Path(config.EXPORT_DIR) / "采购对账单-会泽五星牧场-2026-11-20.xlsx"
check("生成采购对账单：出表落到导出报表/", stmt.exists() and stmt.stat().st_size > 4000,
      stmt.name if stmt.exists() else "未生成")
if stmt.exists():
    from openpyxl import load_workbook
    ws = load_workbook(stmt).active
    head = [ws.cell(row=4, column=i).value for i in range(1, 9)]
    col_a = [str(ws.cell(row=r, column=1).value or "") for r in range(1, ws.max_row + 1)]
    check("对账单表头 / 合计 / 结论行",
          head == ["序号", "入库批次", "商品", "应付金额(元)", "已付款金额(元)",
                   "未付款金额(元)", "账龄(天)", "备注"]
          and "合计" in col_a
          and any(x.startswith("截至") and "未付合计" in x for x in col_a),
          " | ".join(str(x) for x in head))

print("[checks]")
for c in calc.checks(conn):
    print("  ", c.label, c.item, "|", c.actual)
conn.close()
print("OK" if OK else "有断言没通过", TMP)
sys.exit(0 if OK else 1)
