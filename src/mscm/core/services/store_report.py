"""门店损益报表的行结构：页面与 Excel 共用一套，避免两处各排一遍。

版式照 store_manage_system 门店「损益报表」：表身只有「序号 / 项目 / 数量 / 金额」，
纵向项目表：

    一    产出/收入                ← 1.x 各一级明细（白条 / 分割品 / 副产品）
    二    投入/成本                ← 2.x 各一级明细
    三    产投/损益                ← 3.x = 1.x − 2.x，正为益（红）、负为损（绿）
    六    盈利指标
          （一）损益率             ← 6.1.x 数量口径 / 金额口径 = 3.x ÷ 1.x
          （二）单位收入 / 单位投入 ← 6.2.1 / 6.2.2 = 金额 ÷ 数量（元/kg）
          （三）损益 / 投入         ← 6.3.1 = 三 ÷ 二
          （四）单位损益           ← 6.3.2 起，各一级明细 = 三的金额 ÷ 二的数量（元/kg）

口径与「进销存台账」同源（calc.store_flow_rows）：
    产出 = 当日销售台账金额；投入 = 当日出库成本（出库 = 上日结余 + 入库 − 结余）；
    损益 = 产出 − 投入。每行怎么算不占表体，收在页面「填写说明」里，导出时写在表头上方。
"""

from __future__ import annotations

from dataclasses import dataclass

from mscm import config
from mscm.core.models import StorePnl

QTY_FMT = config.QTY_FMT
MONEY_FMT = config.MONEY_FMT
PCT_FMT = config.PCT_FMT

HEADERS = ["序号", "项目", "数量", "金额"]

NOTES: tuple[tuple[str, str], ...] = (
    ("一 产出/收入", "Σ 销售台账金额，按一级明细（商品档案的类别）归集"),
    ("二 投入/成本", "Σ 出库金额；出库 = 上日结余 + 当日入库 − 当日结余，当天有盘点的按实盘结余倒算"),
    ("三 产投/损益", "一 − 二（3.x = 1.x − 2.x），正为益、负为损"),
    ("六 盈利指标", "编号沿用门店日报表（本表只取产出 / 投入 / 损益与盈利指标两块，故为一 / 二 / 三 / 六）；"
                    "数量列 = 数量口径、金额列 = 金额口径；6.1.x = 3.x ÷ 1.x；"
                    "6.2.x = 金额 ÷ 数量；6.3.1 = 三 ÷ 二；6.3.2 起 = 三的金额 ÷ 二的数量（元/kg）"),
)


@dataclass
class PnlLine:
    """报表一行：渲染文字与导出数值共用，fmt 决定怎么写。"""

    no: str
    name: str
    qty: float | None = None
    amt: float | None = None
    qty_fmt: str | None = QTY_FMT
    amt_fmt: str | None = MONEY_FMT
    gain: bool = False             # 损益类数字：正红负绿
    emph: bool = False             # 计算项：加粗 + 浅底


def line_text(value: float | None, fmt: str | None) -> str:
    if value is None:
        return "—"
    if fmt == PCT_FMT:
        return f"{value * 100:,.2f}%"
    if fmt == MONEY_FMT:
        return f"{value:,.2f}"
    if fmt == QTY_FMT:
        return f"{value:,.1f}"
    return f"{value:,.2f}"


def line_number(value: float | None, fmt: str | None) -> float | None:
    if value is None:
        return None
    return round(value, 6) if fmt == PCT_FMT else round(value, 2)


def _ratio(num: float, den: float) -> float | None:
    return (num / den) if den else None


def build_lines(rows: list[StorePnl], total: StorePnl) -> list[PnlLine]:
    lines: list[PnlLine] = []

    # 一 产出 / 收入
    lines.append(PnlLine("一", "产出/收入", total.sale_qty, total.sale_amt, emph=True))
    for i, p in enumerate(rows, start=1):
        lines.append(PnlLine(f"1.{i}", p.cat1, p.sale_qty, p.sale_amt))

    # 二 投入 / 成本
    lines.append(PnlLine("二", "投入/成本", total.out_qty, total.out_amt, emph=True))
    for i, p in enumerate(rows, start=1):
        lines.append(PnlLine(f"2.{i}", p.cat1, p.out_qty, p.out_amt))

    # 三 产投 / 损益
    lines.append(PnlLine("三", "产投/损益", total.gain_qty, total.gain_amt,
                         gain=True, emph=True))
    for i, p in enumerate(rows, start=1):
        lines.append(PnlLine(f"3.{i}", p.cat1, p.gain_qty, p.gain_amt, gain=True))

    # 六 盈利指标
    lines.append(PnlLine("六", "盈利指标", None, None, emph=True))

    lines.append(PnlLine("（一）", "损益率（损益 ÷ 收入）", None, None, emph=True))
    for i, p in enumerate(rows, start=1):
        lines.append(PnlLine(f"6.1.{i}", p.cat1,
                             _ratio(p.gain_qty, p.sale_qty),
                             _ratio(p.gain_amt, p.sale_amt),
                             qty_fmt=PCT_FMT, amt_fmt=PCT_FMT, gain=True))

    lines.append(PnlLine("（二）", "单位收入 / 单位投入", None, None, emph=True))
    lines.append(PnlLine("6.2.1", "单位收入（元/kg）", None,
                         _ratio(total.sale_amt, total.sale_qty), qty_fmt=None))
    lines.append(PnlLine("6.2.2", "单位投入（元/kg）", None,
                         _ratio(total.out_amt, total.out_qty), qty_fmt=None))

    lines.append(PnlLine("（三）", "损益 / 投入", None, None, emph=True))
    lines.append(PnlLine("6.3.1", "损益 ÷ 投入",
                         _ratio(total.gain_qty, total.out_qty),
                         _ratio(total.gain_amt, total.out_amt),
                         qty_fmt=PCT_FMT, amt_fmt=PCT_FMT, gain=True))

    lines.append(PnlLine("（四）", "单位损益", None, None, emph=True))
    for i, p in enumerate(rows, start=2):
        lines.append(PnlLine(f"6.3.{i}", f"{p.cat1}（元/kg）", None,
                             _ratio(p.gain_amt, p.out_qty), qty_fmt=None, gain=True))
    return lines
