"""屠宰记录：一张屠宰单（领入）+ 多条屠宰产出明细。

版式与其它台账不同：这不是「一行一条账」，而是「单据 + 分录」。
上面看单据（领入只数、毛重、产出合计、出肉率、领用成本），下面看选中单据的
产出明细（白条、羊排、羊腿、羊蝎子、羊杂、羊皮……）。新增/编辑走对话框，
在一个窗口里把头和明细一起改完，避免两张表各改一半。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QHBoxLayout, QMenu, QVBoxLayout, QWidget

from mscm import config
from mscm.core import calc, repo
from mscm.core.models import month_start
from mscm.core.services import export as xl_export
from mscm.ui import theme
from mscm.ui.dialogs import SlaughterDialog, confirm, info
from mscm.ui.pages.base_ledger import ROW_BTN_QSS
from mscm.ui.widgets import (
    Card,
    Column,
    Combo,
    DataTable,
    DateEdit,
    FilterStrip,
    HelpPanel,
    PageBase,
    SumBar,
    button,
    money,
    num,
    pct,
    search_input,
)

HELP = (
    "<b>这张表记什么</b>　每宰一批羊记一张单：领进去多少只、多少 kg，产出了哪些商品、各多少 kg，"
    "一张单带多条产出明细。<br>"
    "<b>出肉率</b>　= 产出合计 kg ÷ 领入毛重 kg。整羊一般 35%~55%，超出这个区间系统会提示核对。<br>"
    "<b>领用成本</b>　= 领入毛重 × 该批次暂养累计入库的加权平均单价；"
    "<b>单位成本</b>　= 领用成本 ÷ 产出合计 kg，用来给门店调拨与直销定价打底。<br>"
    "<b>产出金额</b>　按产出明细的单价计价（内部计价口径），不是最终销售额；"
    "真正卖出去的钱在「屠宰出库明细」里。<br>"
    "<b>怎么改</b>　双击单据行 → 在一个窗口里改头改明细；明细可以加行、删行，"
    "金额 = kg × 单价 自动算。"
)

DOC_COLS = [
    Column("屠宰单号", 124),
    Column("日期", 98, "center"),
    Column("羊群批次", 116),
    Column("品类", 68, "center"),
    Column("领入(只)", 64, "right"),
    Column("领入毛重(kg)", 92, "right"),
    Column("产出项数", 72, "center"),
    Column("产出(kg)", 78, "right"),
    Column("出肉率", 66, "right"),
    Column("领用成本", 92, "right"),
    Column("单位成本", 80, "right"),
    Column("标识", 98),
    Column("屠宰人", 70, "center"),
    Column("操作", 106, "center"),
]

LINE_COLS = [
    Column("产出类别", 140, stretch=True),
    Column("数量(只)", 90, "right"),
    Column("数量(kg)", 100, "right"),
    Column("单价(元/kg)", 110, "right"),
    Column("金额", 110, "right"),
]


class SlaughterPage(PageBase):
    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(ctx, parent)
        self._docs: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 6, 14, 4)
        root.setSpacing(0)

        strip = FilterStrip()
        self.d_from = DateEdit()
        self.d_to = DateEdit()
        for w in (self.d_from, self.d_to):
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd")
            w.setFixedWidth(128)
            d = QDate.fromString(ctx.biz_date, "yyyy-MM-dd")
            w.setDate(d if d.isValid() else QDate.currentDate())
        first = QDate.fromString(month_start(ctx.biz_date), "yyyy-MM-dd")
        if first.isValid():
            self.d_from.setDate(first)
        self.f_batch = Combo()
        self.f_batch.setFixedWidth(180)
        self.f_kw = search_input("单号 / 标识 / 屠宰人…", 168)

        strip.add_label("业务期间")
        strip.add(self.d_from)
        strip.add_label("至")
        strip.add(self.d_to)
        strip.add(button("当日", "", self.range_today))
        strip.add(button("本月", "", self.range_month))
        strip.add(self.f_batch)
        strip.add(self.f_kw)
        strip.add(button("重置", "", self.reset))
        strip.add_stretch()
        strip.add(button("导出", "", self.on_export, tip="导出屠宰记录（单 + 产出明细）"))
        strip.add(button("＋ 新增屠宰单", "Primary", self.on_new))
        root.addWidget(strip)

        self.help = HelpPanel(HELP)
        root.addWidget(self.help)

        self.card = Card("屠宰记录（单据）", "")
        self.table = DataTable(DOC_COLS, row_height=30)
        self.table.doubleClicked.connect(lambda *_: self.on_edit())
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._row_menu)
        self.card.add(self.table, 3)
        self.sums = SumBar(self.table)
        self.card.add(self.sums)
        root.addWidget(self.card, 3)

        self.line_card = Card("产出明细", "")
        self.line_table = DataTable(LINE_COLS, row_height=28)
        self.line_card.add(self.line_table, 1)
        self.line_sums = SumBar(self.line_table)
        self.line_card.add(self.line_sums)
        root.addWidget(self.line_card, 2)

        self.d_from.dateChanged.connect(self.refresh)
        self.d_to.dateChanged.connect(self._on_to_changed)
        self.f_batch.currentIndexChanged.connect(self.refresh)
        self.f_kw.textChanged.connect(self.refresh)
        ctx.biz_date_changed.connect(self._on_biz_date)

        self._fill_filters()
        self.refresh()

    # ---------------------------------------------------------- 筛选
    def _fill_filters(self) -> None:
        keep = self.f_batch.currentData() if self.f_batch.count() else 0
        self.f_batch.blockSignals(True)
        self.f_batch.clear()
        self.f_batch.addItem("全部批次", 0)
        for text, bid in repo.batch_options(self.ctx.conn):
            self.f_batch.addItem(text, bid)
        idx = self.f_batch.findData(keep or 0)
        self.f_batch.setCurrentIndex(idx if idx >= 0 else 0)
        self.f_batch.blockSignals(False)

    @property
    def d1(self) -> str:
        return self.d_from.date().toString("yyyy-MM-dd")

    @property
    def d2(self) -> str:
        return self.d_to.date().toString("yyyy-MM-dd")

    @property
    def batch_id(self) -> int:
        return int(self.f_batch.currentData() or 0)

    def range_today(self) -> None:
        self._set_range(self.ctx.biz_date, self.ctx.biz_date)

    def range_month(self) -> None:
        d = QDate.fromString(self.ctx.biz_date, "yyyy-MM-dd")
        if d.isValid():
            self._set_range(d.toString("yyyy-MM-01"), self.ctx.biz_date)

    def _set_range(self, start: str, end: str) -> None:
        for w, value in ((self.d_from, start), (self.d_to, end)):
            d = QDate.fromString(value, "yyyy-MM-dd")
            if d.isValid():
                w.blockSignals(True)
                w.setDate(d)
                w.blockSignals(False)
        self.refresh()

    def reset(self) -> None:
        d = QDate.fromString(self.ctx.biz_date, "yyyy-MM-dd")
        for w in (self.d_from, self.d_to):
            w.blockSignals(True)
            if d.isValid():
                w.setDate(d)
            w.blockSignals(False)
        self.f_kw.blockSignals(True)
        self.f_kw.clear()
        self.f_kw.blockSignals(False)
        self.f_batch.blockSignals(True)
        self.f_batch.setCurrentIndex(0)
        self.f_batch.blockSignals(False)
        self.refresh()

    def _on_biz_date(self, day: str) -> None:
        """抬头改了业务日期：筛选区间跟着跳到「该月 1 日 → 该日」。

        不能把起始日也设成同一天——那样区间会塌成一天，台账看着像空了。
        """
        d = QDate.fromString(day, "yyyy-MM-dd")
        if not d.isValid():
            return
        first = QDate(d.year(), d.month(), 1)
        for w, value in ((self.d_from, first), (self.d_to, d)):
            w.blockSignals(True)
            w.setDate(value)
            w.blockSignals(False)
        self.refresh()

    def _on_to_changed(self) -> None:
        self.refresh()
        self.ctx.set_biz_date(self.d2)

    # ---------------------------------------------------------- 渲染
    def refresh(self) -> None:
        self._docs = calc.slaughter_docs(self.ctx.conn, self.d1, self.d2,
                                         self.batch_id, self.f_kw.text().strip())
        body, colors = [], {}
        for i, d in enumerate(self._docs):
            body.append([
                d.get("doc_no") or "", d.get("date") or "", d.get("_batch_code") or "",
                d.get("category") or "", num(d.get("in_count"), 0),
                num(d.get("in_weight"), 1), num(d.get("_line_count"), 0),
                num(d.get("_out_weight"), 1), pct(d.get("_yield_rate")),
                money(d.get("_in_cost")), money(d.get("_unit_cost")),
                d.get("tag") or "", d.get("operator") or "", "",
            ])
            if d.get("_yield_rate") and not (0.30 <= d["_yield_rate"] <= 0.65):
                colors[(i, 8)] = theme.WARN
        self.table.set_rows(body, self._docs, colors=colors,
                            empty_text="本期还没有屠宰单：点右上「＋ 新增屠宰单」")
        for i, doc in enumerate(self._docs):
            self.table.setRowHeight(i, 30)
            self._set_ops(i, doc)
        self.card.set_hint(f"{self.d1} 至 {self.d2}")
        total_in = sum(float(d.get("in_count") or 0) for d in self._docs)
        total_w = sum(float(d.get("in_weight") or 0) for d in self._docs)
        total_out = sum(float(d.get("_out_weight") or 0) for d in self._docs)
        self.sums.set_text(f"共 {len(self._docs)} 张单",
                           f"领入 {total_in:,.0f} 只 / {total_w:,.1f} kg　·　"
                           f"产出 {total_out:,.1f} kg　·　"
                           f"综合出肉率 {pct(total_out / total_w if total_w else 0)}")
        # 默认选中第一张单：下半屏不至于一片空白，顺手就能看产出明细
        if self._docs and self.table.currentRow() < 0:
            self.table.blockSignals(True)
            self.table.selectRow(0)
            self.table.blockSignals(False)
        self._refresh_lines()

    def _set_ops(self, row: int, doc: dict) -> None:
        box = QWidget()
        box.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(1)
        lay.addStretch(1)
        b_edit = button("编辑", "", lambda _c=False, r=row: self._edit_row(r))
        b_del = button("删除", "", lambda _c=False, r=row: self._delete_row(r))
        b_del.setObjectName("RowDel")
        for b in (b_edit, b_del):
            b.setFixedHeight(20)
            b.setFixedWidth(42)
            b.setStyleSheet(ROW_BTN_QSS)
            b.setCursor(Qt.PointingHandCursor)
            lay.addWidget(b)
        lay.addStretch(1)
        b_edit.setToolTip("打开屠宰单，改领入与产出明细（也可双击本行）")
        b_del.setToolTip("删掉这张屠宰单，连同它的产出明细")
        self.table.setCellWidget(row, len(DOC_COLS) - 1, box)

    def _row_menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= len(self._docs):
            return
        self.table.selectRow(row)
        menu = QMenu(self)
        act_edit = menu.addAction("编辑这张屠宰单")
        act_del = menu.addAction("删除这张屠宰单")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is act_edit:
            self._edit_row(row)
        elif chosen is act_del:
            self._delete_row(row)

    def _current_doc(self) -> dict | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._docs):
            return self._docs[row]
        return None

    def _on_select(self) -> None:
        self._refresh_lines()

    def _refresh_lines(self) -> None:
        doc = self._current_doc()
        if doc is None:
            self.line_table.set_rows([], [], empty_text="选中上面一张屠宰单，这里看它的产出明细")
            self.line_sums.set_text("", "")
            self.line_card.set_hint("")
            return
        lines = calc.yield_lines(self.ctx.conn, int(doc.get("id") or 0))
        body = [[ln.get("product") or "", num(ln.get("count"), 0),
                 num(ln.get("weight"), 1), money(ln.get("price")), money(ln.get("_amount"))]
                for ln in lines]
        self.line_table.set_rows(body, lines)
        for i in range(len(lines)):
            self.line_table.setRowHeight(i, 28)
        self.line_card.set_hint(f"{doc.get('doc_no')}　·　{doc.get('_batch_code')}　·　"
                                f"出肉率 {pct(doc.get('_yield_rate'))}")
        kg = sum(float(ln.get("weight") or 0) for ln in lines)
        amt = sum(float(ln.get("_amount") or 0) for ln in lines)
        self.line_sums.set_text(f"共 {len(lines)} 个产出类别",
                                f"合计 {kg:,.1f} kg　·　{money(amt)} 元")

    # ---------------------------------------------------------- 增删改
    def on_new(self) -> None:
        values = {
            "date": self.ctx.biz_date,
            "doc_no": repo.next_doc_no(self.ctx.conn, self.ctx.biz_date),
            "batch_id": self.batch_id,
            "category": repo.batch_category(self.ctx.conn, self.batch_id),
        }
        dlg = SlaughterDialog(self.ctx, self.ctx.conn, values=values, lines=[], parent=self)
        if dlg.exec() != SlaughterDialog.Accepted:
            return
        data = dict(dlg.result_values)
        if not data.get("doc_no"):
            data["doc_no"] = repo.next_doc_no(self.ctx.conn, data["date"])
        repo.save_slaughter(self.ctx.conn, data, dlg.result_lines)
        self._fill_filters()
        self.refresh()
        self.ctx.changed()
        self.notify(f"已新增屠宰单 {data['doc_no']}（{len(dlg.result_lines)} 行产出）")

    def _edit_row(self, row: int) -> None:
        if not (0 <= row < len(self._docs)):
            return
        doc = self._docs[row]
        lines = calc.yield_lines(self.ctx.conn, int(doc.get("id") or 0))
        dlg = SlaughterDialog(self.ctx, self.ctx.conn, values=doc, lines=lines, parent=self)
        if dlg.exec() != SlaughterDialog.Accepted:
            return
        repo.save_slaughter(self.ctx.conn, dlg.result_values, dlg.result_lines,
                            int(doc.get("id") or 0))
        self.refresh()
        self.ctx.changed()
        self.notify(f"已保存屠宰单 {doc.get('doc_no')}")

    def on_edit(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self._edit_row(row)

    def _delete_row(self, row: int) -> None:
        if not (0 <= row < len(self._docs)):
            return
        doc = self._docs[row]
        if not confirm(self, "删除确认",
                       f"确定删除屠宰单 {doc.get('doc_no')} 吗？\n"
                       f"它的 {doc.get('_line_count')} 行产出明细会一起删掉。", danger=True):
            return
        repo.delete_slaughter(self.ctx.conn, int(doc.get("id") or 0))
        self.refresh()
        self.ctx.changed()
        self.notify("已删除屠宰单及产出明细")

    # ---------------------------------------------------------- 导出
    def on_export(self) -> None:
        if not self._docs:
            self.notify("当前筛选没有可导出的数据", "warn")
            return
        config.ensure_dirs()
        path = Path(config.EXPORT_DIR) / f"屠宰记录-{self.d1}_{self.d2}.xlsx"
        xl_export.export_module(path, "slaughter", self.ctx.conn, self.d1, self.d2,
                                batch_id=self.batch_id)
        self.notify(f"已导出：{path.name}")
        info(self, "导出完成", f"已导出到：\n{path}")
