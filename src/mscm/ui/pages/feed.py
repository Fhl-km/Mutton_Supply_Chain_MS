"""屠宰场暂养出入库台账（活羊采购 & 屠宰 › 第二张台账）。

入库不再在这里手录：一个批次的采购数据（供应商 / 只数 / kg / 单价）存在
「活羊入库&结余」档案里，这里按批次自动生成**一行入库行**，只读展示；
其余行都是出库行（屠宰领用 / 转栏 / 死亡损耗 / 退回）。

这样只有一个数据源：改批次档案 → 入库行跟着变，台账里不会出现两份进价。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit, QWidget

from mscm.core import calc, repo
from mscm.core.models import FEED_OUT_USES, r1, r2
from mscm.ui.pages.base_ledger import RO_QSS, FieldSpec, InlineLedgerPage
from mscm.ui.widgets import button

HELP = (
    "<b>这张表记什么</b>　活羊进场（入库）到送去屠宰（出库）之间，暂养圈里每一笔进出。<br>"
    "<b>表头照纸质表</b>　两行式：上一行分「入库 / 出库 / 结余」三块，下一行是各列名。<br>"
    "<b>入库从哪来</b>　日期 / 圈号 / 标识 / 供应商 / 只数 / kg / 单价<b>直接取「活羊入库&amp;结余」</b>，"
    "每批自动生成一行入库行；日期与这几列都是灰底只读的——要改就回「活羊入库&amp;结余」改，改完这行跟着变。<br>"
    "<b>出库</b>　按天登记：用途、只数、kg；金额按该批次累计入库的加权平均单价结转。<br>"
    "<b>入库金额</b>　= 入库 kg × 平均单价；<b>出库金额</b>　= 出库 kg × "
    "<b>该批次累计入场的加权平均单价</b>（不是固定价，也不是最后一次进价）。<br>"
    "<b>当日结存</b>　= 该批次截至本行的累计（入库 − 出库），只数 / kg / 金额三列同步。<br>"
    "<b>出库用途</b>　屠宰领用 / 转栏 / 死亡损耗 / 退回供应商；死亡损耗只减只数与 kg，"
    "金额照常按加权平均结转。<br>"
    "<b>就地改</b>　双击一行进入编辑，改完点别处（换行 / 换页 / 点空白）即自动保存，"
    "按 Esc 放弃本次改动。<br>"
    "<b>插一行</b>　鼠标移到行号上，左下角冒出「＋」，点它就在这一行下面插一行出库行。<br>"
    "<b>删错了</b>　行尾「多功能集」里删行；撤消 / 恢复在窗口最上排那三个小图标里，"
    "删掉的行点「撤消」原样捡回来。<br>"
    "<b>排序筛选</b>　点表头右侧的小三角，可以按这一列升序 / 降序，也可以只看某一个日期、"
    "某一个批次；排过序列头显示 ▲▼，筛过值显示金色漏斗。"
)

IN_KEYS = ("in_supplier", "in_tag", "in_count", "in_weight", "in_price")


class FeedPage(InlineLedgerPage):
    TITLE = "屠宰场暂养出入库台账"
    MODULE = "feed"
    EXPORT_STEM = "屠宰场暂养出入库台账"
    ROW_NAME = "出入库记录"
    BATCH_FILTER = True           # 台账按批次成册，默认看全部，选批次可只看一批
    KEYWORD_TIP = "供应商 / 标识 / 用途…"
    HELP_HTML = HELP
    SUM_KEYS = (("in_count", "int", "入库(只)"), ("in_weight", "qty", "入库(kg)"),
                ("_in_amount", "money", "入库金额"), ("out_count", "int", "出库(只)"),
                ("out_weight", "qty", "出库(kg)"), ("_out_amount", "money", "出库金额"))
    # 两行式表头：日期 / 批次 / 圈号 / 品类 各占一格，入库 6 列、出库 4 列、结余 3 列
    HEADER_GROUPS = (("入库", 5, 10), ("出库", 11, 14), ("结余", 15, 17))
    FIELDS = [
        FieldSpec("date", "日期", "date", 108, "center"),
        FieldSpec("batch", "羊群批次", "batch", 122, "center"),
        FieldSpec("_pen", "圈号", "ro_text", 58, "center"),
        FieldSpec("category", "羊群品类", "ro_text", 88, "center"),
        FieldSpec("in_supplier", "供应商", "text", 108, placeholder="取自批次"),
        FieldSpec("in_tag", "标识", "text", 92, placeholder="取自批次"),
        FieldSpec("in_count", "数量\n(只)", "int", 66, "right"),
        FieldSpec("in_weight", "数量\n(kg)", "num", 78, "right"),
        FieldSpec("in_price", "平均单价\n(元/kg)", "money", 104, "right"),
        FieldSpec("_in_amount", "金额", "computed", 100, "right", decimals=2),
        FieldSpec("out_use", "用途", "combo", 82, options=FEED_OUT_USES),
        FieldSpec("out_count", "数量\n(只)", "int", 66, "right"),
        FieldSpec("out_weight", "数量\n(kg)", "num", 78, "right"),
        FieldSpec("_out_amount", "金额", "computed", 100, "right", decimals=2),
        FieldSpec("_bal_count", "数量\n(只)", "computed", 66, "right", decimals=0),
        FieldSpec("_bal_weight", "数量\n(kg)", "computed", 78, "right"),
        FieldSpec("_bal_amount", "金额", "computed", 100, "right", decimals=2),
        FieldSpec("remark", "备注", "text", 84, stretch=True),
    ]

    def fetch(self) -> list[dict]:
        rows = calc.feed_ledger(self.ctx.conn, self.d1, self.d2, self.batch_id, self.keyword)
        return sorted(rows, key=lambda r: (int(r.get("batch_id") or 0),
                                           str(r.get("date") or ""), int(r.get("id") or 0)))

    def blank(self) -> dict:
        opts = repo.batch_options(self.ctx.conn)
        bid = opts[0][1] if opts else 0
        return {
            "id": 0, "date": self.ctx.biz_date, "batch_id": bid, "row_kind": "out",
            "category": repo.batch_category(self.ctx.conn, bid),
            "in_supplier": "", "in_tag": "", "in_count": 0.0, "in_weight": 0.0, "in_price": 0.0,
            "out_use": "", "out_count": 0.0, "out_weight": 0.0, "remark": "",
        }

    # ---------------------------------------------------------- 入库行只读、取自批次
    def locked_keys(self, rec: dict) -> set[str]:
        """入库行的日期与入库数值一律来自批次档案，编辑时锁死；出库行只锁入库那几列。"""
        if str(rec.get("row_kind") or "out") == "in":
            return set(IN_KEYS) | {"date"}
        return set(IN_KEYS)

    def _make_editor(self, spec: FieldSpec, rec: dict) -> QWidget:
        # 入库行的日期＝批次的采购入库日期：用一行灰底文字显示，别摆日历框（日期框在窄列里挤）
        if spec.key == "date" and str(rec.get("row_kind") or "out") == "in":
            edit = QLineEdit(str(rec.get("date") or ""))
            edit.setAlignment(Qt.AlignCenter)
            edit.setReadOnly(True)
            edit.setFocusPolicy(Qt.NoFocus)
            edit.setStyleSheet(RO_QSS)
            return edit
        w = super()._make_editor(spec, rec)
        if spec.key in IN_KEYS and isinstance(w, QLineEdit):
            if str(rec.get("row_kind") or "out") != "in":
                w.clear()                   # 出库行不摆入库数字，免得看着像重复入库
            w.setReadOnly(True)
            w.setFocusPolicy(Qt.NoFocus)
            w.setStyleSheet(RO_QSS)
        return w

    def recalc(self, values: dict, base: dict | None) -> dict:
        bid = int(values.get("batch_id") or 0)
        is_in = str((base or {}).get("row_kind") or "out") == "in"
        patch: dict[str, Any] = {"category": repo.batch_category(self.ctx.conn, bid)}
        if is_in:
            batch = repo.get_batch(self.ctx.conn, bid) or {}
            patch["in_supplier"] = str(batch.get("supplier") or "")
            patch["in_count"] = float(batch.get("count") or 0)
            patch["in_weight"] = float(batch.get("weight") or 0)
            patch["in_price"] = float(batch.get("price") or 0)
            values = dict(values)
            values.update({"in_count": patch["in_count"], "in_weight": patch["in_weight"],
                           "in_price": patch["in_price"]})

        in_w = float(values.get("in_weight") or 0)
        in_p = float(values.get("in_price") or 0)
        patch["_in_amount"] = r2(in_w * in_p)
        # 出库金额：本次入库有单价就用本次，否则用批次累计加权平均（保存后按逐日累计重算）
        price = in_p or calc.batch_avg_price(self.ctx.conn, bid)
        out_w = float(values.get("out_weight") or 0)
        patch["_out_amount"] = r2(out_w * price)

        base = base or {}
        open_c = open_w = open_a = 0.0
        if base.get("id"):
            # 编辑已有行：先把它自己上一次的影响扣掉，再加本次
            open_c = float(base.get("_bal_count") or 0) - float(base.get("in_count") or 0) \
                + float(base.get("out_count") or 0)
            open_w = float(base.get("_bal_weight") or 0) - float(base.get("in_weight") or 0) \
                + float(base.get("out_weight") or 0)
            open_a = float(base.get("_bal_amount") or 0) - float(base.get("_in_amount") or 0) \
                + float(base.get("_out_amount") or 0)
        patch["_bal_count"] = r1(open_c + float(values.get("in_count") or 0)
                                 - float(values.get("out_count") or 0))
        patch["_bal_weight"] = r1(open_w + in_w - out_w)
        patch["_bal_amount"] = r2(open_a + patch["_in_amount"] - patch["_out_amount"])
        return patch

    def validate(self, values: dict) -> str:
        if not int(values.get("batch_id") or 0):
            return "先选一个羊群批次"
        if str(getattr(self, "_base", {}).get("row_kind") or "out") == "in":
            batch = repo.get_batch(self.ctx.conn, int(values.get("batch_id") or 0)) or {}
            if float(batch.get("count") or 0) <= 0:
                return "这个批次的入栏只数还是 0，先去「活羊入库&结余」补上"
            return ""
        out_c = float(values.get("out_count") or 0)
        out_w = float(values.get("out_weight") or 0)
        if out_c <= 0 and out_w <= 0:
            return "出库只数 / kg 至少填一个；要记入库请到「活羊入库&结余」登记"
        if out_c > 0 and out_w <= 0:
            return "有出库只数就要填出库 kg"
        if out_w > 0 and out_c <= 0:
            return "有出库 kg 就要填出库只数"
        if not str(values.get("out_use") or "").strip():
            return "出库要选用途（屠宰领用 / 转栏 / 死亡损耗 / 退回供应商）"
        return ""

    def save_record(self, data: dict, rid: int | None) -> dict:
        bid = int(data.get("batch_id") or 0)
        payload = {
            "date": data.get("date"),
            "batch_id": bid,
            "category": repo.batch_category(self.ctx.conn, bid),
            "row_kind": str(getattr(self, "_base", {}).get("row_kind") or "out"),
            "in_supplier": data.get("in_supplier") or "",
            "in_tag": data.get("in_tag") or "",
            "in_count": float(data.get("in_count") or 0),
            "in_weight": float(data.get("in_weight") or 0),
            "in_price": float(data.get("in_price") or 0),
            "out_use": data.get("out_use") or "",
            "out_count": float(data.get("out_count") or 0),
            "out_weight": float(data.get("out_weight") or 0),
            "remark": data.get("remark") or "",
        }
        return repo.save_row(self.ctx.conn, "feed", payload, rid)

    def delete_record(self, rid: int) -> None:
        repo.delete_row(self.ctx.conn, "feed", rid)

    # ---------------------------------------------------------- 专用按钮
    def extra_buttons(self) -> list[QWidget]:
        return [button("从批次补入库", "", self.on_sync_inbound,
                       tip="给还没有入库行的批次按「活羊入库&结余」补一行；已有入库行不动")]

    def on_sync_inbound(self) -> None:
        made = repo.ensure_feed_inbound(self.ctx.conn)
        self.refresh()
        self.notify(f"已按批次补 {made} 行入库" if made else "各批次的入库行都齐了")
