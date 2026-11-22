"""活羊入库&结余：采购入库批次 + 入栏金额 / 当前存栏 / 暂养结余。

界面照「养殖记录」那一套行内台账来：序号列带「＋」插行、双击就地改、操作列只留一枚
多功能集（删除），改完点别处自动存。批次是整本账的主线（暂养、养殖、屠宰、门店入库
全挂批次），所以入库日期摆在首列，看着就是一笔一笔按日子排下来的采购。

金额与结余都不落库、现算：
    入栏金额 = 入栏 kg × 入栏均价
    当前存栏 = 养殖记录最后一行的期末存栏
    暂养结存 = 累计入库 kg − 累计出库 kg
"""

from __future__ import annotations

from pathlib import Path

from mscm import config
from mscm.core import calc, repo
from mscm.core.models import SHEEP_CATEGORIES, r2, today
from mscm.core.services import export as xl_export
from mscm.ui.dialogs import info
from mscm.ui.pages.base_ledger import FieldSpec, InlineLedgerPage

TITLE = "活羊入库&结余"

HELP = (
    "<b>批次是这本账的主线</b>　暂养出入库、养殖、屠宰、门店入库、盘点，全都挂批次；"
    "一个批次一份台账，不同批次不得混填。<br>"
    "<b>入库日期摆首列</b>　按日子排下来就是一笔一笔的采购；批次编号跟着日期自动生成，"
    "8 位「年月日」：2026 年 11 月 15 日 → <b>20261115</b>，同一天进两批为 <b>20261115-2</b>。"
    "日期一改，编号保存时跟着重算，不用手填。<br>"
    "<b>入库日期＝进场日期</b>　暂养台账里这一批的入库行就用这个日期，"
    "供应商 / 只数 / kg / 单价也直接取本页，台账里不再重复录入。<br>"
    "<b>标识 / 圈号</b>　耳标号段与暂养圈号；暂养出入库台账里的「标识」「圈号」两列直接取这里。<br>"
    "<b>入栏只数</b>　批次进场时的只数，养殖记录第一行的「期初存栏」就用它。<br>"
    "<b>入栏均价</b>　用于计算入栏金额，也是暂养台账加权平均的第一笔。<br>"
    "<b>这批采购的应付</b>　入栏金额（kg × 均价）按「一次采购一张单」自动提取成应付单，"
    "不用另外录；进价 / 供应商 / 日期改了，应付单跟着变。<br>"
    "<b>当前存栏 / 暂养结存</b>　现算的两列：存栏取养殖记录最后一行期末只数，"
    "结存取暂养台账的累计入库 kg − 累计出库 kg。<br>"
    "<b>电话 / 状态</b>　这两列不在这页摆了：供应商电话到「应付款项」那页手填"
    "（批次上以前填过的仍会带过去）；状态不影响任何结存计算，老数据原样保留。<br>"
    "<b>怎么改</b>　双击一行就地改，改完点别处自动存；鼠标移到序号上点「＋」，"
    "在这一行下面插一批新的采购。"
)


class BatchInUse(Exception):
    """批次已被台账引用，不能删。"""


class BatchPage(InlineLedgerPage):
    TITLE = TITLE
    MODULE = "batches"
    EXPORT_STEM = "活羊入库&结余"
    ROW_NAME = "入库批次"
    KEYWORD_TIP = "批次编号 / 品类 / 供应商…"
    NEW_TIP = "在首行插入一批新的采购入库；填完点别处自动保存"

    DATE_FILTER = False             # 批次不是按日结的，不摆业务期间
    BATCH_FILTER = False            # 这批档案本身就是批次，不用再按批次筛
    BATCH_OPTIONAL = False
    SUM_KEYS = (("count", "int"), ("weight", "qty"), ("_amount", "money", "入栏金额"))

    HELP_HTML = HELP

    FIELDS = [
        FieldSpec("entry_date", "入库日期", "date", 122, "center"),
        FieldSpec("code", "批次编号", "ro_text", 104, "center"),
        FieldSpec("category", "羊群品类", "combo", 86, "center", options=SHEEP_CATEGORIES),
        FieldSpec("pen", "圈号", "text", 62, "center", placeholder="如 A1"),
        FieldSpec("supplier", "供应商", "text", 124),
        FieldSpec("tag", "标识", "text", 96, placeholder="耳标号段"),
        FieldSpec("count", "入栏(只)", "int", 78, "right"),
        FieldSpec("weight", "入栏(kg)", "num", 82, "right"),
        FieldSpec("price", "入栏均价", "money", 84, "right"),
        FieldSpec("_amount", "入栏金额", "computed", 94, "right", decimals=2),
        FieldSpec("_stock", "当前存栏(只)", "computed", 96, "right", decimals=0),
        FieldSpec("_bal_weight", "暂养结存(kg)", "computed", 100, "right", decimals=1),
        FieldSpec("remark", "备注", "text", 100, stretch=True),
    ]

    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self.card.set_title("批次明细")

    # ---------------------------------------------------------- 取数
    def fetch(self) -> list[dict]:
        kw = self.keyword
        rows = repo.list_batches(self.ctx.conn)
        if kw:
            rows = [r for r in rows
                    if kw in " ".join(str(r.get(k) or "") for k in
                                      ("code", "category", "supplier", "pen", "tag", "entry_date"))]
        bal = {b.batch_id: b for b in calc.batch_balances(self.ctx.conn)}
        out: list[dict] = []
        for r in rows:
            bid = int(r.get("id") or 0)
            rec = dict(r)
            b = bal.get(bid)
            rec["_amount"] = r2(float(r.get("weight") or 0) * float(r.get("price") or 0))
            rec["_stock"] = calc.current_stock(self.ctx.conn, bid)
            rec["_bal_weight"] = b.weight if b else 0.0
            out.append(rec)
        return out

    def blank(self) -> dict:
        day = self.ctx.biz_date
        return {
            "id": 0, "entry_date": day,
            "code": repo.batch_code_for(self.ctx.conn, day),
            "category": SHEEP_CATEGORIES[0], "pen": "", "supplier": "",
            "tag": "", "count": 0.0, "weight": 0.0, "price": 0.0,
            "_amount": 0.0, "_stock": 0.0, "_bal_weight": 0.0,
            "remark": "",
        }

    # ---------------------------------------------------------- 现算
    def recalc(self, values: dict, base: dict | None) -> dict:
        entry = str(values.get("entry_date") or today())
        rid = int((base or {}).get("id") or 0)
        weight = float(values.get("weight") or 0)
        price = float(values.get("price") or 0)
        return {
            "code": repo.batch_code_for(self.ctx.conn, entry, exclude_id=rid or None),
            "_amount": r2(weight * price),
        }

    def validate(self, values: dict) -> str:
        if not str(values.get("entry_date") or "").strip():
            return "先填入库日期"
        if float(values.get("count") or 0) <= 0:
            return "入栏只数要大于 0"
        if float(values.get("price") or 0) > 0 and float(values.get("weight") or 0) <= 0:
            return "填了入栏均价，就要填入栏重量(kg)"
        return ""

    # ---------------------------------------------------------- 落库
    def save_record(self, data: dict, rid: int | None) -> dict:
        weight = float(data.get("weight") or 0)
        price = float(data.get("price") or 0)
        # 电话 / 状态不再在本页录：老批次上已经有的值原样留着（应付款、对账单还要用），别被空值抹掉
        old = (repo.get_batch(self.ctx.conn, rid) or {}) if rid else {}
        phone = str(old.get("supplier_phone") or "")
        status = str(old.get("status") or "在养")
        payload = {
            "entry_date": str(data.get("entry_date") or self.ctx.biz_date),
            "category": str(data.get("category") or ""),
            "pen": str(data.get("pen") or ""),
            "supplier": str(data.get("supplier") or ""),
            "supplier_phone": phone,
            "tag": str(data.get("tag") or ""),
            "count": float(data.get("count") or 0),
            "weight": weight,
            "price": price,
            "amount": r2(weight * price),
            "status": status,
            "remark": str(data.get("remark") or ""),
        }
        return repo.save_batch(self.ctx.conn, payload, rid)

    def delete_record(self, rid: int) -> None:
        ok, msg = repo.delete_batch(self.ctx.conn, rid)
        if not ok:
            raise BatchInUse(msg)

    def _apply_delete(self, rec: dict, push: bool = True) -> None:
        """批次被台账引用了就拦下来，别把台账挂成孤儿。"""
        try:
            super()._apply_delete(rec, push)
        except BatchInUse as exc:
            info(self, "不能删除", str(exc))

    # ---------------------------------------------------------- 文案
    def row_label(self, rec: dict) -> str:
        return f"{rec.get('entry_date') or ''}　{rec.get('code') or ''}　{rec.get('category') or ''}"

    def card_hint(self) -> None:
        extra = "　·　已按关键词筛" if self.keyword else ""
        self.card.set_hint(f"共 {len(self._rows)} 个批次{extra}　·　双击一行就地编辑，改完点别处即存"
                           f"　·　序号「＋」插一批新的采购")

    # ---------------------------------------------------------- 导出
    def on_export(self) -> None:
        self._settle_edit()
        if not self._rows:
            self.notify("当前筛选没有可导出的批次", "warn")
            return
        config.ensure_dirs()
        path = Path(config.EXPORT_DIR) / f"活羊入库&结余-{today()}.xlsx"
        xl_export.export_batches(path, self._rows)
        self.notify(f"已导出：{path.name}")
        info(self, "导出完成", f"已导出 {len(self._rows)} 个批次到：\n{path}")
