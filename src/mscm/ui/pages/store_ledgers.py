"""门店管理下的三张台账：入库台账 / 销售台账 / 结存（盘点）台账。

三张都锁在一个门店上（导航「门店管理 › 关一店 › …」进来即锁定）：
筛选条不出现门店下拉，录入也不会跑到别的店去——单据串店是这类台账最常见的错。
"""

from __future__ import annotations

from mscm.core import calc, repo
from mscm.core.models import (
    PAY_METHODS, SALE_TARGETS, STOCK_LOCATIONS, STORE_IN_SOURCES, r2, T_SSTOCK,
)
from mscm.ui.dialogs import confirm, info
from mscm.ui.pages.base_ledger import FieldSpec, InlineLedgerPage
from mscm.ui.widgets import button

HELP_IN = (
    "<b>这张表记什么</b>　门店收到的每一批货：从屠宰场调拨来的、外购的、退库的。<br>"
    "<b>来源</b>　屠宰场调拨（由「屠宰出库明细」转过来，备注里带来源单号）/ 外购 / 退库。<br>"
    "<b>批次</b>　必须落到具体羊群批次，门店库存才是按批次算得出来的；"
    "批次错了，盘点和毛利都会跟着错。<br>"
    "<b>金额</b>　= 数量(kg) × 单价。"
)

HELP_SALE = (
    "<b>这张表记什么</b>　门店所有销售，包括赠送（赠送也要登记，实收填 0）。<br>"
    "<b>应收</b>　= 数量(kg) × 单价，系统自动算；<b>实收</b>　填实际收到的钱，"
    "差额就是挂账，页脚与「数据校验」都会提示未收金额。<br>"
    "<b>去向</b>　零售 / 批发 / 配送 / 赠送 / 内部调拨。<br>"
    "<b>客户信息</b>　现款零售散客可以不填；非现收、配送、挂账必须开《销货单》并留客户信息。<br>"
    "<b>库存影响</b>　门店账面库存 = 入库 − 销售，按 批次 × 商品 逐项轧差。"
)

HELP_STOCK = (
    "<b>这张表记什么</b>　门店实盘：某一天、某个存放地点、某批次某商品实际还有多少。<br>"
    "<b>按账面生成</b>　点按钮先把「入库 − 销售」的账面数拉成草稿行，"
    "人只需把实盘数量改上去，省得一行行敲。<br>"
    "<b>差异</b>　实盘 kg − 账面 kg，非零即为盘点差异（损耗、串货、漏单），"
    "在「数据校验」里集中列示，便于追查。<br>"
    "<b>金额</b>　= 库存 kg × 单价。"
)


class _StorePage(InlineLedgerPage):
    """门店专属台账：锁定门店，标题带店名。"""

    BATCH_FILTER = False

    def page_title(self) -> str:
        name = repo.store_name(self.ctx.conn, self.store_id) or "门店"
        return f"{name}　·　{self.TITLE}"

    def blank(self) -> dict:
        data = super().blank()
        data["store_id"] = self.store_id
        return data


class StoreInPage(_StorePage):
    TITLE = "入库台账"
    MODULE = "store_in"
    EXPORT_STEM = "门店入库台账"
    ROW_NAME = "入库单"
    KEYWORD_TIP = "商品 / 来源…"
    HELP_HTML = HELP_IN
    SUM_KEYS = (("count", "int"), ("weight", "qty"), ("_amount", "money"))
    FIELDS = [
        FieldSpec("date", "入库日期", "date", 108, "center"),
        FieldSpec("source", "来源", "combo", 100, options=STORE_IN_SOURCES, required=True),
        FieldSpec("batch", "批次", "batch", 146, required=True),
        FieldSpec("product", "商品名称", "product", 112, required=True),
        FieldSpec("count", "数量(只)", "int", 78, "right"),
        FieldSpec("weight", "数量(kg)", "num", 86, "right"),
        FieldSpec("price", "单价", "money", 80, "right"),
        FieldSpec("_amount", "入库金额", "computed", 100, "right", decimals=2),
        FieldSpec("remark", "备注", "text", 140, stretch=True),
    ]

    def fetch(self) -> list[dict]:
        return calc.store_in_rows(self.ctx.conn, self.store_id, self.d1, self.d2, self.keyword)

    def blank(self) -> dict:
        data = super().blank()
        opts = repo.batch_options(self.ctx.conn)
        data.update({
            "batch_id": opts[0][1] if opts else 0, "source": "屠宰场调拨",
            "product": "", "count": 0.0, "weight": 0.0, "price": 0.0, "remark": "",
        })
        return data

    def recalc(self, values: dict, base: dict | None) -> dict:
        return {"_amount": r2(float(values.get("weight") or 0) * float(values.get("price") or 0))}

    def validate(self, values: dict) -> str:
        if not int(values.get("batch_id") or 0):
            return "先选一个羊群批次"
        if not str(values.get("product") or "").strip():
            return "商品名称不能为空"
        if float(values.get("weight") or 0) <= 0:
            return "数量(kg) 要大于 0"
        if float(values.get("price") or 0) <= 0:
            return "单价要大于 0"
        return ""

    def save_record(self, data: dict, rid: int | None) -> dict:
        payload = {
            "store_id": self.store_id,
            "date": data.get("date"),
            "source": data.get("source") or "",
            "batch_id": int(data.get("batch_id") or 0),
            "product": data.get("product") or "",
            "count": float(data.get("count") or 0),
            "weight": float(data.get("weight") or 0),
            "price": float(data.get("price") or 0),
            "remark": data.get("remark") or "",
        }
        return repo.save_row(self.ctx.conn, "store_in", payload, rid)

    def delete_record(self, rid: int) -> None:
        repo.delete_row(self.ctx.conn, "store_in", rid)


class StoreSalePage(_StorePage):
    TITLE = "销售台账"
    MODULE = "store_sale"
    EXPORT_STEM = "门店销售台账"
    ROW_NAME = "销售单"
    KEYWORD_TIP = "商品 / 客户 / 业务员…"
    HELP_HTML = HELP_SALE
    SUM_KEYS = (("count", "int", "数量(只)"), ("weight", "qty", "数量(kg)"),
                ("_due", "money", "应收"), ("_paid", "money", "实收"),
                ("_unpaid", "money", "未收"))
    FIELDS = [
        FieldSpec("date", "销售日期", "date", 100, "center"),
        FieldSpec("target", "去向", "combo", 78, options=SALE_TARGETS, required=True),
        FieldSpec("batch", "批次", "batch", 122, required=True),
        FieldSpec("product", "商品名称", "product", 96, required=True),
        FieldSpec("count", "数量(只)", "int", 64, "right"),
        FieldSpec("weight", "数量(kg)", "num", 76, "right"),
        FieldSpec("price", "单价", "money", 70, "right"),
        FieldSpec("_due", "应收金额", "computed", 92, "right", decimals=2),
        FieldSpec("paid", "实收金额", "money", 92, "right"),
        FieldSpec("_unpaid", "未收金额", "computed", 92, "right", decimals=2),
        FieldSpec("pay_method", "收款方式", "combo", 76, options=PAY_METHODS),
        FieldSpec("customer", "客户名称", "text", 96),
        FieldSpec("phone", "联系电话", "text", 96),
        FieldSpec("salesman", "业务员", "text", 62),
        FieldSpec("remark", "备注", "text", 80, stretch=True),
    ]

    def fetch(self) -> list[dict]:
        return calc.store_sale_rows(self.ctx.conn, self.store_id, self.d1, self.d2, self.keyword)

    def blank(self) -> dict:
        data = super().blank()
        opts = repo.batch_options(self.ctx.conn)
        data.update({
            "batch_id": opts[0][1] if opts else 0, "target": "零售", "product": "",
            "count": 0.0, "weight": 0.0, "price": 0.0, "paid": 0.0,
            "pay_method": "现款", "customer": "", "phone": "", "salesman": "", "remark": "",
        })
        return data

    def recalc(self, values: dict, base: dict | None) -> dict:
        due = r2(float(values.get("weight") or 0) * float(values.get("price") or 0))
        paid = float(values.get("paid") or 0)
        # 实收没动过（还是 0 或等于旧应收）就跟着应收走，避免一条条手填
        base = base or {}
        old_due = float(base.get("_due") or 0)
        if paid == 0 or (old_due and abs(paid - old_due) < 0.005):
            paid = due
            patch = {"paid": paid}
        else:
            patch = {}
        patch["_due"] = due
        patch["_unpaid"] = r2(due - paid)
        return patch

    def validate(self, values: dict) -> str:
        if not int(values.get("batch_id") or 0):
            return "先选一个羊群批次"
        if not str(values.get("product") or "").strip():
            return "商品名称不能为空"
        if float(values.get("weight") or 0) <= 0:
            return "数量(kg) 要大于 0"
        if float(values.get("price") or 0) <= 0:
            return "单价要大于 0"
        due = float(values.get("weight") or 0) * float(values.get("price") or 0)
        if float(values.get("paid") or 0) - due > 0.005:
            return f"实收 {float(values.get('paid')):,.2f} 大于应收 {due:,.2f}，核对一下单价或实收"
        return ""

    def save_record(self, data: dict, rid: int | None) -> dict:
        weight = float(data.get("weight") or 0)
        price = float(data.get("price") or 0)
        payload = {
            "store_id": self.store_id,
            "date": data.get("date"),
            "target": data.get("target") or "",
            "batch_id": int(data.get("batch_id") or 0),
            "product": data.get("product") or "",
            "count": float(data.get("count") or 0),
            "weight": weight,
            "price": price,
            "due": r2(weight * price),
            "paid": float(data.get("paid") or 0),
            "pay_method": data.get("pay_method") or "",
            "customer": data.get("customer") or "",
            "phone": data.get("phone") or "",
            "salesman": data.get("salesman") or "",
            "remark": data.get("remark") or "",
        }
        return repo.save_row(self.ctx.conn, "store_sale", payload, rid)

    def delete_record(self, rid: int) -> None:
        repo.delete_row(self.ctx.conn, "store_sale", rid)


class StoreStockPage(_StorePage):
    TITLE = "结存/盘点台账"
    MODULE = "store_stock"
    EXPORT_STEM = "门店结存盘点台账"
    ROW_NAME = "盘点行"
    KEYWORD_TIP = "商品 / 存放地点…"
    HELP_HTML = HELP_STOCK
    SUM_KEYS = (("count", "int"), ("weight", "qty"), ("_amount", "money"))
    FIELDS = [
        FieldSpec("date", "盘点日期", "date", 106, "center"),
        FieldSpec("batch", "批次", "batch", 146, required=True),
        FieldSpec("location", "存放地点", "combo", 96, options=STOCK_LOCATIONS),
        FieldSpec("product", "商品名称", "product", 112, required=True),
        FieldSpec("count", "库存(只)", "int", 80, "right"),
        FieldSpec("weight", "库存(kg)", "num", 88, "right"),
        FieldSpec("price", "单价", "money", 80, "right"),
        FieldSpec("_amount", "库存金额", "computed", 100, "right", decimals=2),
        FieldSpec("remark", "备注", "text", 140, stretch=True),
    ]

    def extra_buttons(self):
        self.btn_fill = button("按账面生成", "Gold", self.on_fill,
                               tip="把「入库 − 销售」的账面库存拉成草稿行，再改成实盘数")
        return [self.btn_fill]

    def fetch(self) -> list[dict]:
        return calc.store_stock_rows(self.ctx.conn, self.store_id, self.d1, self.d2, self.keyword)

    def blank(self) -> dict:
        data = super().blank()
        opts = repo.batch_options(self.ctx.conn)
        data.update({
            "batch_id": opts[0][1] if opts else 0, "location": "冷藏库", "product": "",
            "count": 0.0, "weight": 0.0, "price": 0.0, "remark": "",
        })
        return data

    def recalc(self, values: dict, base: dict | None) -> dict:
        return {"_amount": r2(float(values.get("weight") or 0) * float(values.get("price") or 0))}

    def validate(self, values: dict) -> str:
        if not int(values.get("batch_id") or 0):
            return "先选一个羊群批次"
        if not str(values.get("product") or "").strip():
            return "商品名称不能为空"
        if float(values.get("weight") or 0) <= 0:
            return "库存 kg 要大于 0（这项没有库存就别登记这一行）"
        return ""

    def save_record(self, data: dict, rid: int | None) -> dict:
        payload = {
            "store_id": self.store_id,
            "date": data.get("date"),
            "batch_id": int(data.get("batch_id") or 0),
            "location": data.get("location") or "",
            "product": data.get("product") or "",
            "count": float(data.get("count") or 0),
            "weight": float(data.get("weight") or 0),
            "price": float(data.get("price") or 0),
            "remark": data.get("remark") or "",
        }
        return repo.save_row(self.ctx.conn, "store_stock", payload, rid)

    def delete_record(self, rid: int) -> None:
        repo.delete_row(self.ctx.conn, "store_stock", rid)

    # ---------------------------------------------------------- 按账面生成
    def on_fill(self) -> None:
        day = self.d2
        rows = repo.build_stocktake_rows(self.ctx.conn, self.store_id, day)
        if not rows:
            self.notify("账面没有可盘的商品（这家店还没入库过？）", "warn")
            return
        existing = {(int(r.get("batch_id") or 0), str(r.get("product") or ""))
                    for r in self.ctx.conn.rows(T_SSTOCK)
                    if int(r.get("store_id") or 0) == self.store_id and str(r.get("date")) == day}
        todo = [r for r in rows if (int(r.get("batch_id") or 0), str(r.get("product") or ""))
                not in existing]
        if not todo:
            self.notify(f"{day} 的账面库存已经生成过盘点行，不用重复生成", "warn")
            return
        if not confirm(self, "按账面生成盘点",
                       f"{day} 按账面库存生成 {len(todo)} 行盘点草稿？\n"
                       "生成后把「库存 kg」改成实盘数即可。"):
            return
        for row in todo:
            repo.save_row(self.ctx.conn, T_SSTOCK, row, None)
        self.refresh()
        self.ctx.changed()
        info(self, "按账面生成", f"已生成 {len(todo)} 行盘点草稿（盘点日期 {day}）。")
