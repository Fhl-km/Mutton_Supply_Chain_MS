"""概览：一天的经营 + 全盘结存 + 门店库存。"""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from mscm.core import calc
from mscm.core.models import month_start
from mscm.ui import theme
from mscm.ui.widgets import Card, Column, DataTable, PageBase, StatCard, money, num, pct

BATCH_COLS = [
    Column("羊群批次", 118),
    Column("品类", 66, "center"),
    Column("结存(只)", 78, "right"),
    Column("结存(kg)", 86, "right"),
    Column("结存金额", 102, "right"),
    Column("结存均价", 84, "right", stretch=True),
]

STOCK_COLS = [
    Column("门店", 92),
    Column("批次", 110),
    Column("商品", 100),
    Column("账面库存(kg)", 104, "right"),
    Column("库存金额", 100, "right"),
    Column("均价", 82, "right", stretch=True),
]


class DashboardPage(PageBase):
    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(ctx, parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 8, 14, 6)
        root.setSpacing(8)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.cards: dict[str, StatCard] = {}
        specs = [
            ("pen_count", "暂养存栏", "只", theme.NAVY_2, "各批次暂养圈现存只数"),
            ("pen_weight", "暂养结存", "kg", theme.NAVY_2, "入库 kg − 出库 kg"),
            ("pen_amount", "暂养库存金额", "元", theme.GOLD, "按批次加权平均单价结存"),
            ("store_stock", "门店账面库存", "kg", theme.NAVY_LIGHT, "入库 − 销售，全部门店"),
            ("month_slaughter", "本月屠宰领入", "只", theme.NAVY_2, "本月屠宰单领入只数"),
            ("month_sale", "本月门店销售", "元", theme.GOLD, "按应收金额统计"),
            ("month_unpaid", "本月未收金额", "元", theme.DANGER, "应收 − 实收，含挂账"),
            ("month_yield", "本月综合出肉率", "%", theme.SUCCESS, "产出 kg ÷ 领入毛重 kg"),
        ]
        for i, (key, label, unit, accent, hint) in enumerate(specs):
            card = StatCard(label, unit, accent, hint)
            self.cards[key] = card
            grid.addWidget(card, i // 4, i % 4)
        root.addLayout(grid)

        body = QHBoxLayout()
        body.setSpacing(10)

        self.batch_card = Card("批次结存（暂养台账口径）", "")
        self.batch_table = DataTable(BATCH_COLS, row_height=28)
        self.batch_card.add(self.batch_table, 1)
        body.addWidget(self.batch_card, 5)

        self.stock_card = Card("门店账面库存（入库 − 销售）", "")
        self.stock_table = DataTable(STOCK_COLS, row_height=28)
        self.stock_card.add(self.stock_table, 1)
        body.addWidget(self.stock_card, 6)
        root.addLayout(body, 1)

        self.foot_card = Card("本月经营（简化口径）",
                              "收入只算真正卖出去的：门店销售 + 屠宰直销；内部调拨不重复计收入")
        foot_lay = QHBoxLayout()
        foot_lay.setSpacing(28)
        self.foot_values: dict[str, QLabel] = {}
        for key, text in (("revenue", "收入"), ("cost", "成本"),
                          ("gross", "毛利"), ("rate", "毛利率")):
            box = QVBoxLayout()
            box.setSpacing(0)
            cap = QLabel(text)
            cap.setStyleSheet(f"color:{theme.MUTED};font-size:11.5px;")
            val = QLabel("—")
            val.setStyleSheet(f"color:{theme.NAVY};font-size:18px;font-weight:bold;")
            box.addWidget(cap)
            box.addWidget(val)
            foot_lay.addLayout(box)
            self.foot_values[key] = val
        foot_lay.addStretch(1)
        self.foot_card.add_layout(foot_lay)
        root.addWidget(self.foot_card)

    def refresh(self) -> None:
        day = self.ctx.biz_date
        s = calc.dashboard_stats(self.ctx.conn, day)
        self.cards["pen_count"].set_value(num(s["pen_count"], 0), f"养殖存栏 {num(s['breed_stock'], 0)} 只")
        self.cards["pen_weight"].set_value(num(s["pen_weight"], 1), f"结存金额 {money(s['pen_amount'])} 元")
        self.cards["pen_amount"].set_value(money(s["pen_amount"]), f"截至 {day}")
        self.cards["store_stock"].set_value(num(s["store_stock_weight"], 1),
                                            f"库存金额 {money(s['store_stock_amount'])} 元")
        self.cards["month_slaughter"].set_value(num(s["month_in_count"], 0),
                                                f"{s['month_slaughter']} 张屠宰单 · 产出 "
                                                f"{num(s['month_yield_weight'], 1)} kg")
        self.cards["month_sale"].set_value(money(s["month_sale"]),
                                           f"屠宰直销 {money(s['month_out'])} 元")
        self.cards["month_unpaid"].set_value(money(s["month_unpaid"]),
                                             "对账跟进：客户挂账", theme.DANGER)
        self.cards["month_yield"].set_value(pct(s["month_yield_rate"]),
                                            f"本月 {month_start(day)} 起算")

        balances = calc.batch_balances(self.ctx.conn, day)
        body = [[b.batch_code, b.category, num(b.count, 0), num(b.weight, 1),
                 money(b.amount), money(b.avg_price)] for b in balances]
        red = {i: theme.DANGER for i, b in enumerate(balances) if b.count < 0 or b.weight < 0}
        self.batch_table.set_rows(body, balances, row_colors=red,
                                  empty_text="还没有批次结存：先在「屠宰场暂养出入库台账」登记入库")
        for i in range(len(body)):
            self.batch_table.setRowHeight(i, 28)
        self.batch_card.set_hint(f"{len(balances)} 个批次　·　存栏 {num(s['pen_count'], 0)} 只 / "
                                 f"{num(s['pen_weight'], 1)} kg")

        book = calc.store_book_stock(self.ctx.conn, 0, day)
        sbody = [[r.store_name, r.batch_code or "—", r.product,
                  num(r.weight, 1), money(r.amount), money(r.avg_price)] for r in book]
        self.stock_table.set_rows(sbody, book,
                                  row_colors={i: theme.DANGER for i, r in enumerate(book)
                                              if r.weight < 0},
                                  empty_text="门店还没有入库记录")
        for i in range(len(sbody)):
            self.stock_table.setRowHeight(i, 28)
        self.stock_card.set_hint(f"入库 {num(sum(r.in_weight for r in book), 1)} kg　·　"
                                 f"销售 {num(sum(r.sale_weight for r in book), 1)} kg")

        gross, revenue, cost = _gross(self.ctx.conn, day)
        rate = (gross / revenue) if revenue else 0.0
        self.foot_values["revenue"].setText(f"{money(revenue)} 元")
        self.foot_values["cost"].setText(f"{money(cost)} 元")
        self.foot_values["gross"].setText(f"{money(gross)} 元")
        self.foot_values["gross"].setStyleSheet(
            f"color:{theme.money_color(gross)};font-size:18px;font-weight:bold;")
        self.foot_values["rate"].setText(f"{rate * 100:,.1f}%")
        self.foot_values["rate"].setStyleSheet(
            f"color:{theme.money_color(gross)};font-size:18px;font-weight:bold;")


def _gross(conn, day: str) -> tuple[float, float, float]:
    """简化毛利：只算真正卖出去的（门店销售 + 屠宰直销），调拨不算收入。

    - 门店销售成本 = 销售 kg × 门店累计入库均价
    - 屠宰直销成本 = 出库 kg × 屠宰单单位成本（期间加权）
    """
    m1 = month_start(day)
    ins = calc.store_in_rows(conn, 0, "", day)
    in_w = sum(float(r.get("weight") or 0) for r in ins)
    in_a = sum(float(r.get("_amount") or 0) for r in ins)
    store_price = (in_a / in_w) if in_w else 0.0

    sales = calc.store_sale_rows(conn, 0, m1, day)
    revenue_s = sum(float(r.get("_due") or 0) for r in sales)
    cost_s = sum(float(r.get("weight") or 0) for r in sales) * store_price

    docs = calc.slaughter_docs(conn, m1, day)
    out_w = sum(float(d.get("_out_weight") or 0) for d in docs)
    in_cost = sum(float(d.get("_in_cost") or 0) for d in docs)
    sla_cost = (in_cost / out_w) if out_w else 0.0

    outs = [r for r in calc.slaughter_out_rows(conn, m1, day) if r.get("target") != "门店调拨"]
    revenue_o = sum(float(r.get("_amount") or 0) for r in outs)
    cost_o = sum(float(r.get("weight") or 0) for r in outs) * sla_cost

    revenue = revenue_s + revenue_o
    cost = cost_s + cost_o
    return round(revenue - cost, 2), round(revenue, 2), round(cost, 2)
