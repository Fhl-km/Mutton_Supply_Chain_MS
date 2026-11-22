"""出表：按《账表记录-羊.xlsx》的七张台账版式导出整套 / 单张 Excel。

版式对齐用户给的模板：
    第 1 行  标题（合并居中）
    第 2 行  羊群批次 / 暂养圈编号 / 门店名称 / 日期（左右分列）
    第 3-4 行 表头（入库/出库/屠宰产出/投料情况 两层分组）
    第 4 行起 数据
    表格下方 注（模板原文的填写说明）
"""

from __future__ import annotations

from pathlib import Path

from copy import copy

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from mscm import config
from mscm.core import calc
from mscm.core.models import AR_BIZ_SLAUGHTER, SETTLE_METHODS, r1, r2, T_STORE
from mscm.core.services import store_report as SR
from mscm.core.services import xl_style as X

NOTE_BATCH = "注：该台账以批次为基本单位，1个批次1份台账，不得不同批次混淆填列。"
NOTE_SALE = ("注：①门店所有销售都必须登记该明细账，包括对外赠送商品；"
             "②门店现场现收款零售散客户不开具《销售货单》，但必须登记该明细，明细可不用填写客户信息；"
             "③门店现场非现收销售、配送、挂账的行为必须开具《销货单》，注明客户信息（联系人、联系电话、地址），"
             "并经客户签字确认。")
NOTE_SOUT = ("注：①屠宰场所有出库必须登记「出库（销售/内部调拨）明细账」；"
             "②屠宰场直接对外销售的必须开具《销售货单》，注明客户信息（联系人、联系电话、地址等），并经客户签字确认；"
             "③屠宰场内部调拨至门店的需开具《屠宰场出库单》，需经门店收货员签收确认商品名称和数量。")

QTY, MONEY, PRICE, INT, PCT = (config.QTY_FMT, config.MONEY_FMT, config.PRICE_FMT,
                               config.INT_FMT, config.PCT_FMT)


# ---------------------------------------------------------------- 表头定义
G_FEED = [("日期", 1), ("羊群批次", 1), ("圈号", 1), ("羊群品类", 1), ("入库", 6), ("出库", 4), ("结余", 3)]
H_FEED = ["日期", "羊群批次", "圈号", "羊群品类", "供应商", "标识", "数量\n(只)", "数量\n(kg)",
          "平均单价\n(元/kg)", "金额",
          "用途", "数量\n(只)", "数量\n(kg)", "金额", "数量\n(只)", "数量\n(kg)", "金额"]
F_FEED = [None, None, None, None, None, None, INT, QTY, PRICE, MONEY, None, INT, QTY, MONEY, INT, QTY, MONEY]
W_FEED = [11, 12, 6, 10, 19, 13, 7, 9, 11, 12, 10, 7, 9, 11, 8, 9, 11]

G_BREED = [("日期", 1), ("品类", 1), ("标识", 1), ("期初存栏\n数量(只)", 1), ("出栏\n数量(只)", 1),
           ("期末存栏\n数量(只)", 1), ("出栏用途", 1), ("投料情况", 5), ("记录人", 1)]
H_BREED = ["日期", "品类", "标识", "期初存栏\n数量(只)", "出栏\n数量(只)", "期末存栏\n数量(只)", "出栏用途",
           "原材料名称", "单位", "数量", "单价", "金额", "记录人"]
F_BREED = [None, None, None, INT, INT, INT, None, None, None, QTY, PRICE, MONEY, None]
W_BREED = [11, 13, 7, 11, 9, 11, 12, 14, 7, 9, 9, 11, 9]

G_SLA = [("日期", 1), ("羊群批次", 1), ("品类", 1), ("领入\n数量(只)", 1), ("标识", 1),
         ("屠宰产出", 3), ("金额", 1), ("出肉率", 1), ("备注", 1)]
H_SLA = ["日期", "羊群批次", "品类", "领入\n数量\n(只)", "标识", "类别", "数量\n(只)", "数量\n(kg)",
         "金额", "出肉率", "备注"]
F_SLA = [None, None, None, INT, None, None, INT, QTY, MONEY, PCT, None]
W_SLA = [11, 13, 9, 8, 8, 13, 7, 9, 12, 9, 16]

H_SOUT = ["出库/销售日期", "羊群批次", "销售批次", "去向", "商品名称", "数量(只)", "数量(kg)",
          "单价(元/kg)", "金额", "客户名称", "联系电话", "收款方式", "业务员", "备注"]
F_SOUT = [None, None, None, None, None, INT, QTY, PRICE, MONEY, None, None, None, None, None]
W_SOUT = [13, 12, 11, 11, 14, 8, 9, 10, 12, 16, 13, 9, 9, 14]

H_SIN = ["序号", "来源", "批次", "商品名称", "入库数量(只)", "入库数量(kg)", "单价(元/kg)", "入库金额", "备注"]
F_SIN = [INT, None, None, None, INT, QTY, PRICE, MONEY, None]
W_SIN = [6, 12, 12, 14, 10, 11, 10, 12, 16]

H_SSALE = ["序号", "去向", "批次", "商品名称", "数量(只)", "数量(kg)", "单价(元/kg)",
           "应收金额", "实收金额", "收款方式", "客户名称", "联系电话", "业务员", "备注"]
F_SSALE = [INT, None, None, None, INT, QTY, PRICE, MONEY, MONEY, None, None, None, None, None]
W_SSALE = [6, 9, 12, 14, 7, 9, 10, 11, 11, 9, 14, 13, 9, 12]

H_SSTOCK = ["序号", "批次", "存放地点", "商品名称", "库存数量(只)", "库存数量(kg)", "单价(元/kg)", "库存金额", "备注"]
F_SSTOCK = [INT, None, None, None, INT, QTY, PRICE, MONEY, None]
W_SSTOCK = [6, 12, 11, 14, 11, 11, 10, 12, 16]


# ---------------------------------------------------------------- 小工具
def _batch_head(ws: Worksheet, row: int, conn, batch_id: int, ncols: int) -> None:
    info = conn.get("batch", batch_id) or {}
    left = f"羊群批次：{info.get('code') or '（全部批次）'}"
    right = f"暂养圈编号：{info.get('pen') or ''}"
    ws.cell(row=row, column=1, value=left).font = X.BATCH_FONT
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(3, ncols // 2))
    ws.cell(row=row, column=1).alignment = Alignment(horizontal="left", vertical="center")
    col = max(4, ncols // 2 + 1)
    ws.cell(row=row, column=col, value=right).font = X.BATCH_FONT
    ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=ncols)
    ws.cell(row=row, column=col).alignment = Alignment(horizontal="right", vertical="center")
    ws.row_dimensions[row].height = 20


def _store_head(ws: Worksheet, row: int, store_name: str, label: str, value: str,
                ncols: int) -> None:
    ws.cell(row=row, column=1, value=f"门店名称：{store_name or '—'}").font = X.BATCH_FONT
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(3, ncols // 2))
    ws.cell(row=row, column=1).alignment = Alignment(horizontal="left", vertical="center")
    col = max(4, ncols // 2 + 1)
    ws.cell(row=row, column=col, value=f"{label}：{value or '—'}").font = X.BATCH_FONT
    ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=ncols)
    ws.cell(row=row, column=col).alignment = Alignment(horizontal="right", vertical="center")
    ws.row_dimensions[row].height = 20


# ---------------------------------------------------------------- 各表写入
def _sheet_feed(ws: Worksheet, conn, d1: str, d2: str, batch_id: int = 0) -> None:
    rows = calc.feed_ledger(conn, d1, d2, batch_id)
    n = X.write_title(ws, 1, "屠宰场暂养出入库台账", len(H_FEED),
                      sub=f"期间：{d1 or '不限'} 至 {d2 or '不限'}　口径：入库金额 = kg × 单价，"
                          f"出库金额按批次累计入库加权平均单价计价")
    _batch_head(ws, n, conn, batch_id, len(H_FEED))
    start = X.write_header(ws, n + 1, G_FEED, H_FEED)
    body = [[r.get("date"), r.get("_batch_code") or calc.batch_code(conn, r.get("batch_id")),
             r.get("_pen") or "", r.get("category") or calc.batch_category(conn, r.get("batch_id")),
             r.get("in_supplier") or "", r.get("in_tag") or "",
             float(r.get("in_count") or 0) or None, float(r.get("in_weight") or 0) or None,
             float(r.get("in_price") or 0) or None, r.get("_in_amount") or None,
             r.get("out_use") or "", float(r.get("out_count") or 0) or None,
             float(r.get("out_weight") or 0) or None, r.get("_out_amount") or None,
             r.get("_bal_count"), r.get("_bal_weight"), r.get("_bal_amount")]
            for r in rows]
    last = X.write_rows(ws, start, body, F_FEED)
    total = ["合计", "", "", "", "", "",
             sum(float(r.get("in_count") or 0) for r in rows),
             r1(sum(float(r.get("in_weight") or 0) for r in rows)), None,
             r2(sum(float(r.get("_in_amount") or 0) for r in rows)),
             "", sum(float(r.get("out_count") or 0) for r in rows),
             r1(sum(float(r.get("out_weight") or 0) for r in rows)),
             r2(sum(float(r.get("_out_amount") or 0) for r in rows)),
             "", "", ""]
    last = X.write_total(ws, last, total, len(H_FEED), F_FEED)
    X.write_note(ws, last + 1, NOTE_BATCH, len(H_FEED))
    X.set_widths(ws, W_FEED)
    X.freeze(ws, start)
    X.setup_page(ws)


def _sheet_breed(ws: Worksheet, conn, d1: str, d2: str, batch_id: int = 0) -> None:
    rows = calc.breeding_ledger(conn, d1, d2, batch_id)
    n = X.write_title(ws, 1, "养殖记录", len(H_BREED),
                      sub=f"期间：{d1 or '不限'} 至 {d2 or '不限'}　口径：期末存栏 = 期初存栏 − 出栏只数；"
                          f"投料金额 = 数量 × 单价")
    _batch_head(ws, n, conn, batch_id, len(H_BREED))
    start = X.write_header(ws, n + 1, G_BREED, H_BREED)
    body = [[r.get("date"), r.get("category") or calc.batch_category(conn, r.get("batch_id")),
             r.get("tag") or "", r.get("_open_count"), float(r.get("out_count") or 0) or None,
             r.get("_close_count"), r.get("out_use") or "", r.get("mat_name") or "",
             r.get("mat_unit") or "", float(r.get("mat_qty") or 0) or None,
             float(r.get("mat_price") or 0) or None, r.get("_mat_amount") or None,
             r.get("recorder") or ""] for r in rows]
    last = X.write_rows(ws, start, body, F_BREED)
    total = ["合计", "", "", None, sum(float(r.get("out_count") or 0) for r in rows), None, "", "", "",
             r1(sum(float(r.get("mat_qty") or 0) for r in rows)), None,
             r2(sum(float(r.get("_mat_amount") or 0) for r in rows)), ""]
    last = X.write_total(ws, last, total, len(H_BREED), F_BREED)
    X.write_note(ws, last + 1, NOTE_BATCH, len(H_BREED))
    X.set_widths(ws, W_BREED)
    X.freeze(ws, start)
    X.setup_page(ws)


def _sheet_slaughter(ws: Worksheet, conn, d1: str, d2: str, batch_id: int = 0) -> None:
    docs = calc.slaughter_docs(conn, d1, d2, batch_id)
    n = X.write_title(ws, 1, "屠宰记录", len(H_SLA),
                      sub=f"期间：{d1 or '不限'} 至 {d2 or '不限'}　口径：出肉率 = 产出合计 kg ÷ 领入毛重 kg；"
                          f"领用成本按批次暂养加权平均单价")
    _batch_head(ws, n, conn, batch_id, len(H_SLA))
    start = X.write_header(ws, n + 1, G_SLA, H_SLA)
    body: list[list] = []
    for d in docs:
        lines = calc.yield_lines(conn, int(d.get("id") or 0))
        if not lines:
            lines = [{}]
        for i, ln in enumerate(lines):
            first = i == 0
            body.append([
                d.get("date") if first else "",
                d.get("_batch_code") if first else "",
                d.get("category") if first else "",
                float(d.get("in_count") or 0) if first else None,
                d.get("tag") if first else "",
                ln.get("product") or "",
                float(ln.get("count") or 0) or None,
                float(ln.get("weight") or 0) or None,
                ln.get("_amount") or None,
                d.get("_yield_rate") if first else None,
                (d.get("remark") or "") if first else "",
            ])
    last = X.write_rows(ws, start, body, F_SLA)
    # 产出「只数」按类别重复计算，横向累加没有意义，合计行只给 kg 与金额
    total = ["合计", "", "", sum(float(d.get("in_count") or 0) for d in docs), "", "", None,
             r1(sum(float(d.get("_out_weight") or 0) for d in docs)),
             r2(sum(float(d.get("_out_amount") or 0) for d in docs)), None, ""]
    last = X.write_total(ws, last, total, len(H_SLA), F_SLA)
    X.write_note(ws, last + 1, NOTE_BATCH, len(H_SLA))
    X.set_widths(ws, W_SLA)
    X.freeze(ws, start)
    X.setup_page(ws)


def _sheet_sout(ws: Worksheet, conn, d1: str, d2: str, batch_id: int = 0) -> None:
    rows = calc.slaughter_out_rows(conn, d1, d2)
    if batch_id:
        rows = [r for r in rows if int(r.get("batch_id") or 0) == int(batch_id)]
    n = X.write_title(ws, 1, "屠宰出库（销售/内部调拨）明细", len(H_SOUT),
                      sub=f"期间：{d1 or '不限'} 至 {d2 or '不限'}　口径：金额 = 数量(kg) × 单价；"
                          f"销售批次 = 类型编码（对外销售 T / 内部调拨 N）+ 销售日期 8 位")
    start = X.write_flat_header(ws, n + 1, H_SOUT)
    body = [[r.get("date"), r.get("_batch_code"), r.get("_sale_batch"), r.get("target"),
             r.get("product"),
             float(r.get("count") or 0) or None, float(r.get("weight") or 0) or None,
             float(r.get("price") or 0) or None, r.get("_amount"),
             r.get("customer") or "", r.get("phone") or "", r.get("pay_method") or "",
             r.get("salesman") or "", r.get("remark") or ""] for r in rows]
    last = X.write_rows(ws, start, body, F_SOUT)
    total = ["合计", "", "", "", "", sum(float(r.get("count") or 0) for r in rows),
             r1(sum(float(r.get("weight") or 0) for r in rows)), None,
             r2(sum(float(r.get("_amount") or 0) for r in rows)), "", "", "", "", ""]
    last = X.write_total(ws, last, total, len(H_SOUT), F_SOUT)
    X.write_note(ws, last + 1, NOTE_SOUT, len(H_SOUT))
    X.set_widths(ws, W_SOUT)
    X.freeze(ws, start)
    X.setup_page(ws)


def _period(d1: str, d2: str) -> str:
    if d1 and d2 and d1 == d2:
        return d1
    return f"{d1 or '不限'} 至 {d2 or '不限'}"


def _store_label(conn, store_id: int) -> str:
    if store_id:
        return str((conn.get(T_STORE, store_id) or {}).get("name") or "")
    return "全部门店"


def _sheet_store_in(ws: Worksheet, conn, d1: str, d2: str, store_id: int = 0) -> None:
    rows = calc.store_in_rows(conn, store_id, d1, d2)
    n = X.write_title(ws, 1, "门店入库台账", len(H_SIN),
                      sub=f"期间：{d1 or '不限'} 至 {d2 or '不限'}　口径：入库金额 = 数量(kg) × 单价")
    _store_head(ws, n, _store_label(conn, store_id), "入库期间", _period(d1, d2), len(H_SIN))
    start = X.write_flat_header(ws, n + 1, H_SIN)
    body = [[i, r.get("source"), r.get("_batch_code"), r.get("product"),
             float(r.get("count") or 0) or None, float(r.get("weight") or 0) or None,
             float(r.get("price") or 0) or None, r.get("_amount"), r.get("remark") or ""]
            for i, r in enumerate(rows, start=1)]
    last = X.write_rows(ws, start, body, F_SIN)
    total = ["合计", "", "", "", sum(float(r.get("count") or 0) for r in rows),
             r1(sum(float(r.get("weight") or 0) for r in rows)), None,
             r2(sum(float(r.get("_amount") or 0) for r in rows)), ""]
    last = X.write_total(ws, last, total, len(H_SIN), F_SIN)
    X.set_widths(ws, W_SIN)
    X.freeze(ws, start)
    X.setup_page(ws)


def _sheet_store_sale(ws: Worksheet, conn, d1: str, d2: str, store_id: int = 0) -> None:
    rows = calc.store_sale_rows(conn, store_id, d1, d2)
    n = X.write_title(ws, 1, "门店销售台账", len(H_SSALE),
                      sub=f"期间：{d1 or '不限'} 至 {d2 or '不限'}　口径：应收 = 数量(kg) × 单价，"
                          f"实收按实际收款填列，差额即挂账")
    _store_head(ws, n, _store_label(conn, store_id), "销售期间", _period(d1, d2), len(H_SSALE))
    start = X.write_flat_header(ws, n + 1, H_SSALE)
    body = [[i, r.get("target"), r.get("_batch_code"), r.get("product"),
             float(r.get("count") or 0) or None, float(r.get("weight") or 0) or None,
             float(r.get("price") or 0) or None, r.get("_due"), r.get("_paid"),
             r.get("pay_method") or "", r.get("customer") or "", r.get("phone") or "",
             r.get("salesman") or "", r.get("remark") or ""] for i, r in enumerate(rows, start=1)]
    last = X.write_rows(ws, start, body, F_SSALE)
    total = ["合计", "", "", "", sum(float(r.get("count") or 0) for r in rows),
             r1(sum(float(r.get("weight") or 0) for r in rows)), None,
             r2(sum(float(r.get("_due") or 0) for r in rows)),
             r2(sum(float(r.get("_paid") or 0) for r in rows)), "", "", "", "", ""]
    last = X.write_total(ws, last, total, len(H_SSALE), F_SSALE)
    X.write_note(ws, last + 1, NOTE_SALE, len(H_SSALE))
    X.set_widths(ws, W_SSALE)
    X.freeze(ws, start)
    X.setup_page(ws)


def _sheet_store_stock(ws: Worksheet, conn, d1: str, d2: str, store_id: int = 0) -> None:
    rows = calc.store_stock_rows(conn, store_id, d1, d2)
    n = X.write_title(ws, 1, "门店结存/盘点台账", len(H_SSTOCK),
                      sub=f"盘点日期：{d2 or '不限'}　口径：库存金额 = 库存 kg × 单价；"
                          f"实盘与账面差异见系统「数据校验」")
    _store_head(ws, n, _store_label(conn, store_id), "盘点日期", d2 or d1, len(H_SSTOCK))
    start = X.write_flat_header(ws, n + 1, H_SSTOCK)
    body = [[i, r.get("_batch_code"), r.get("location"), r.get("product"),
             float(r.get("count") or 0) or None, float(r.get("weight") or 0) or None,
             float(r.get("price") or 0) or None, r.get("_amount"), r.get("remark") or ""]
            for i, r in enumerate(rows, start=1)]
    last = X.write_rows(ws, start, body, F_SSTOCK)
    total = ["合计", "", "", "", sum(float(r.get("count") or 0) for r in rows),
             r1(sum(float(r.get("weight") or 0) for r in rows)), None,
             r2(sum(float(r.get("_amount") or 0) for r in rows)), ""]
    last = X.write_total(ws, last, total, len(H_SSTOCK), F_SSTOCK)
    X.set_widths(ws, W_SSTOCK)
    X.freeze(ws, start)
    X.setup_page(ws)


# ---------------------------------------------------------------- 门店经营报表
# 进销存台账：一级明细 × 二级明细，六段「数量 / 金额」
G_SFLOW = [("一级明细", 1), ("二级明细", 1), ("上日结余", 2), ("当日入库", 2),
           ("当日出库", 2), ("当日结余", 2), ("当日销售", 2), ("当日损益", 2)]
H_SFLOW = ["一级明细", "二级明细",
           "数量\n(kg)", "金额", "数量\n(kg)", "金额", "数量\n(kg)", "金额",
           "数量\n(kg)", "金额", "数量\n(kg)", "金额", "数量\n(kg)", "金额"]
F_SFLOW = [None, None] + [QTY, MONEY] * 6
W_SFLOW = [12, 14] + [11] * 12

GAIN_RED, GAIN_GREEN = "C0392B", "0F8A5F"
EMPH_FILL = PatternFill("solid", fgColor="F1F5FB")


def _gain_color(value: float) -> str | None:
    """中国会计习惯：正数（收益）红、负数（亏损）绿。"""
    if value > 0:
        return GAIN_RED
    if value < 0:
        return GAIN_GREEN
    return None


def _sheet_store_ledger(ws: Worksheet, conn, store_id: int = 0, day: str = "",
                        cat1: str = "", cat2: str = "") -> None:
    store = _store_label(conn, store_id)
    rows = [r for r in calc.store_flow_rows(conn, store_id, day)
            if (not cat1 or r.cat1 == cat1) and (not cat2 or r.cat2 == cat2)]
    n = X.write_title(ws, 1, f"{store} 进销存台账", len(H_SFLOW),
                      sub=f"日期：{day or '—'}　口径：上日结余 + 当日入库 − 当日结余 = 当日出库；"
                          f"当日损益 = 当日销售 − 当日出库；数量按 kg、金额按入库加权平均成本")
    start = X.write_header(ws, n, G_SFLOW, H_SFLOW)
    body = [[r.cat1, r.cat2, r.open_qty, r.open_amt, r.in_qty, r.in_amt,
             r.out_qty, r.out_amt, r.close_qty, r.close_amt,
             r.sale_qty, r.sale_amt, r.gain_qty, r.gain_amt] for r in rows]
    last = X.write_rows(ws, start, body, F_SFLOW,
                        ["left", "left"] + ["right"] * 12)
    total = calc.store_flow_total(rows)
    values = ["小计", "", total.open_qty, total.open_amt, total.in_qty, total.in_amt,
              total.out_qty, total.out_amt, total.close_qty, total.close_amt,
              total.sale_qty, total.sale_amt, total.gain_qty, total.gain_amt]
    last = X.write_total(ws, last, values, len(H_SFLOW), F_SFLOW,
                         ["left", "left"] + ["right"] * 12)
    X.write_note(ws, last + 1,
                 "注：①当日结余记了盘点的取实盘数，没记盘点的取账面（上日结余 + 当日入库 − 当日销售），"
                 "所以出库里可能含盘亏 / 盘盈；②当日损益 = 当日销售金额 − 当日出库成本，"
                 "正为益（红）、负为损（绿）；③上日结余 = 截至前一日累计入库 − 累计销售。",
                 len(H_SFLOW))
    X.set_widths(ws, W_SFLOW)
    X.freeze(ws, start)
    X.setup_page(ws)


def _sheet_store_pnl(ws: Worksheet, conn, store_id: int = 0, day: str = "") -> None:
    store = _store_label(conn, store_id)
    rows, total = calc.store_pnl_rows(conn, store_id, day)
    lines = SR.build_lines(rows, total)
    n = X.write_title(ws, 1, f"{store} 损益表", len(SR.HEADERS),
                      sub=f"期间：{day or '—'}　口径：产出/收入 = 销售；投入/成本 = 出库；"
                          f"损益 = 产出 − 投入；盈利指标：数量列 = 数量口径、金额列 = 金额口径")

    # 口径说明写在表头上方（页面里收在「填写说明」，导出时一并带上）
    row = n
    for key, text in SR.NOTES:
        cell = ws.cell(row=row, column=1, value=f"{key}　{text}")
        cell.font = X.SUB_FONT
        cell.alignment = Alignment(horizontal="left", vertical="center")
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(SR.HEADERS))
        ws.row_dimensions[row].height = 16
        row += 1

    start = X.write_flat_header(ws, row, SR.HEADERS)
    for i, ln in enumerate(lines):
        r = start + i
        fmt = [None, None, ln.qty_fmt, ln.amt_fmt]
        vals = [ln.no, ln.name, SR.line_number(ln.qty, ln.qty_fmt),
                SR.line_number(ln.amt, ln.amt_fmt)]
        for c, val in enumerate(vals, start=1):
            cell = ws.cell(row=r, column=c, value=val)
            color = _gain_color(val) if (ln.gain and c >= 3 and isinstance(val, (int, float))) else None
            cell.font = Font(name=X.FONT_NAME, size=9.5, bold=ln.emph, color=color or "000000")
            cell.border = X.BORDER
            if ln.emph:
                cell.fill = EMPH_FILL
            cell.alignment = Alignment(
                horizontal="center" if c == 1 else
                "left" if c == 2 else "right", vertical="center")
            if fmt[c - 1]:
                cell.number_format = fmt[c - 1]
        ws.row_dimensions[r].height = 18

    X.set_widths(ws, [8, 30, 15, 17])
    X.freeze(ws, start)
    X.setup_page(ws, landscape=False)
    ws.print_title_rows = "1:2"          # 只重复标题 + 口径副标题，说明区不重复


def export_store_pnl(path: str | Path, conn, store_id: int = 0, day: str = "") -> Path:
    """单店损益表导出（版式同页面）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "损益表"
    _sheet_store_pnl(ws, conn, store_id, day)
    wb.save(target)
    wb.close()
    return target


def export_store_ledger(path: str | Path, conn, store_id: int = 0, day: str = "",
                        cat1: str = "", cat2: str = "") -> Path:
    """单店进销存台账导出（按当前分类筛选）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "进销存台账"
    _sheet_store_ledger(ws, conn, store_id, day, cat1, cat2)
    wb.save(target)
    wb.close()
    return target


# ---------------------------------------------------------------- 应收款项（应收 + 未收）
# 应收款一张单一行，单下面跟着它的每一笔收款（一对多），未收金额逐行往下减——照银行流水看
H_AR = ["序号", "销售批次", "客户名称", "联系电话", "商品 / 摘要", "应收金额", "结算方式",
        "约定收款日", "收款日期", "已收金额", "抹零金额", "未收金额", "业务员", "备注"]
F_AR = [INT, None, None, None, None, MONEY, None, None, None, MONEY, MONEY, MONEY, None, None]
W_AR = [6, 13, 20, 13, 16, 12, 10, 12, 12, 12, 11, 12, 9, 18]

H_AROPEN = ["序号", "客户名称", "销售批次", "商品 / 摘要", "应收金额", "结算方式", "约定收款日",
            "已收金额", "抹零金额", "未收金额", "账龄(天)", "逾期(天)", "联系电话", "备注"]
F_AROPEN = [INT, None, None, None, MONEY, None, None, MONEY, MONEY, MONEY, INT, INT, None, None]
W_AROPEN = [6, 19, 13, 16, 12, 10, 12, 12, 11, 12, 9, 9, 13, 18]

NOTE_AR = ("注：①应收款由销售单自动提取——屠宰出库明细里收款方式为挂账 / 月结的销售行、"
           "门店销售应收大于实收的差额；②销售批次 = 类型编码（对外销售 T / 内部调拨 N）+ 销售日期 8 位，"
           "约定收款日 = 销售日期 + 账期（现结 / 预付 0 天、周结 7 天、半月结 15 天、月结 30 天）；"
           "③收款照银行流水逐笔登记在对应应收单下面，一张单可对应多笔；"
           "应收单那行的「已收金额 / 抹零金额」为下面各笔的小计，未收金额 = 应收金额 − 已收金额 − 抹零金额；"
           "④未收金额为负数表示实收大于应收，即预收款。")


def _ar_subject(conn, biz: str, store_id: int = 0) -> str:
    if str(biz) == AR_BIZ_SLAUGHTER:
        return "屠宰销售（屠宰场直接对外销售）"
    return f"门店销售（{_store_label(conn, store_id)}）"


def _ar_head(ws: Worksheet, row: int, subject: str, label: str, value: str,
             ncols: int) -> None:
    ws.cell(row=row, column=1, value=f"核算对象：{subject}").font = X.BATCH_FONT
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(3, ncols // 2))
    ws.cell(row=row, column=1).alignment = Alignment(horizontal="left", vertical="center")
    col = max(4, ncols // 2 + 1)
    ws.cell(row=row, column=col, value=f"{label}：{value or '—'}").font = X.BATCH_FONT
    ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=ncols)
    ws.cell(row=row, column=col).alignment = Alignment(horizontal="right", vertical="center")
    ws.row_dimensions[row].height = 20


def _sheet_ar_invoice(ws: Worksheet, conn, d1: str, d2: str, biz: str,
                      store_id: int = 0) -> None:
    rows = calc.ar_detail_rows(conn, biz, store_id, d1, d2)
    invoices = [r for r in rows if r.get("_kind") != "receipt"]
    n = X.write_title(ws, 1, "应收款项 · 应收款明细（含逐笔收款）", len(H_AR),
                      sub=f"期间：{_period(d1, d2)}　口径：应收单按销售挂账自动提取；"
                          f"销售批次 = 类型编码（对外销售 T / 内部调拨 N）+ 销售日期；"
                          f"约定收款日 = 销售日期 + 账期；未收 = 应收 − 已收 − 抹零")
    _ar_head(ws, n, _ar_subject(conn, biz, store_id), "应收期间", _period(d1, d2), len(H_AR))
    start = X.write_flat_header(ws, n + 1, H_AR)
    body: list[list] = []
    seq = 0
    for r in rows:
        if r.get("_kind") == "receipt":
            body.append(["", "", "", "", "", None, "", "",
                         r.get("receipt_date") or "", r.get("receipt_amount"),
                         r2(float(r.get("waiver") or 0)) or None,
                         r.get("_unpaid"), "", r.get("remark") or ""])
            continue
        seq += 1
        body.append([seq, r.get("sale_batch") or "", r.get("customer") or "—",
                     r.get("phone") or "", r.get("summary") or "", r.get("_amount"),
                     r.get("settle") or "", r.get("due_date") or "", "小计",
                     r2(float(r.get("_received") or 0)) or None,
                     r2(float(r.get("_waiver") or 0)) or None,
                     r.get("_unpaid"), r.get("salesman") or "", r.get("remark") or ""])
    last = X.write_rows(ws, start, body, F_AR,
                        [None, "center", None, None, None, None, None, "center", "center",
                         None, None, None, None, None])
    received_rows = [r for r in rows if r.get("_kind") == "receipt"]
    prepaid = r2(sum(-min(float(r.get("_unpaid") or 0), 0.0) for r in invoices))
    total = ["合计", "", "", "", "",
             r2(sum(float(r.get("_amount") or 0) for r in invoices)), "", "", "",
             r2(sum(float(r.get("receipt_amount") or 0) for r in received_rows)),
             r2(sum(float(r.get("_waiver") or 0) for r in invoices)),
             r2(sum(max(float(r.get("_unpaid") or 0), 0.0) for r in invoices)), "",
             "" if prepaid <= 0.005 else f"其中预收 {prepaid:,.2f}（未收为负数的行）"]
    last = X.write_total(ws, last, total, len(H_AR), F_AR)
    X.write_note(ws, last + 1, NOTE_AR, len(H_AR))
    X.set_widths(ws, W_AR)
    X.freeze(ws, start)
    X.setup_page(ws)


def _sheet_ar_open(ws: Worksheet, conn, d1: str, d2: str, biz: str,
                   store_id: int = 0) -> None:
    as_of = d2 or d1
    rows = calc.ar_open_items(conn, biz, store_id, as_of)
    n = X.write_title(ws, 1, "应收款项 · 未收款明细", len(H_AROPEN),
                      sub=f"截至：{as_of or '不限'}　口径：未收 = 应收 − 已收；"
                          f"账龄 = 截至日 − 销售日期（销售批次后 8 位）；逾期 = 截至日 − 约定收款日")
    _ar_head(ws, n, _ar_subject(conn, biz, store_id), "截至日期", as_of, len(H_AROPEN))
    start = X.write_flat_header(ws, n + 1, H_AROPEN)
    body = [[i, r.get("customer") or "—", r.get("sale_batch") or "", r.get("summary") or "",
             r.get("_amount"), r.get("settle") or "", r.get("due_date") or "",
             r.get("_received"), r.get("_waiver") or None, r.get("_unpaid"), r.get("_age"),
             r.get("_overdue") or None, r.get("phone") or "", r.get("remark") or ""]
            for i, r in enumerate(rows, start=1)]
    last = X.write_rows(ws, start, body, F_AROPEN,
                        [None, None, "center", None, None, None, "center",
                         None, None, None, None, None, None, None])
    total = ["合计", f"{len(rows)} 笔", "", "",
             r2(sum(float(r.get("_amount") or 0) for r in rows)),
             "", "",
             r2(sum(float(r.get("_received") or 0) for r in rows)),
             r2(sum(float(r.get("_waiver") or 0) for r in rows)),
             r2(sum(float(r.get("_unpaid") or 0) for r in rows)), "", "", "", ""]
    last = X.write_total(ws, last, total, len(H_AROPEN), F_AROPEN)
    X.write_note(ws, last + 1, NOTE_AR, len(H_AROPEN))
    X.set_widths(ws, W_AROPEN)
    X.freeze(ws, start)
    X.setup_page(ws)


def export_ar_invoice(path: str | Path, conn, biz: str, store_id: int = 0,
                      d1: str = "", d2: str = "") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "应收款明细"
    _sheet_ar_invoice(ws, conn, d1, d2, biz, store_id)
    wb.save(target)
    wb.close()
    return target


def export_ar_open(path: str | Path, conn, biz: str, store_id: int = 0,
                   as_of: str = "") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "未收款明细"
    _sheet_ar_open(ws, conn, as_of, as_of, biz, store_id)
    wb.save(target)
    wb.close()
    return target


def export_receivable_workbook(path: str | Path, conn, biz: str, store_id: int = 0,
                               d1: str = "", d2: str = "") -> Path:
    """两张表一个工作簿：应收款（含逐笔收款）/ 未收款（月末对账一次拿走）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    for name, fn in (("应收款明细", _sheet_ar_invoice), ("未收款明细", _sheet_ar_open)):
        ws = wb.create_sheet(name)
        fn(ws, conn, d1, d2, biz, store_id)
    wb.save(target)
    wb.close()
    return target


# ---------------------------------------------------------------- 应付款项（应付 + 未付）
# 表头照《账表记录-羊.xlsx》的「应付款」：序号 / 入库批次 / 供应商名称 / 联系电话 / 商品 /
# 应付金额 / 付款日期 / 已付款金额 / 未付款余额（多一列备注，方便记付款说明）
H_AP = ["序号", "入库批次", "供应商名称", "联系电话", "商品", "应付金额",
        "付款日期", "已付款金额", "未付款余额", "备注"]
F_AP = [INT, None, None, None, None, MONEY, None, MONEY, MONEY, None]
W_AP = [6, 13, 20, 13, 15, 12, 12, 12, 12, 20]

H_APOPEN = ["序号", "入库批次", "供应商名称", "联系电话", "商品", "应付金额",
            "已付款金额", "未付款余额", "账龄(天)", "备注"]
F_APOPEN = [INT, None, None, None, None, MONEY, MONEY, MONEY, INT, None]
W_APOPEN = [6, 13, 20, 13, 15, 12, 12, 12, 9, 20]

NOTE_AP = ("注：①应付款由「活羊入库&结余」自动提取——一次采购一张单，应付金额 = 入栏 kg × 入栏均价；"
           "②付款照银行流水逐笔登记在对应应付单下面，一张单可对应多笔；"
           "应付单那行的「已付款金额」为下面各笔的小计，未付款余额 = 应付金额 − 已付款金额；"
           "③未付款余额为负数表示实付大于应付，即预付 / 多付款；④账龄 = 截至日 − 采购入库日期。")


def _sheet_ap_invoice(ws: Worksheet, conn, d1: str, d2: str) -> None:
    rows = calc.ap_detail_rows(conn, d1, d2)
    invoices = [r for r in rows if r.get("_kind") != "payment"]
    n = X.write_title(ws, 1, "应付款项 · 应付款明细（含逐笔付款）", len(H_AP),
                      sub=f"期间：{_period(d1, d2)}　口径：应付单按入库批次自动提取；"
                          f"未付款余额 = 应付 − 已付；负数＝预付 / 多付")
    _ar_head(ws, n, "活羊采购（活羊入库&结余）", "应付期间", _period(d1, d2), len(H_AP))
    start = X.write_flat_header(ws, n + 1, H_AP)
    body: list[list] = []
    seq = 0
    for r in rows:
        if r.get("_kind") == "payment":
            body.append(["", "", "", "", "", None, r.get("pay_date") or "",
                         r.get("pay_amount"), r.get("_unpaid"), r.get("remark") or ""])
            continue
        seq += 1
        body.append([seq, r.get("batch_code") or "", r.get("supplier") or "—",
                     r.get("phone") or "", r.get("item") or "", r.get("_amount"),
                     "小计", r2(float(r.get("_paid") or 0)) or None,
                     r.get("_unpaid"), r.get("remark") or ""])
    last = X.write_rows(ws, start, body, F_AP,
                        [None, "center", None, None, None, None, "center", None, None, None])
    pays = [r for r in rows if r.get("_kind") == "payment"]
    prepaid = r2(sum(-min(float(r.get("_unpaid") or 0), 0.0) for r in invoices))
    total = ["合计", "", "", "", "",
             r2(sum(float(r.get("_amount") or 0) for r in invoices)), "",
             r2(sum(float(r.get("pay_amount") or 0) for r in pays)),
             r2(sum(max(float(r.get("_unpaid") or 0), 0.0) for r in invoices)),
             "" if prepaid <= 0.005 else f"其中预付 / 多付 {prepaid:,.2f}（未付为负数的行）"]
    last = X.write_total(ws, last, total, len(H_AP), F_AP)
    X.write_note(ws, last + 1, NOTE_AP, len(H_AP))
    X.set_widths(ws, W_AP)
    X.freeze(ws, start)
    X.setup_page(ws)


def _sheet_ap_open(ws: Worksheet, conn, d1: str, d2: str) -> None:
    as_of = d2 or d1
    rows = calc.ap_open_items(conn, as_of)
    n = X.write_title(ws, 1, "应付款项 · 未付款明细", len(H_APOPEN),
                      sub=f"截至：{as_of or '不限'}　口径：未付 = 应付 − 已付；"
                          f"账龄 = 截至日 − 采购入库日期；负数＝预付 / 多付")
    _ar_head(ws, n, "活羊采购（活羊入库&结余）", "截至日期", as_of, len(H_APOPEN))
    start = X.write_flat_header(ws, n + 1, H_APOPEN)
    body = [[i, r.get("batch_code") or "", r.get("supplier") or "—", r.get("phone") or "",
             r.get("item") or "", r.get("_amount"), r.get("_paid"), r.get("_unpaid"),
             r.get("_age"), r.get("remark") or ""]
            for i, r in enumerate(rows, start=1)]
    last = X.write_rows(ws, start, body, F_APOPEN,
                        [None, "center", None, None, None, None, None, None, None, None])
    total = ["合计", f"{len(rows)} 笔", "", "", "",
             r2(sum(float(r.get("_amount") or 0) for r in rows)),
             r2(sum(float(r.get("_paid") or 0) for r in rows)),
             r2(sum(float(r.get("_unpaid") or 0) for r in rows)), "", ""]
    last = X.write_total(ws, last, total, len(H_APOPEN), F_APOPEN)
    X.write_note(ws, last + 1, NOTE_AP, len(H_APOPEN))
    X.set_widths(ws, W_APOPEN)
    X.freeze(ws, start)
    X.setup_page(ws)


def export_ap_invoice(path: str | Path, conn, d1: str = "", d2: str = "") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "应付款明细"
    _sheet_ap_invoice(ws, conn, d1, d2)
    wb.save(target)
    wb.close()
    return target


def export_ap_open(path: str | Path, conn, as_of: str = "") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "未付款明细"
    _sheet_ap_open(ws, conn, as_of, as_of)
    wb.save(target)
    wb.close()
    return target


def export_payable_workbook(path: str | Path, conn, d1: str = "", d2: str = "") -> Path:
    """两张表一个工作簿：应付款（含逐笔付款）/ 未付款。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    for name, fn in (("应付款明细", _sheet_ap_invoice), ("未付款明细", _sheet_ap_open)):
        ws = wb.create_sheet(name)
        fn(ws, conn, d1, d2)
    wb.save(target)
    wb.close()
    return target



# ---------------------------------------------------------------- 对账单（按未收款逐笔）
# 版式照客户《账表记录-羊.xlsx》里「对账单2」那张：宋体、浅蓝表头（#D9E0F4）、黑色细框、
# A4 纵向一页。做法是**直接拿模板那张表当底稿**（样式/列宽/合并全保留），
# 只往里填数据、按行数插行，所以打出来跟模板一模一样；模板不在时才用下面这套兜底版式。
ST_TEMPLATE_SHEET = "对账单2"
ST_HEAD = ["序号", "销售批次", "商品 / 摘要", "应收金额(元)", "已收金额(元)",
           "抹零金额(元)", "未收金额(元)", "备注"]
ST_STYLE_HEAD = ["序号", "销售批次", "商品 / 摘要", "应收金额(元)", "已收金额(元)",
                 "抹零金额(元)", "未收金额(元)", "备注"]
ST_W = [7.67, 8.89, 8.89, 12.44, 13.56, 12.89, 13.78, 8.89]
ST_FILL = "FFD9E0F4"
ST_SIDE = Side(style="thin", color="FF000000")
ST_BORDER = Border(left=ST_SIDE, right=ST_SIDE, top=ST_SIDE, bottom=ST_SIDE)
ST_FONT = "宋体"
ST_NOTE = "注：请核对无误后签字 / 盖章回传，如有出入请联系我公司对账联系人"
ST_OUR_DEFAULT = "—"


def rmb_upper(amount) -> str:
    """金额转人民币大写（柒佰零肆元整 / 壹仟贰佰元伍角…），对账单结论行要用。"""
    digits = "零壹贰叁肆伍陆柒捌玖"
    units = ["", "拾", "佰", "仟"]
    big = ["", "万", "亿", "兆"]

    value = round(float(amount or 0), 2)
    if abs(value) < 0.005:
        return "零元整"
    sign = "负" if value < 0 else ""
    value = abs(value)
    yuan = int(value)
    cents = int(round((value - yuan) * 100))
    if cents == 100:
        yuan += 1
        cents = 0
    jiao, fen = divmod(cents, 10)

    def _four(seg: int) -> str:
        text, zero = "", False
        for i in range(3, -1, -1):
            d = (seg // 10 ** i) % 10
            if d:
                if zero:
                    text += "零"
                    zero = False
                text += digits[d] + units[i]
            elif text:
                zero = True
        return text

    groups: list[int] = []
    n = yuan
    while n > 0:
        groups.append(n % 10000)
        n //= 10000
    parts: list[str] = []
    for idx in range(len(groups) - 1, -1, -1):
        seg = groups[idx]
        if seg == 0:
            if parts and not parts[-1].endswith("零"):
                parts.append("零")
            continue
        if parts and seg < 1000 and not parts[-1].endswith("零"):
            parts.append("零")
        parts.append(_four(seg) + big[idx])
    whole = "".join(parts).rstrip("零") or "零"
    if not jiao and not fen:
        return f"{sign}{whole}元整"
    tail = ""
    if jiao:
        tail += digits[jiao] + "角"
    if fen:
        if not jiao:
            tail += "零"
        tail += digits[fen] + "分"
    return f"{sign}{whole}元{tail}"


def _statement_rows(conn, biz: str, store_id: int, customer: str, as_of: str) -> list[dict]:
    key = calc.ar_customer_key(customer)
    return [r for r in calc.ar_open_items(conn, biz, store_id, as_of)
            if calc.ar_customer_key(r.get("customer")) == key]


def _statement_totals(rows: list[dict]) -> tuple[float, float, float, float]:
    due = r2(sum(float(r.get("_amount") or 0) for r in rows))
    paid = r2(sum(float(r.get("_received") or 0) for r in rows))
    waiver = r2(sum(float(r.get("_waiver") or 0) for r in rows))
    open_amt = r2(sum(float(r.get("_unpaid") or 0) for r in rows))
    return due, paid, waiver, open_amt


def _statement_cells(rows: list[dict]) -> list[list]:
    """明细行的 8 列内容：序号 / 销售批次 / 商品 / 应收 / 已收 / 抹零 / 未收 / 备注。"""
    out = []
    for i, r in enumerate(rows, start=1):
        overdue = int(float(r.get("_overdue") or 0))
        out.append([
            i, r.get("sale_batch") or "", r.get("summary") or "",
            r2(float(r.get("_amount") or 0)),
            r2(float(r.get("_received") or 0)) or None,
            r2(float(r.get("_waiver") or 0)) or None,
            r2(float(r.get("_unpaid") or 0)),
            f"逾期 {overdue} 天" if overdue > 0 else "",
        ])
    return out


def _sheet_statement(ws: Worksheet, conn, biz: str, store_id: int, customer: str,
                     contact: str, phone: str, as_of: str, our_contact: str = "",
                     our_phone: str = "", company: str = "") -> None:
    """兜底版式（模板文件不在时用）：仍是 A4 纵向、浅蓝表头、黑色细框。"""
    company = company or config.COMPANY
    rows = _statement_rows(conn, biz, store_id, customer, as_of)
    due, paid, waiver, open_amt = _statement_totals(rows)
    ncol = len(ST_HEAD)

    def _line(row: int, left: str, right: str) -> None:
        ws.cell(row=row, column=1, value=left).font = Font(ST_FONT, 10.5, bold=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
        ws.cell(row=row, column=1).alignment = Alignment("left", "center")
        ws.cell(row=row, column=5, value=right).font = Font(ST_FONT, 10.5, bold=True)
        ws.merge_cells(start_row=row, start_column=5, end_row=row, end_column=ncol)
        ws.cell(row=row, column=5).alignment = Alignment("right", "center")
        ws.row_dimensions[row].height = 25

    ws.cell(row=1, column=1, value=f"{company}\n对  账  单").font = Font(
        ST_FONT, 14, bold=True)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
    ws.cell(row=1, column=1).alignment = Alignment("center", "center", wrap_text=True)
    ws.row_dimensions[1].height = 45

    _line(2, f"客户名称：{customer or ST_OUR_DEFAULT}", f"对账日期：{as_of or ST_OUR_DEFAULT}")
    _line(3, f"客户联系人：{contact or ST_OUR_DEFAULT}",
          f"联系电话：{phone or ST_OUR_DEFAULT}")

    for i, name in enumerate(ST_HEAD, start=1):
        c = ws.cell(row=4, column=i, value=name)
        c.font = Font(ST_FONT, 9.5, bold=True)
        c.fill = PatternFill("solid", fgColor=ST_FILL)
        c.alignment = Alignment("center", "center", wrap_text=True)
        c.border = ST_BORDER

    for i, values in enumerate(_statement_cells(rows)):
        for c, val in enumerate(values, start=1):
            cell = ws.cell(row=5 + i, column=c)
            cell.value = val
            cell.font = Font(ST_FONT, 9.5)
            cell.border = ST_BORDER
            if c in (4, 5, 6, 7):
                cell.number_format = MONEY
                cell.alignment = Alignment("right", "center")
            elif c in (2, 8):
                cell.alignment = Alignment("center", "center")
            else:
                cell.alignment = Alignment("left" if c == 3 else "right", "center")

    total_row = 5 + max(len(rows), 1)
    for c in range(1, ncol + 1):
        cell = ws.cell(row=total_row, column=c)
        cell.font = Font(ST_FONT, 9.5, bold=True)
        cell.fill = PatternFill("solid", fgColor=ST_FILL)
        cell.border = ST_BORDER
    ws.cell(row=total_row, column=1, value="合计").alignment = Alignment("left", "center")
    for c, val in ((4, due), (5, paid), (6, waiver), (7, open_amt)):
        cell = ws.cell(row=total_row, column=c, value=val)
        cell.number_format = MONEY
        cell.alignment = Alignment("right", "center")

    note_row = total_row + 1
    ws.cell(row=note_row, column=1, value=ST_NOTE).font = Font(ST_FONT, 11)
    ws.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=ncol)
    ws.cell(row=note_row, column=1).alignment = Alignment("left", "center")
    ws.row_dimensions[note_row].height = 25

    concl_row = note_row + 1
    ws.cell(row=concl_row, column=1,
            value=f"截至 {as_of}，未收合计：¥{open_amt:,.2f}元"
                  f"（人民币大写：{rmb_upper(open_amt)}）").font = Font(
        ST_FONT, 11, bold=True, color=X.NAVY)
    ws.merge_cells(start_row=concl_row, start_column=1, end_row=concl_row, end_column=ncol)
    ws.cell(row=concl_row, column=1).alignment = Alignment("left", "center")
    ws.row_dimensions[concl_row].height = 25

    our_row = concl_row + 1
    ws.cell(row=our_row, column=1,
            value=f"我公司联系人：{our_contact or ST_OUR_DEFAULT}").font = Font(
        ST_FONT, 10.5, bold=True, color=X.NAVY)
    ws.cell(row=our_row, column=5,
            value=f"联系电话：{our_phone or ST_OUR_DEFAULT}").font = Font(
        ST_FONT, 10.5, bold=True, color=X.NAVY)
    ws.merge_cells(start_row=our_row, start_column=5, end_row=our_row, end_column=ncol)
    ws.cell(row=our_row, column=5).alignment = Alignment("right", "center")
    ws.row_dimensions[our_row].height = 25

    pad = 16
    blocks = (
        f"上述数据来源于我公司的销售单和已收款回单，已核对无误！\n\n"
        f"供货方（盖章）：{company}{' ' * pad}日期：      年    月    日",
        f"   已核对无误！\n\n"
        f"客户确认（签字 / 盖章）：{' ' * 36}日期：      年    月    日",
    )
    for i, text in enumerate(blocks):
        row = our_row + 1 + i
        c = ws.cell(row=row, column=1, value=text)
        c.font = Font(ST_FONT, 9.5)
        c.alignment = Alignment("center", "center", wrap_text=True)
        for cc in range(1, ncol + 1):
            cell = ws.cell(row=row, column=cc)
            cell.border = ST_BORDER
            cell.font = Font(ST_FONT, 9.5)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncol)
        ws.row_dimensions[row].height = 63

    X.set_widths(ws, ST_W)
    ws.page_setup.orientation = "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_margins.left = ws.page_margins.right = 0.75
    ws.page_margins.top = ws.page_margins.bottom = 1.0
    ws.page_margins.header = ws.page_margins.footer = 0.5


def _workbook_from_template(tpl: Path, conn, biz: str, store_id: int, customer: str,
                            contact: str, phone: str, as_of: str,
                            our_contact: str, our_phone: str):
    """拿模板的「对账单2」当底稿：留着样式、列宽、合并，只换内容与行数。"""
    try:
        wb = load_workbook(tpl)
    except Exception:
        return None
    if ST_TEMPLATE_SHEET not in wb.sheetnames:
        wb.close()
        return None
    ws = wb[ST_TEMPLATE_SHEET]
    for name in list(wb.sheetnames):
        if name != ST_TEMPLATE_SHEET:
            wb.remove(wb[name])
    ws.title = "对账单"
    # 模板里带着指向别的账套的外部链接（7MB 的 externalLink），对账单用不上，清掉
    try:
        wb._external_links = []
    except Exception:
        pass

    company = ""
    title_lines = str(ws["A1"].value or "").split("\n")
    if title_lines and title_lines[0].strip():
        company = title_lines[0].strip()
    try:
        company = str(conn.setting("statement_company", "") or "").strip() or company
    except Exception:
        pass
    company = company or config.COMPANY

    rows = _statement_rows(conn, biz, store_id, customer, as_of)
    cells = _statement_cells(rows)
    n = max(len(rows), 1)

    # 先拆合并，再插行、复制数据行样式，最后按新位置重新合并
    merges = [str(rng) for rng in ws.merged_cells.ranges]
    for rng in merges:
        ws.unmerge_cells(rng)

    data_style = [copy(ws.cell(row=5, column=c)._style) for c in range(1, 9)]
    data_height = ws.row_dimensions[5].height
    # insert_rows 只挪单元格、不挪行高，原 5~11 行的高先记下来，最后按新位置铺回去
    heights = {r: ws.row_dimensions[r].height for r in range(5, 12)}
    if n > 1:
        ws.insert_rows(6, n - 1)
        for r in range(6, 5 + n):
            for c in range(1, 9):
                ws.cell(row=r, column=c)._style = copy(data_style[c - 1])

    total_row = 5 + n
    note_row = total_row + 1
    concl_row = note_row + 1
    our_row = concl_row + 1
    block1 = our_row + 1
    block2 = block1 + 1

    # 行高写死，不依赖「默认行高」——WPS 打开时默认行高会掉到 14.4 磅，整张表会挤成一团
    ws.row_dimensions[2].height = 25
    ws.row_dimensions[3].height = 25
    ws.row_dimensions[4].height = 30
    for i in range(n):
        ws.row_dimensions[5 + i].height = 25
    for row in (total_row, note_row):
        ws.row_dimensions[row].height = 25
    ws.row_dimensions[concl_row].height = 28
    ws.row_dimensions[our_row].height = 26
    ws.row_dimensions[block1].height = heights.get(10) or 63
    ws.row_dimensions[block2].height = heights.get(11) or 64

    # 抬头
    ws["A1"] = f"{company}\n对  账  单"
    ws["A2"] = f"客户名称：{customer or ST_OUR_DEFAULT}"
    ws["E2"] = f"对账日期：{as_of or ST_OUR_DEFAULT}"
    ws["A3"] = f"客户联系人：{contact or ST_OUR_DEFAULT}"
    ws["E3"] = f"联系电话：{phone or ST_OUR_DEFAULT}"

    # 明细
    if not cells:                       # 没有未收款：把模板那行示例值清掉，别留在纸上
        for c in range(1, 9):
            ws.cell(row=5, column=c).value = None
    for i, values in enumerate(cells):
        for c, val in enumerate(values, start=1):
            # 注意：ws.cell(value=None) 不会覆盖原值，必须直接赋给 .value 才能清空
            ws.cell(row=5 + i, column=c).value = val

    # 合计
    due, paid, waiver, open_amt = _statement_totals(rows)
    ws.cell(row=total_row, column=1).value = "合计"
    for col, val in ((4, due), (5, paid), (6, waiver), (7, open_amt)):
        ws.cell(row=total_row, column=col).value = val

    ws.cell(row=note_row, column=1, value=ST_NOTE)
    ws.cell(row=concl_row, column=1,
            value=f"截至 {as_of}，未收合计：¥{open_amt:,.2f}元"
                  f"（人民币大写：{rmb_upper(open_amt)}）")
    ws.cell(row=our_row, column=1, value=f"我公司联系人：{our_contact or ST_OUR_DEFAULT}")
    ws.cell(row=our_row, column=5, value=f"联系电话：{our_phone or ST_OUR_DEFAULT}")

    pad = max(4, 16 + (14 - len(company)))
    ws.cell(row=block1, column=1,
            value=f"上述数据来源于我公司的销售单和已收款回单，已核对无误！\n\n"
                  f"供货方（盖章）：{company}{' ' * pad}日期：      年    月    日")
    ws.cell(row=block2, column=1,
            value=f"   已核对无误！\n\n"
                  f"客户确认（签字 / 盖章）：{' ' * 36}日期：      年    月    日")

    for rng in ("A1:H1", "A2:D2", "E2:H2", "A3:D3", "E3:H3",
                f"A{note_row}:H{note_row}", f"A{concl_row}:H{concl_row}",
                f"E{our_row}:H{our_row}",
                f"A{block1}:H{block1}", f"A{block2}:H{block2}"):
        ws.merge_cells(rng)
    return wb


def export_statement(path: str | Path, conn, biz: str, store_id: int, customer: str,
                     contact: str = "", phone: str = "", as_of: str = "",
                     our_contact: str = "", our_phone: str = "") -> Path:
    """一个客户一张对账单：模板在就照着「对账单2」出，不在就按兜底版式出。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    wb = None
    tpl = config.template_workbook()
    if tpl is not None:
        wb = _workbook_from_template(tpl, conn, biz, store_id, customer, contact, phone,
                                     as_of, our_contact, our_phone)
    if wb is None:
        wb = Workbook()
        ws = wb.active
        ws.title = "对账单"
        _sheet_statement(ws, conn, biz, store_id, customer, contact, phone, as_of,
                         our_contact, our_phone)
    wb.save(target)
    wb.close()
    return target


# ---------------------------------------------------------------- 采购对账单（按未付款逐笔）
# 跟销售对账单同一套版式（直接拿模板「对账单2」当底稿），只是把「客户 / 应收」换成
# 「供应商 / 应付」：8 列 —— 序号 / 入库批次 / 商品·摘要 / 应付 / 已付 / 未付 / 账龄 / 备注。
ST_AP_HEAD = ["序号", "入库批次", "商品", "应付金额(元)", "已付款金额(元)",
              "未付款金额(元)", "账龄(天)", "备注"]
# 备注列比销售对账单宽一点（采购单的备注常写批次 / 车号），钱列略收窄，整页仍是一页宽
ST_AP_W = [7.67, 8.89, 8.89, 12.44, 11.5, 11.5, 8.5, 14.0]
ST_AP_NOTE = "注：请核对无误后签字 / 盖章回传，如有出入请联系我公司采购对账联系人"


def _ap_statement_rows(conn, supplier: str, as_of: str) -> list[dict]:
    key = calc.ap_supplier_key(supplier)
    return [r for r in calc.ap_open_items(conn, as_of)
            if calc.ap_supplier_key(r.get("supplier")) == key]


def _ap_statement_totals(rows: list[dict]) -> tuple[float, float, float]:
    due = r2(sum(float(r.get("_amount") or 0) for r in rows))
    paid = r2(sum(float(r.get("_paid") or 0) for r in rows))
    open_amt = r2(sum(float(r.get("_unpaid") or 0) for r in rows))
    return due, paid, open_amt


def _ap_statement_cells(rows: list[dict]) -> list[list]:
    out = []
    for i, r in enumerate(rows, start=1):
        out.append([
            i, r.get("batch_code") or "", r.get("item") or "",
            r2(float(r.get("_amount") or 0)),
            r2(float(r.get("_paid") or 0)) or None,
            r2(float(r.get("_unpaid") or 0)),
            int(float(r.get("_age") or 0)),
            r.get("remark") or "",
        ])
    return out


def _ap_sheet_statement(ws: Worksheet, conn, supplier: str, contact: str, phone: str,
                        as_of: str, our_contact: str = "", our_phone: str = "",
                        company: str = "") -> None:
    """兜底版式（模板文件不在时用）：A4 纵向、浅蓝表头、黑色细框。"""
    company = company or config.COMPANY
    rows = _ap_statement_rows(conn, supplier, as_of)
    due, paid, open_amt = _ap_statement_totals(rows)
    ncol = len(ST_AP_HEAD)

    def _line(row: int, left: str, right: str) -> None:
        ws.cell(row=row, column=1, value=left).font = Font(ST_FONT, 10.5, bold=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
        ws.cell(row=row, column=1).alignment = Alignment("left", "center")
        ws.cell(row=row, column=5, value=right).font = Font(ST_FONT, 10.5, bold=True)
        ws.merge_cells(start_row=row, start_column=5, end_row=row, end_column=ncol)
        ws.cell(row=row, column=5).alignment = Alignment("right", "center")
        ws.row_dimensions[row].height = 25

    ws.cell(row=1, column=1, value=f"{company}\n采 购 对 账 单").font = Font(
        ST_FONT, 14, bold=True)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
    ws.cell(row=1, column=1).alignment = Alignment("center", "center", wrap_text=True)
    ws.row_dimensions[1].height = 45

    _line(2, f"供应商名称：{supplier or ST_OUR_DEFAULT}", f"对账日期：{as_of or ST_OUR_DEFAULT}")
    _line(3, f"供应商联系人：{contact or ST_OUR_DEFAULT}",
          f"联系电话：{phone or ST_OUR_DEFAULT}")

    for i, name in enumerate(ST_AP_HEAD, start=1):
        c = ws.cell(row=4, column=i, value=name)
        c.font = Font(ST_FONT, 9.5, bold=True)
        c.fill = PatternFill("solid", fgColor=ST_FILL)
        c.alignment = Alignment("center", "center", wrap_text=True)
        c.border = ST_BORDER

    for i, values in enumerate(_ap_statement_cells(rows)):
        for c, val in enumerate(values, start=1):
            cell = ws.cell(row=5 + i, column=c)
            cell.value = val
            cell.font = Font(ST_FONT, 9.5)
            cell.border = ST_BORDER
            if c in (4, 5, 6):
                cell.number_format = MONEY
                cell.alignment = Alignment("right", "center")
            elif c == 7:
                cell.number_format = INT
                cell.alignment = Alignment("center", "center")
            elif c in (2, 8):
                cell.alignment = Alignment("center", "center")
            else:
                cell.alignment = Alignment("left" if c == 3 else "right", "center")

    total_row = 5 + max(len(rows), 1)
    for c in range(1, ncol + 1):
        cell = ws.cell(row=total_row, column=c)
        cell.font = Font(ST_FONT, 9.5, bold=True)
        cell.fill = PatternFill("solid", fgColor=ST_FILL)
        cell.border = ST_BORDER
    ws.cell(row=total_row, column=1, value="合计").alignment = Alignment("left", "center")
    for c, val in ((4, due), (5, paid), (6, open_amt)):
        cell = ws.cell(row=total_row, column=c, value=val)
        cell.number_format = MONEY
        cell.alignment = Alignment("right", "center")

    note_row = total_row + 1
    ws.cell(row=note_row, column=1, value=ST_AP_NOTE).font = Font(ST_FONT, 11)
    ws.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=ncol)
    ws.cell(row=note_row, column=1).alignment = Alignment("left", "center")
    ws.row_dimensions[note_row].height = 25

    concl_row = note_row + 1
    ws.cell(row=concl_row, column=1,
            value=f"截至 {as_of}，未付合计：¥{open_amt:,.2f}元"
                  f"（人民币大写：{rmb_upper(open_amt)}）").font = Font(
        ST_FONT, 11, bold=True, color=X.NAVY)
    ws.merge_cells(start_row=concl_row, start_column=1, end_row=concl_row, end_column=ncol)
    ws.cell(row=concl_row, column=1).alignment = Alignment("left", "center")
    ws.row_dimensions[concl_row].height = 25

    our_row = concl_row + 1
    ws.cell(row=our_row, column=1,
            value=f"我公司联系人：{our_contact or ST_OUR_DEFAULT}").font = Font(
        ST_FONT, 10.5, bold=True, color=X.NAVY)
    ws.cell(row=our_row, column=5,
            value=f"联系电话：{our_phone or ST_OUR_DEFAULT}").font = Font(
        ST_FONT, 10.5, bold=True, color=X.NAVY)
    ws.merge_cells(start_row=our_row, start_column=5, end_row=our_row, end_column=ncol)
    ws.cell(row=our_row, column=5).alignment = Alignment("right", "center")
    ws.row_dimensions[our_row].height = 25

    blocks = (
        f"上述数据来源于我公司的入库单和已付款回单，已核对无误！\n\n"
        f"采购方（盖章）：{company}{' ' * 16}日期：      年    月    日",
        f"   已核对无误！\n\n"
        f"供应商确认（签字 / 盖章）：{' ' * 36}日期：      年    月    日",
    )
    for i, text in enumerate(blocks):
        row = our_row + 1 + i
        c = ws.cell(row=row, column=1, value=text)
        c.font = Font(ST_FONT, 9.5)
        c.alignment = Alignment("center", "center", wrap_text=True)
        for cc in range(1, ncol + 1):
            cell = ws.cell(row=row, column=cc)
            cell.border = ST_BORDER
            cell.font = Font(ST_FONT, 9.5)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncol)
        ws.row_dimensions[row].height = 63

    X.set_widths(ws, ST_AP_W)
    ws.page_setup.orientation = "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_margins.left = ws.page_margins.right = 0.75
    ws.page_margins.top = ws.page_margins.bottom = 1.0
    ws.page_margins.header = ws.page_margins.footer = 0.5


def _ap_workbook_from_template(tpl: Path, conn, supplier: str, contact: str, phone: str,
                               as_of: str, our_contact: str, our_phone: str):
    """拿模板的「对账单2」当底稿出采购对账单：样式 / 列宽 / 行高全保留，只换内容与行数。"""
    try:
        wb = load_workbook(tpl)
    except Exception:
        return None
    if ST_TEMPLATE_SHEET not in wb.sheetnames:
        wb.close()
        return None
    ws = wb[ST_TEMPLATE_SHEET]
    for name in list(wb.sheetnames):
        if name != ST_TEMPLATE_SHEET:
            wb.remove(wb[name])
    ws.title = "采购对账单"
    try:
        wb._external_links = []
    except Exception:
        pass

    company = ""
    title_lines = str(ws["A1"].value or "").split("\n")
    if title_lines and title_lines[0].strip():
        company = title_lines[0].strip()
    try:
        company = str(conn.setting("statement_company", "") or "").strip() or company
    except Exception:
        pass
    company = company or config.COMPANY

    rows = _ap_statement_rows(conn, supplier, as_of)
    cells = _ap_statement_cells(rows)
    n = max(len(rows), 1)

    merges = [str(rng) for rng in ws.merged_cells.ranges]
    for rng in merges:
        ws.unmerge_cells(rng)

    data_style = [copy(ws.cell(row=5, column=c)._style) for c in range(1, 9)]
    heights = {r: ws.row_dimensions[r].height for r in range(5, 12)}
    if n > 1:
        ws.insert_rows(6, n - 1)
        for r in range(6, 5 + n):
            for c in range(1, 9):
                ws.cell(row=r, column=c)._style = copy(data_style[c - 1])

    total_row = 5 + n
    note_row = total_row + 1
    concl_row = note_row + 1
    our_row = concl_row + 1
    block1 = our_row + 1
    block2 = block1 + 1

    ws.row_dimensions[2].height = 25
    ws.row_dimensions[3].height = 25
    ws.row_dimensions[4].height = 34
    for i in range(n):
        ws.row_dimensions[5 + i].height = 25
    for row in (total_row, note_row):
        ws.row_dimensions[row].height = 25
    ws.row_dimensions[concl_row].height = 28
    ws.row_dimensions[our_row].height = 26
    ws.row_dimensions[block1].height = heights.get(10) or 63
    ws.row_dimensions[block2].height = heights.get(11) or 64

    ws["A1"] = f"{company}\n采 购 对 账 单"
    ws["A2"] = f"供应商名称：{supplier or ST_OUR_DEFAULT}"
    ws["E2"] = f"对账日期：{as_of or ST_OUR_DEFAULT}"
    ws["A3"] = f"供应商联系人：{contact or ST_OUR_DEFAULT}"
    ws["E3"] = f"联系电话：{phone or ST_OUR_DEFAULT}"

    for c, name in enumerate(ST_AP_HEAD, start=1):
        ws.cell(row=4, column=c).value = name

    if not cells:
        for c in range(1, 9):
            ws.cell(row=5, column=c).value = None
    for i, values in enumerate(cells):
        for c, val in enumerate(values, start=1):
            cell = ws.cell(row=5 + i, column=c)
            cell.value = val
            if c == 7:                       # 账龄：模板那列是金额格式，这里按整数显示
                cell.number_format = INT
                cell.alignment = Alignment("center", "center")
            elif c == 8:                     # 备注：窄列自动换行，超长文字不会顶到第 2 页
                cell.alignment = Alignment("left", "center", wrap_text=True)
        # 备注每行约容 7 个汉字：按内容给行高，别让第二行被框线切掉
        remark = str(values[7] if len(values) > 7 else "")
        lines = max(1, min(3, (len(remark) + 6) // 7))
        ws.row_dimensions[5 + i].height = 25 + (lines - 1) * 13

    # 列宽按采购对账单排：备注宽一点，钱列收窄，整页仍是一页宽
    X.set_widths(ws, ST_AP_W)

    due, paid, open_amt = _ap_statement_totals(rows)
    ws.cell(row=total_row, column=1).value = "合计"
    for col, val in ((4, due), (5, paid), (6, open_amt)):
        ws.cell(row=total_row, column=col).value = val
    ws.cell(row=total_row, column=7).value = None

    ws.cell(row=note_row, column=1, value=ST_AP_NOTE)
    ws.cell(row=concl_row, column=1,
            value=f"截至 {as_of}，未付合计：¥{open_amt:,.2f}元"
                  f"（人民币大写：{rmb_upper(open_amt)}）")
    ws.cell(row=our_row, column=1, value=f"我公司联系人：{our_contact or ST_OUR_DEFAULT}")
    ws.cell(row=our_row, column=5, value=f"联系电话：{our_phone or ST_OUR_DEFAULT}")

    pad = max(4, 16 + (14 - len(company)))
    ws.cell(row=block1, column=1,
            value=f"上述数据来源于我公司的入库单和已付款回单，已核对无误！\n\n"
                  f"采购方（盖章）：{company}{' ' * pad}日期：      年    月    日")
    ws.cell(row=block2, column=1,
            value=f"   已核对无误！\n\n"
                  f"供应商确认（签字 / 盖章）：{' ' * 36}日期：      年    月    日")

    for rng in ("A1:H1", "A2:D2", "E2:H2", "A3:D3", "E3:H3",
                f"A{note_row}:H{note_row}", f"A{concl_row}:H{concl_row}",
                f"E{our_row}:H{our_row}",
                f"A{block1}:H{block1}", f"A{block2}:H{block2}"):
        ws.merge_cells(rng)
    return wb


def export_ap_statement(path: str | Path, conn, supplier: str, contact: str = "",
                        phone: str = "", as_of: str = "", our_contact: str = "",
                        our_phone: str = "") -> Path:
    """一个供应商一张采购对账单：模板在就照「对账单2」出，不在就按兜底版式出。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    wb = None
    tpl = config.template_workbook()
    if tpl is not None:
        wb = _ap_workbook_from_template(tpl, conn, supplier, contact, phone, as_of,
                                        our_contact, our_phone)
    if wb is None:
        wb = Workbook()
        ws = wb.active
        ws.title = "采购对账单"
        _ap_sheet_statement(ws, conn, supplier, contact, phone, as_of,
                            our_contact, our_phone)
    wb.save(target)
    wb.close()
    return target


# ---------------------------------------------------------------- 客户名录
# 版式照用户模板《客户名录.xlsx》：标题合并居中 18 号粗体、表头 10.5 号粗体无底色、
# 数据 10 号、细边框 #BFCFC8、行高 26、冻结前三行、结算方式带下拉。
H_CUST = ["序号", "归属", "客户名称（店名/单位）", "统一信用代码/身份证号", "联系人",
          "联系电话", "经营/配送地址", "结算方式", "首次供货时间", "业务对接人", "备注"]
W_CUST = [6, 17.25, 24, 24, 14.25, 14, 26.462962962963, 11, 15.0185185185185, 11, 20]
A_CUST = ["center", "center", "left", "left", "left", "left", "left",
          "center", "center", "center", "left"]
CUST_FONT = "微软雅黑"
_cust_side = Side(style="thin", color="FFBFCFC8")
CUST_BORDER = Border(left=_cust_side, right=_cust_side, top=_cust_side, bottom=_cust_side)
CUST_DV_RANGE = "H3:H500"          # 下拉铺到 500 行：在 Excel 里往下续录也还带着选项


def _sheet_customers(ws: Worksheet, rows: list[dict]) -> None:
    ncol = len(H_CUST)

    cell = ws.cell(row=1, column=1, value="客户名录")
    cell.font = Font(name=CUST_FONT, size=18, bold=True)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
    ws.row_dimensions[1].height = 38

    for i, name in enumerate(H_CUST, start=1):
        c = ws.cell(row=2, column=i, value=name)
        c.font = Font(name=CUST_FONT, size=10.5, bold=True)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = CUST_BORDER
    ws.row_dimensions[2].height = 36

    r = 3
    for idx, rec in enumerate(rows, start=1):
        values = [idx, rec.get("org") or "", rec.get("name") or "", rec.get("credit_code") or "",
                  rec.get("contact") or "", rec.get("phone") or "", rec.get("address") or "",
                  rec.get("settle") or "", rec.get("first_date") or "", rec.get("owner") or "",
                  rec.get("remark") or ""]
        for i, val in enumerate(values, start=1):
            c = ws.cell(row=r, column=i, value=val)
            c.font = Font(name=CUST_FONT, size=10)
            c.alignment = Alignment(horizontal=A_CUST[i - 1], vertical="center", wrap_text=True)
            c.border = CUST_BORDER
        ws.row_dimensions[r].height = 26
        r += 1

    if r > 3:                       # 结算方式照模板做成下拉，省得写成十几种说法
        dv = DataValidation(type="list", formula1='"' + ",".join(SETTLE_METHODS) + '"',
                            allow_blank=True, showInputMessage=True, showErrorMessage=True)
        dv.prompt = "结算方式\n下拉选择"
        dv.error = "请从下拉里选：" + " / ".join(SETTLE_METHODS)
        ws.add_data_validation(dv)
        dv.add(CUST_DV_RANGE)

    X.set_widths(ws, W_CUST)
    ws.freeze_panes = "A3"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True
    ws.print_title_rows = "1:2"
    ws.sheet_view.zoomScale = 85


def export_customers(path: str | Path, rows: list[dict]) -> Path:
    """客户名录导出：传当前筛选出来的行，出表版式与用户模板一致。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "客户名录"
    _sheet_customers(ws, rows)
    wb.save(target)
    wb.close()
    return target


# 「活羊入库&结余」：入库日期在首列，后面跟着编号与结余两列（库存 / 结余都是现算的）
H_BATCH = ["入库日期", "批次编号", "羊群品类", "圈号", "供应商", "标识",
           "入栏\n数量(只)", "入栏\n数量(kg)", "入栏均价\n(元/kg)", "入栏金额",
           "当前存栏\n数量(只)", "暂养结存\n数量(kg)", "备注"]
F_BATCH = [None, None, None, None, None, None, INT, QTY, PRICE, MONEY, INT, QTY, None]
W_BATCH = [11, 12, 10, 6, 22, 13, 9, 10, 11, 12, 10, 12, 20]
NOTE_BATCH_LIST = (
    "注：①批次编号＝入库日期（YYYYMMDD；同一天进两批，第二批起挂 -2）；"
    "②入栏金额 = 入栏 kg × 入栏均价，并按「一次采购一张单」自动提取应付；"
    "③当前存栏取养殖记录最后一行的期末存栏；④暂养结存 = 累计入库 kg − 累计出库 kg。"
)


def _sheet_batches(ws: Worksheet, rows: list[dict]) -> None:
    n = X.write_title(ws, 1, "活羊入库&结余", len(H_BATCH),
                      sub="口径：入栏金额 = kg × 均价　·　当前存栏取养殖记录期末　·　"
                          "暂养结存 = 累计入库 − 累计出库")
    start = X.write_flat_header(ws, n, H_BATCH)
    body = [[r.get("entry_date") or "", r.get("code") or "", r.get("category") or "",
             r.get("pen") or "", r.get("supplier") or "", r.get("tag") or "",
             float(r.get("count") or 0) or None, float(r.get("weight") or 0) or None,
             float(r.get("price") or 0) or None, r.get("_amount") or None,
             float(r.get("_stock") or 0) or None, float(r.get("_bal_weight") or 0) or None,
             r.get("remark") or ""] for r in rows]
    last = X.write_rows(ws, start, body, F_BATCH)
    total = ["合计", "", "", "", "", "",
             sum(float(r.get("count") or 0) for r in rows),
             r1(sum(float(r.get("weight") or 0) for r in rows)), None,
             r2(sum(float(r.get("_amount") or 0) for r in rows)), "", "", ""]
    last = X.write_total(ws, last, total, len(H_BATCH), F_BATCH)
    X.write_note(ws, last + 1, NOTE_BATCH_LIST, len(H_BATCH))
    X.set_widths(ws, W_BATCH)
    X.freeze(ws, start)
    X.setup_page(ws)
    ws.print_title_rows = f"1:{start - 1}"     # 标题 / 口径 / 表头三行跨页重复


def export_batches(path: str | Path, rows: list[dict]) -> Path:
    """活羊入库&结余导出：传当前筛选出来的批次（页面上已带好现算的结余列）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "活羊入库&结余"
    _sheet_batches(ws, rows)
    wb.save(target)
    wb.close()
    return target


SHEETS = (
    ("屠宰场暂养出入库台账", _sheet_feed),
    ("养殖记录", _sheet_breed),
    ("屠宰记录", _sheet_slaughter),
    ("屠宰出库明细", _sheet_sout),
    ("门店入库台账", _sheet_store_in),
    ("门店销售台账", _sheet_store_sale),
    ("门店结存盘点台账", _sheet_store_stock),
)


# ---------------------------------------------------------------- 对外入口
def export_workbook(path: str | Path, conn, d1: str = "", d2: str = "",
                    store_id: int = 0, batch_id: int = 0) -> Path:
    """七张台账整套导出（一个工作簿 7 个工作表，顺序照模板）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    for name, fn in SHEETS:
        ws = wb.create_sheet(name[:31])
        if fn in (_sheet_store_in, _sheet_store_sale, _sheet_store_stock):
            fn(ws, conn, d1, d2, store_id)
        else:
            fn(ws, conn, d1, d2, batch_id)
    wb.save(target)
    wb.close()
    return target


_MODULE_BUILDERS = {
    "feed": (_sheet_feed, "屠宰场暂养出入库台账"),
    "breeding": (_sheet_breed, "养殖记录"),
    "slaughter": (_sheet_slaughter, "屠宰记录"),
    "slaughter_out": (_sheet_sout, "屠宰出库明细"),
    "store_in": (_sheet_store_in, "门店入库台账"),
    "store_sale": (_sheet_store_sale, "门店销售台账"),
    "store_stock": (_sheet_store_stock, "门店结存盘点台账"),
}


def export_module(path: str | Path, module: str, conn, d1: str = "", d2: str = "",
                  store_id: int = 0, batch_id: int = 0) -> Path:
    """单张台账导出（页面上的「导出」按钮）。"""
    fn, name = _MODULE_BUILDERS[module]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = name[:31]
    if fn in (_sheet_store_in, _sheet_store_sale, _sheet_store_stock):
        fn(ws, conn, d1, d2, store_id)
    else:
        fn(ws, conn, d1, d2, batch_id)
    wb.save(target)
    wb.close()
    return target
