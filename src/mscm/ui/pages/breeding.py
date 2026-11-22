"""养殖记录：暂养圈里的存栏与投料（活羊采购 & 屠宰 › 第二张台账）。"""

from __future__ import annotations

from mscm.core import calc, repo
from mscm.core.models import BREED_OUT_USES, COMMON_MATS, MAT_UNITS, r1, r2
from mscm.ui.pages.base_ledger import FieldSpec, InlineLedgerPage

HELP = (
    "<b>这张表记什么</b>　暂养圈里每天的存栏变化与投料（玉米、羊草、兽药等），一个批次一份。<br>"
    "<b>期初存栏</b>　自动接上一行的期末；批次第一行取「活羊入库&amp;结余」里的入栏只数，不用手填。<br>"
    "<b>期末存栏</b>　= 期初存栏 − 出栏只数（自动算，改出栏立刻变）。<br>"
    "<b>出栏用途</b>　屠宰出栏 / 转栏 / 销售活羊 / 死亡损耗。"
    "走「屠宰出栏」的只数应与屠宰记录的领入只数对得上。<br>"
    "<b>投料</b>　原材料名称 / 单位 / 数量 / 单价，金额 = 数量 × 单价；"
    "同一天投几种料就登几行（每次投料一行）。<br>"
    "<b>提示</b>　存栏只算只数，不算 kg；体重口径看暂养台账的 kg 结存。"
)


class BreedingPage(InlineLedgerPage):
    TITLE = "养殖记录"
    MODULE = "breeding"
    EXPORT_STEM = "养殖记录"
    ROW_NAME = "养殖记录"
    BATCH_FILTER = True
    KEYWORD_TIP = "原材料 / 记录人…"
    HELP_HTML = HELP
    SUM_KEYS = (("out_count", "int"), ("mat_qty", "qty"), ("_mat_amount", "money"))
    FIELDS = [
        FieldSpec("date", "日期", "date", 108, "center"),
        FieldSpec("batch", "羊群批次", "batch", 148),
        FieldSpec("tag", "标识", "text", 84, placeholder="耳标"),
        FieldSpec("_open_count", "期初存栏(只)", "computed", 100, "right", decimals=0),
        FieldSpec("out_count", "出栏(只)", "int", 82, "right"),
        FieldSpec("_close_count", "期末存栏(只)", "computed", 100, "right", decimals=0),
        FieldSpec("out_use", "出栏用途", "combo", 96, options=BREED_OUT_USES),
        FieldSpec("mat_name", "原材料名称", "combo", 108, editable=True, options=COMMON_MATS),
        FieldSpec("mat_unit", "单位", "combo", 62, "center", options=MAT_UNITS),
        FieldSpec("mat_qty", "数量", "num", 76, "right"),
        FieldSpec("mat_price", "单价", "money", 76, "right"),
        FieldSpec("_mat_amount", "金额", "computed", 92, "right", decimals=2),
        FieldSpec("recorder", "记录人", "text", 80),
        FieldSpec("remark", "备注", "text", 100, stretch=True),
    ]

    def _options(self, spec: FieldSpec) -> list[str]:
        """原材料下拉：常用料在前，台账里用过的补在后面（不丢历史写法）。"""
        if spec.key == "mat_name":
            return self.common_mats()
        return super()._options(spec)

    def common_mats(self) -> list[str]:
        used = [str(r.get("mat_name")) for r in self.ctx.conn.rows("breeding") if r.get("mat_name")]
        out: list[str] = []
        for name in list(COMMON_MATS) + used:
            if name and name not in out:
                out.append(name)
        return out

    def fetch(self) -> list[dict]:
        rows = calc.breeding_ledger(self.ctx.conn, self.d1, self.d2, self.batch_id, self.keyword)
        return sorted(rows, key=lambda r: (int(r.get("batch_id") or 0),
                                           str(r.get("date") or ""), int(r.get("id") or 0)))

    def blank(self) -> dict:
        opts = repo.batch_options(self.ctx.conn)
        bid = opts[0][1] if opts else 0
        return {
            "id": 0, "date": self.ctx.biz_date, "batch_id": bid,
            "category": repo.batch_category(self.ctx.conn, bid), "tag": "",
            "out_count": 0.0, "out_use": "", "mat_name": "", "mat_unit": "kg",
            "mat_qty": 0.0, "mat_price": 0.0, "recorder": self.ctx.conn.setting("recorder", ""),
            "remark": "",
        }

    def recalc(self, values: dict, base: dict | None) -> dict:
        bid = int(values.get("batch_id") or 0)
        base = base or {}
        if base.get("id") and int(base.get("batch_id") or 0) == bid:
            open_c = float(base.get("_open_count") or 0)
        else:
            open_c = calc.current_stock(self.ctx.conn, bid)
        out_c = float(values.get("out_count") or 0)
        qty = float(values.get("mat_qty") or 0)
        price = float(values.get("mat_price") or 0)
        return {
            "_open_count": r1(open_c),
            "_close_count": r1(max(open_c - out_c, 0.0)),
            "_mat_amount": r2(qty * price),
        }

    def validate(self, values: dict) -> str:
        if not int(values.get("batch_id") or 0):
            return "先选一个羊群批次"
        out_c = float(values.get("out_count") or 0)
        if out_c > 0 and not str(values.get("out_use") or "").strip():
            return "有出栏就选用途"
        qty = float(values.get("mat_qty") or 0)
        if qty > 0 and float(values.get("mat_price") or 0) <= 0:
            return "填了投料数量就要填单价"
        if qty > 0 and not str(values.get("mat_name") or "").strip():
            return "填了投料就要写原材料名称"
        open_c = float(self._editors["_open_count"].text() or 0) if "_open_count" in self._editors else 0
        if out_c > open_c + 0.001:
            return f"出栏 {out_c:g} 只超过期初存栏 {open_c:g} 只"
        if out_c <= 0 and qty <= 0:
            return "出栏与投料都为空，这一行没有可记的内容"
        return ""

    def save_record(self, data: dict, rid: int | None) -> dict:
        bid = int(data.get("batch_id") or 0)
        payload = {
            "date": data.get("date"),
            "batch_id": bid,
            "category": repo.batch_category(self.ctx.conn, bid),
            "tag": data.get("tag") or "",
            "out_count": float(data.get("out_count") or 0),
            "out_use": data.get("out_use") or "",
            "mat_name": data.get("mat_name") or "",
            "mat_unit": data.get("mat_unit") or "kg",
            "mat_qty": float(data.get("mat_qty") or 0),
            "mat_price": float(data.get("mat_price") or 0),
            "recorder": data.get("recorder") or "",
            "remark": data.get("remark") or "",
        }
        row = repo.save_row(self.ctx.conn, "breeding", payload, rid)
        if payload["recorder"]:
            repo.set_setting(self.ctx.conn, "recorder", payload["recorder"])
        return row

    def delete_record(self, rid: int) -> None:
        repo.delete_row(self.ctx.conn, "breeding", rid)
