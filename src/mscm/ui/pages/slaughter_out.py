"""屠宰出库明细：屠宰场对外销售 + 内部调拨到门店。"""

from __future__ import annotations

from mscm.core import calc, repo
from mscm.core.models import OUT_TARGETS, PAY_METHODS, r2, sale_batch_code
from mscm.ui.dialogs import confirm, info
from mscm.ui.pages.base_ledger import FieldSpec, InlineLedgerPage
from mscm.ui.widgets import button

HELP = (
    "<b>这张表记什么</b>　屠宰场所有出门的货：卖给客户、调拨给门店、赠送，一笔一行。<br>"
    "<b>羊群批次</b>　这批货是哪个羊群批次出的（入库时定的那个批次，不是销售时的日期），"
    "成本、库存都按它归集。<br>"
    "<b>销售批次</b>　= 销售类型编码 + 销售日期：<b>对外销售 T</b>、<b>内部调拨 N</b>，"
    "如 <b>T20261115</b>。改了日期或去向，这列自动重算；应收款项里的销售批次就用它。<br>"
    "<b>去向</b>　门店调拨 / 对外销售 / 客户直供 / 赠送。"
    "选「门店调拨」时必须选门店，否则转门店入库时不知道入哪家。<br>"
    "<b>金额</b>　= 数量(kg) × 单价；只数只作辅助，不进金额。<br>"
    "<b>转门店入库</b>　点这个按钮，把所有「门店调拨」的出库单自动转成门店入库明细"
    "（来源＝屠宰场调拨，备注里记着来源出库单号）。已经转过的不会再转一遍，可以放心重复点。<br>"
    "<b>成本与毛利</b>　这张表只管收入口径；成本按屠宰单的单位成本算，见「数据校验」。"
)


class SlaughterOutPage(InlineLedgerPage):
    TITLE = "屠宰出库（销售 / 内部调拨）明细"
    MODULE = "slaughter_out"
    EXPORT_STEM = "屠宰出库明细"
    ROW_NAME = "出库单"
    BATCH_FILTER = True
    KEYWORD_TIP = "商品 / 客户 / 销售批次…"
    HELP_HTML = HELP
    SUM_KEYS = (("count", "int"), ("weight", "qty"), ("_amount", "money"))
    FIELDS = [
        FieldSpec("date", "出库/销售日期", "date", 112, "center"),
        FieldSpec("batch", "羊群批次", "batch", 142),
        FieldSpec("_sale_batch", "销售批次", "ro_text", 100, "center"),
        FieldSpec("target", "去向", "combo", 92, options=OUT_TARGETS, required=True),
        FieldSpec("store", "调拨门店", "store", 96),
        FieldSpec("product", "商品名称", "product", 108, required=True),
        FieldSpec("count", "数量(只)", "int", 76, "right"),
        FieldSpec("weight", "数量(kg)", "num", 84, "right"),
        FieldSpec("price", "单价", "money", 78, "right"),
        FieldSpec("_amount", "金额", "computed", 96, "right", decimals=2),
        FieldSpec("customer", "客户名称", "text", 108),
        FieldSpec("phone", "联系电话", "text", 104),
        FieldSpec("pay_method", "收款方式", "combo", 84, options=PAY_METHODS),
        FieldSpec("salesman", "业务员", "text", 72),
        FieldSpec("remark", "备注", "text", 96, stretch=True),
    ]

    # ---------------------------------------------------------- 按钮
    def extra_buttons(self):
        self.btn_sync = button("→ 转门店入库", "Gold", self.on_sync,
                               tip="把所有「门店调拨」的出库单转成门店入库明细（已转过的跳过）")
        return [self.btn_sync]

    # ---------------------------------------------------------- 取数
    def fetch(self) -> list[dict]:
        rows = calc.slaughter_out_rows(self.ctx.conn, self.d1, self.d2, self.keyword)
        if self.batch_id:
            rows = [r for r in rows if int(r.get("batch_id") or 0) == self.batch_id]
        return sorted(rows, key=lambda r: (str(r.get("date") or ""), int(r.get("id") or 0)))

    def blank(self) -> dict:
        opts = repo.batch_options(self.ctx.conn)
        bid = self.batch_id or (opts[0][1] if opts else 0)
        stores = self.ctx.store_options()
        return {
            "id": 0, "date": self.ctx.biz_date, "batch_id": bid, "target": "门店调拨",
            "store_id": stores[0][1] if stores else 0, "product": "",
            "count": 0.0, "weight": 0.0, "price": 0.0, "customer": "", "phone": "",
            "pay_method": "现款", "salesman": "", "remark": "",
            "_sale_batch": sale_batch_code(self.ctx.biz_date, "门店调拨"),
        }

    def recalc(self, values: dict, base: dict | None) -> dict:
        """金额 = kg × 单价；销售批次跟着日期与去向走（T 对外 / N 内调）。"""
        return {
            "_amount": r2(float(values.get("weight") or 0) * float(values.get("price") or 0)),
            "_sale_batch": sale_batch_code(values.get("date"), values.get("target")),
        }

    def validate(self, values: dict) -> str:
        if not int(values.get("batch_id") or 0):
            return "先选一个羊群批次"
        if not str(values.get("product") or "").strip():
            return "商品名称不能为空"
        if float(values.get("weight") or 0) <= 0:
            return "数量(kg) 要大于 0"
        if float(values.get("price") or 0) <= 0:
            return "单价要大于 0"
        if not str(values.get("target") or "").strip():
            return "选一个去向"
        if str(values.get("target")) == "门店调拨" and not int(values.get("store_id") or 0):
            return "去向是「门店调拨」就要选门店"
        return ""

    def save_record(self, data: dict, rid: int | None) -> dict:
        payload = {
            "date": data.get("date"),
            "batch_id": int(data.get("batch_id") or 0),
            "target": data.get("target") or "",
            "store_id": int(data.get("store_id") or 0) if data.get("target") == "门店调拨" else 0,
            "product": data.get("product") or "",
            "count": float(data.get("count") or 0),
            "weight": float(data.get("weight") or 0),
            "price": float(data.get("price") or 0),
            "customer": data.get("customer") or "",
            "phone": data.get("phone") or "",
            "pay_method": data.get("pay_method") or "",
            "salesman": data.get("salesman") or "",
            "remark": data.get("remark") or "",
        }
        return repo.save_row(self.ctx.conn, "slaughter_out", payload, rid)

    def delete_record(self, rid: int) -> None:
        repo.delete_row(self.ctx.conn, "slaughter_out", rid)

    # ---------------------------------------------------------- 转门店入库
    def on_sync(self) -> None:
        rows = [r for r in self.ctx.conn.rows("slaughter_out") if r.get("target") == "门店调拨"]
        if not rows:
            self.notify("还没有「门店调拨」的出库单", "warn")
            return
        if not confirm(self, "转门店入库",
                       f"把 {len(rows)} 张「门店调拨」出库单转成门店入库明细？\n"
                       "已经转过的会自动跳过，不会重复入库。"):
            return
        created, skipped, msgs = repo.sync_store_in_from_out(self.ctx.conn)
        self.ctx.changed()
        text = f"已生成 {created} 条门店入库"
        if skipped:
            text += f"，跳过已转过的 {skipped} 条"
        if msgs:
            text += "；" + "；".join(msgs[:3])
        self.notify(text)
        info(self, "转门店入库", text)
