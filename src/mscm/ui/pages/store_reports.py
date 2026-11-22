"""门店的两张经营报表：损益报表 / 进销存台账。

版式与口径照 store_manage_system 的门店报表，落到羊这条链路上：

    损益报表     一 产出/收入 → 二 投入/成本 → 三 产投/损益 → 六 盈利指标
                 产出 = 当日销售台账；投入 = 当日出库成本；损益 = 产出 − 投入
    进销存台账   一级明细 × 二级明细，六段「数量 / 金额」：
                 上日结余 / 当日入库 / 当日出库 / 当日结余 / 当日销售 / 当日损益

两张表都从同一个口径出发（calc.store_flow_rows）：出库不单独录，按
「上日结余 + 当日入库 − 当日结余」倒算；当天记了盘点的商品，结余取实盘
（盘亏 / 盘盈自然落进出库），没记盘点的退回账面，不会因为漏盘把出库算大。

页面锁门店（导航「门店管理 › 关一店 › …」进来即锁定）；日期只认页面抬头的
「业务日期」，筛选条里不再放日期控件，也不放「销售 / 出库 / 损益」那串汇总字——
页脚已经说清楚了，同一页同一组数字说两遍只会挤占表宽。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QLabel, QVBoxLayout, QWidget

from mscm import config
from mscm.core import calc, repo
from mscm.core.services import export as xl_export
from mscm.core.services import store_report as SR
from mscm.ui import theme
from mscm.ui.dialogs import info
from mscm.ui.widgets import (
    Card, Column, Combo, DataTable, FilterStrip, HelpPanel, PageBase,
    button, label, money, num,
)

EMPH_BG = "#F1F5FB"

HELP_PNL = (
    "<b>一 产出/收入</b>　Σ 销售台账金额，按一级明细（商品档案的类别：白条 / 分割品 / 副产品）归集<br>"
    "<b>二 投入/成本</b>　Σ 出库金额；出库 = 上日结余 + 当日入库 − 当日结余。"
    "当天记了盘点的商品，结余取实盘数，盘亏 / 盘盈就落进出库里；没记盘点的按账面结余倒算<br>"
    "<b>三 产投/损益</b>　一 − 二（3.x = 1.x − 2.x），正为益（红）、负为损（绿）<br>"
    "<b>六 盈利指标</b>　编号沿用门店日报表（本表只取产出 / 投入 / 损益与盈利指标两块，故为一 / 二 / 三 / 六）；"
    "数量列 = 数量口径，金额列 = 金额口径<br>"
    "　　（一）损益率　3.x ÷ 1.x，即损益 ÷ 收入<br>"
    "　　（二）单位收入 / 单位投入　一的金额 ÷ 数量；二的金额 ÷ 数量（元/kg）<br>"
    "　　（三）损益 ÷ 投入　三 ÷ 二<br>"
    "　　（四）单位损益　三的金额 ÷ 二的数量（元/kg）<br>"
    "<b>页脚勾稽</b>　销售台账原始单据合计 − 本表「一 产出/收入」，差异应为 0.00"
)

HELP_LEDGER = (
    "<b>上日结余</b>　截至前一日累计入库 − 累计销售（按商品），金额按累计入库加权平均价<br>"
    "<b>当日入库</b>　Σ 当日入库台账（屠宰场调拨 / 外购 / 退库；对门店就是进货）<br>"
    "<b>当日出库</b>　上日结余 + 当日入库 − 当日结余；出库不单独录，是倒算出来的<br>"
    "<b>当日结余</b>　当天记了盘点的取实盘数；没记盘点的取账面（不会因为漏盘把出库算大）<br>"
    "<b>当日销售</b>　Σ 当日销售台账（应收金额）<br>"
    "<b>当日损益</b>　当日销售 − 当日出库；正为益（红）、负为损（绿）<br>"
    "数量按 kg、金额两位千分位；「小计」行是当前筛选的合计"
)

WIDTHS = [86, 104] + [78, 92] * 6
LEADING = ("一级明细", "二级明细")
FLOW_GROUPS = ("上日结余", "当日入库", "当日出库", "当日结余", "当日销售", "当日损益")
FLOW_HEADS = ["数量(kg)", "金额"] * 6
ALL_CAT1 = "全部一级明细"
ALL_CAT2 = "全部二级明细"


class _StoreReportPage(PageBase):
    """门店报表页的公共部分：锁店、抬头、说明面板、导出路径。"""

    LEDGER = False
    TITLE = ""
    REPORT = ""

    def __init__(self, ctx, store_id: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(ctx, parent)
        self.store_id = int(store_id or 0)

    @property
    def store_label(self) -> str:
        return repo.store_name(self.ctx.conn, self.store_id) or "门店"

    @property
    def day(self) -> str:
        return self.ctx.biz_date

    def export_path(self) -> Path:
        config.ensure_dirs()
        return Path(config.EXPORT_DIR) / f"{self.REPORT}-{self.store_label}-{self.day}.xlsx"

    def _exported(self, path: Path) -> None:
        info(self, "导出完成", f"已导出到：\n{path}")


class StorePnlPage(_StoreReportPage):
    """损益报表：按一级明细的产出 / 投入 / 损益与盈利指标。"""

    TITLE = "损益报表"
    REPORT = "损益报表"

    def __init__(self, ctx, store_id: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(ctx, store_id, parent)
        self._lines: list[SR.PnlLine] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 6, 14, 8)
        root.setSpacing(8)

        strip = FilterStrip()
        self.store_tag = label(f"门店：{self.store_label}", "Muted")
        strip.add(self.store_tag)
        strip.add(label("　期间：页面抬头的业务日期（单日）", "Muted"))
        strip.add_stretch()
        strip.add(button("导出", "Gold", self.export,
                         tip="导出本店损益表（Excel 快照，版式同本页）"))
        root.addWidget(strip)

        self.help = HelpPanel(HELP_PNL)
        root.addWidget(self.help)

        self.card = Card("损益表", "口径：产出 = 销售；投入 = 出库成本；损益 = 产出 − 投入")
        self.table = DataTable([
            Column("序号", 76, "center"),
            Column("项目", 260, stretch=True),
            Column("数量", 170, "right"),
            Column("金额", 190, "right"),
        ], row_height=25)
        for c, align in ((0, Qt.AlignHCenter), (2, Qt.AlignRight), (3, Qt.AlignRight)):
            head_item = self.table.horizontalHeaderItem(c)
            if head_item is not None:
                head_item.setTextAlignment(align | Qt.AlignVCenter)
        self.card.add(self.table, 1)

        foot = QHBoxLayout()
        foot.setSpacing(12)
        self.check = QLabel("")
        self.check.setStyleSheet(f"color:{theme.MUTED};font-size:11.5px;")
        self.foot = QLabel("")
        self.foot.setStyleSheet(f"color:{theme.NAVY};font-size:12.5px;font-weight:bold;")
        foot.addWidget(self.check)
        foot.addStretch(1)
        foot.addWidget(self.foot)
        self.card.add_layout(foot)
        root.addWidget(self.card, 1)

    # ---------------------------------------------------------- 刷新
    def refresh(self) -> None:
        self.store_tag.setText(f"门店：{self.store_label}")
        rows, total = calc.store_pnl_rows(self.ctx.conn, self.store_id, self.day)
        self._lines = SR.build_lines(rows, total)

        body: list[list[str]] = []
        colors: dict[tuple[int, int], str] = {}
        bold: set[int] = set()
        bg: dict[int, str] = {}
        for i, ln in enumerate(self._lines):
            body.append([ln.no, ln.name,
                         SR.line_text(ln.qty, ln.qty_fmt),
                         SR.line_text(ln.amt, ln.amt_fmt)])
            if ln.emph:
                bold.add(i)
                bg[i] = EMPH_BG
            if ln.gain:
                for col, value in ((2, ln.qty), (3, ln.amt)):
                    if value:
                        colors[(i, col)] = theme.money_color(value)
        self.table.set_rows(body, colors=colors, bold_rows=bold, bg_rows=bg,
                            empty_text="这一天还没有销售 / 入库 / 盘点数据")

        self.card.set_hint(f"{self.store_label}　·　{self.day}　·　产出 = 销售，投入 = 出库成本")
        rate = (total.gain_amt / total.out_amt) if total.out_amt else None
        self.foot.setText(
            f"产出 {money(total.sale_amt)}　·　投入 {money(total.out_amt)}　·　"
            f"损益 {money(total.gain_amt)}　·　损益 ÷ 投入 "
            f"{'—' if rate is None else f'{rate * 100:,.1f}%'}")
        self.foot.setStyleSheet(
            f"color:{theme.money_color(total.gain_amt)};font-size:12.5px;font-weight:bold;")

        # 勾稽：销售台账原始单据 vs 本表「一 产出/收入」
        raw = calc.store_day_sale_amount(self.ctx.conn, self.store_id, self.day)
        diff = round(raw - total.sale_amt, 2)
        ok = abs(diff) < 0.01
        self.check.setText(f"勾稽：销售台账 {money(raw)} − 损益表产出 {money(total.sale_amt)} "
                           f"= 差异 {money(diff)}")
        self.check.setStyleSheet(
            f"color:{theme.SUCCESS if ok else theme.DANGER};font-size:11.5px;font-weight:bold;")

    # ---------------------------------------------------------- 导出
    def export(self) -> None:
        if not self._lines:
            self.notify("当前没有可导出的损益数据", "warn")
            return
        path = self.export_path()
        xl_export.export_store_pnl(path, self.ctx.conn, self.store_id, self.day)
        self.notify(f"已导出：{path.name}")
        self._exported(path)


class StoreLedgerPage(_StoreReportPage):
    """进销存台账：单店、单日，按商品列示收发存与损益。"""

    TITLE = "进销存台账"
    REPORT = "进销存台账"

    def __init__(self, ctx, store_id: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(ctx, store_id, parent)
        self._flows: list[calc.StoreFlow] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 6, 14, 4)
        root.setSpacing(0)

        strip = FilterStrip()
        self.store_tag = label(f"门店：{self.store_label}", "Muted")
        strip.add(self.store_tag)
        strip.add(label("一级明细", "Muted"))
        self.cat1 = Combo()
        self.cat1.setFixedWidth(128)
        strip.add(self.cat1)
        strip.add(label("二级明细", "Muted"))
        self.cat2 = Combo()
        self.cat2.setFixedWidth(140)
        strip.add(self.cat2)
        strip.add(button("重置", "", self.reset, tip="分类回到全部"))
        strip.add_stretch()
        strip.add(button("导出", "Gold", self.export, tip="导出为 Excel（按当前筛选）"))
        root.addWidget(strip)

        self.help = HelpPanel(HELP_LEDGER)
        root.addWidget(self.help)

        self.card = Card("进销存台账",
                         "口径：上日结余 + 当日入库 − 当日结余 = 当日出库；"
                         "当日损益 = 当日销售 − 当日出库")
        self.table = DataTable(
            [Column("一级明细", WIDTHS[0]), Column("二级明细", WIDTHS[1], stretch=True)]
            + [Column(title, width, "right")
               for title, width in zip(FLOW_HEADS, WIDTHS[2:])],
            row_height=26)
        self.table.set_header_groups([
            (FLOW_GROUPS[0], 2, 3), (FLOW_GROUPS[1], 4, 5), (FLOW_GROUPS[2], 6, 7),
            (FLOW_GROUPS[3], 8, 9), (FLOW_GROUPS[4], 10, 11), (FLOW_GROUPS[5], 12, 13),
        ])
        # 两行表头的台账关掉了自动铺满，让「二级明细」自己吃掉剩下的表宽
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.card.add(self.table, 1)
        root.addWidget(self.card, 1)

        self.foot = QLabel("")
        self.foot.setWordWrap(True)
        self.foot.setStyleSheet(f"color:{theme.MUTED};font-size:12px;padding:5px 2px;")
        root.addWidget(self.foot)

        self.cat1.currentIndexChanged.connect(self._on_cat1)
        self.cat2.currentIndexChanged.connect(self._render)

    # ---------------------------------------------------------- 分类下拉
    def _sync_filters(self) -> None:
        keep1 = self.cat1.currentData() if self.cat1.count() else ""
        cats: list[str] = []
        for f in self._flows:
            if f.cat1 not in cats:
                cats.append(f.cat1)
        self.cat1.blockSignals(True)
        self.cat1.clear()
        self.cat1.addItem(ALL_CAT1, "")
        for name in cats:
            self.cat1.addItem(name, name)
        self.cat1.setCurrentIndex(max(self.cat1.findData(keep1 or ""), 0))
        self.cat1.blockSignals(False)
        self._sync_cat2()

    def _sync_cat2(self) -> None:
        keep2 = self.cat2.currentData() if self.cat2.count() else ""
        cat1 = self.cat1.currentData() or ""
        names: list[str] = []
        for f in self._flows:
            if (not cat1 or f.cat1 == cat1) and f.cat2 not in names:
                names.append(f.cat2)
        self.cat2.blockSignals(True)
        self.cat2.clear()
        self.cat2.addItem(ALL_CAT2, "")
        for name in names:
            self.cat2.addItem(name, name)
        self.cat2.setCurrentIndex(max(self.cat2.findData(keep2 or ""), 0))
        self.cat2.blockSignals(False)

    def _on_cat1(self) -> None:
        self._sync_cat2()
        self._render()

    def reset(self) -> None:
        self.cat1.blockSignals(True)
        self.cat1.setCurrentIndex(0)
        self.cat1.blockSignals(False)
        self._sync_cat2()
        self._render()

    # ---------------------------------------------------------- 刷新
    def refresh(self) -> None:
        self.store_tag.setText(f"门店：{self.store_label}")
        self._flows = calc.store_flow_rows(self.ctx.conn, self.store_id, self.day)
        self._sync_filters()
        self._render()

    def filtered(self) -> list[calc.StoreFlow]:
        cat1 = self.cat1.currentData() or ""
        cat2 = self.cat2.currentData() or ""
        return [f for f in self._flows
                if (not cat1 or f.cat1 == cat1) and (not cat2 or f.cat2 == cat2)]

    def _render(self) -> None:
        rows = self.filtered()
        total = calc.store_flow_total(rows)

        body: list[list[str]] = []
        colors: dict[tuple[int, int], str] = {}
        for f in rows:
            body.append([
                f.cat1, f.cat2,
                num(f.open_qty), money(f.open_amt), num(f.in_qty), money(f.in_amt),
                num(f.out_qty), money(f.out_amt), num(f.close_qty), money(f.close_amt),
                num(f.sale_qty), money(f.sale_amt),
                num(f.gain_qty), money(f.gain_amt),
            ])
            i = len(body) - 1
            if f.gain_amt:
                colors[(i, 13)] = theme.money_color(f.gain_amt)
            if f.gain_qty:
                colors[(i, 12)] = theme.money_color(f.gain_qty)
            if f.close_qty < 0:
                colors[(i, 8)] = theme.DANGER
            if f.out_qty < 0:
                colors[(i, 6)] = theme.WARN

        if rows:
            body.append(["小计", "",
                         num(total.open_qty), money(total.open_amt),
                         num(total.in_qty), money(total.in_amt),
                         num(total.out_qty), money(total.out_amt),
                         num(total.close_qty), money(total.close_amt),
                         num(total.sale_qty), money(total.sale_amt),
                         num(total.gain_qty), money(total.gain_amt)])
            total_row = len(body) - 1
            bold = {total_row}
            bg = {total_row: EMPH_BG}
            if total.gain_amt:
                colors[(total_row, 13)] = theme.money_color(total.gain_amt)
            if total.gain_qty:
                colors[(total_row, 12)] = theme.money_color(total.gain_qty)
        else:
            bold, bg = set(), {}

        self.table.set_rows(body, colors=colors, bold_rows=bold, bg_rows=bg,
                            empty_text="这一天没有可列的进销存（先记入库 / 销售 / 盘点）")

        counted = sum(1 for f in rows if f.counted)
        diff = round(total.open_qty + total.in_qty - total.out_qty - total.close_qty, 2)
        # 结余取实盘的行：实盘 − 账面（正为盘盈、负为盘亏，已随出库计入成本）
        stock_diff = round(sum(
            f.close_qty - (f.open_qty + f.in_qty - f.sale_qty) for f in rows if f.counted), 2)
        self.foot.setText(
            f"勾稽：上日结余 {num(total.open_qty)} + 入库 {num(total.in_qty)} − "
            f"出库 {num(total.out_qty)} − 结余 {num(total.close_qty)} = {num(diff)} kg"
            f"　·　销售 {money(total.sale_amt)} − 出库成本 {money(total.out_amt)} = "
            f"损益 {money(total.gain_amt)} 元"
            f"　·　实盘商品 {counted} 个，盘点差异 {stock_diff:+,.1f} kg（正盘盈 / 负盘亏，已计入出库）")
        self.foot.setStyleSheet(
            f"color:{theme.SUCCESS if abs(diff) < 0.05 else theme.DANGER};"
            f"font-size:12px;padding:5px 2px;")

    # ---------------------------------------------------------- 导出
    def export(self) -> None:
        rows = self.filtered()
        if not rows:
            self.notify("当前筛选没有台账数据", "warn")
            return
        path = self.export_path()
        xl_export.export_store_ledger(
            path, self.ctx.conn, self.store_id, self.day,
            str(self.cat1.currentData() or ""), str(self.cat2.currentData() or ""))
        self.notify(f"已导出：{path.name}")
        self._exported(path)
