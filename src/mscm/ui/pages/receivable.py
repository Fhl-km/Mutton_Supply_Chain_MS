"""应收款项：应收款（含逐笔收款）/ 未收款两张表。

两套账共用这一页（页内两个页签，结构完全一样，只是 biz 不同）：

    屠宰销售    活羊采购 & 屠宰 › 应收款项 · 屠宰销售
                 屠宰场直接对外销售（出库去向＝对外销售 / 客户直供）挂的账
    门店销售    门店管理 › 关一店 › 应收款项
                 门店对外销售挂的账

口径（2026-11 按客户要求改成「自动提取 + 逐笔登记收款」）：

    应收款   不手填。屠宰出库明细里「收款方式＝挂账 / 月结」的销售行自动提取成应收单，
             门店销售取「应收 − 实收」的差额；销售单改了金额 / 客户 / 日期，应收跟着变。
             销售批次 = 销售类型编码 + 销售日期：对外销售 T、内部调拨 N，如 T20261115；
             销售日期就是销售批次的后 8 位。
    已收款   不单独成表，按「一对多」挂在应收单下面：一张单收了三次就有三条收款行。
             收款日期 / 收款金额由出纳照银行流水分笔登记，未收金额自动往下减。
    未收款   现算、只读：应收 − 已收 的余额，带账龄与逾期天数。

为什么未收不按期间切：未收是**余额**，上月的欠款不会因为换个月就消失；
应收按期间看发生额，未收看截至业务日期的余额，两者才勾得上。
"""

from __future__ import annotations

from pathlib import Path

import re

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QCheckBox, QDialog, QMenu, QTabWidget, QVBoxLayout, QWidget

from mscm import config
from mscm.core import calc, repo
from mscm.core.models import (
    AR_BIZ_SLAUGHTER, AR_BIZ_STORE, SETTLE_METHODS, T_AR, T_ARR,
    month_start, r2, sale_batch_code, sale_batch_date, settle_due_date,
)
from mscm.core.services import export as xl_export
from mscm.ui import icons, theme
from mscm.ui.dialogs import Field, FormDialog, info
from mscm.ui.pages.base_ledger import FieldSpec, InlineLedgerPage, SeqCell
from mscm.ui.widgets import (
    Column, DataTable, FilterStrip, HelpPanel, PageBase, SumBar,
    button, label, money, search_input,
)

HELP_MAIN = (
    "<b>这一页是什么</b>　应收款项分两套账：<b>屠宰销售</b>（屠宰场直接对外销售挂的账）、"
    "<b>门店销售</b>（门店对外销售挂的账）。每套账两张表——应收款、未收款。<br>"
    "<b>应收款是自动提取的，不用手填</b>　屠宰出库明细里「收款方式＝挂账（或月结）」的销售行，"
    "进这一页就自动变成一张应收单；门店销售取「应收 − 实收」的差额。"
    "销售单改了金额、客户、日期，应收单跟着变；要补一张手工应收，点右上「＋ 新增」。<br>"
    "<b>自动提取的行改了没用</b>　销售批次、应收金额是跟着销售单走的（灰底只读）；"
    "要改就回「屠宰出库明细」改销售单，这一页跟着变。<br>"
    "<b>销售批次</b>　= 销售类型编码 + 销售日期：<b>对外销售 T</b>、<b>内部调拨 N</b>，"
    "如 <b>T20261115</b>。销售日期就是批次的后 8 位，改批次等于同时改了日期。<br>"
    "<b>结算方式</b>　从「客户名录」里带：名录里这位客户记的是周结，这里就是周结。<br>"
    "<b>约定收款日是算出来的</b>　= 销售日期 + 账期（现结 / 预付 0 天、周结 7 天、"
    "半月结 15 天、月结 30 天）。客户另有约定的，直接在格子里改成实际日子，改过的不再被覆盖。<br>"
    "<b>收款怎么登</b>　应收单行右侧「多功能集 › 记一笔收款」，或点<b>已有收款行</b>前面的「＋」，"
    "就能在同一张单下面再加一笔；收款日期、已收金额、抹零金额照<b>银行流水</b>填，"
    "未收金额自动往下减。应收单那行的「已收金额」「抹零金额」是下面几笔的<b>小计</b>。<br>"
    "<b>抹零金额</b>　银行到账时把零头抹掉的（应收 6,232、实到 6,200，抹零 32），"
    "跟那笔收款一起填；<b>未收金额 = 应收金额 − 已收金额 − 抹零金额</b>。<br>"
    "<b>收多了怎么办</b>　已收＋抹零 大于应收时，未收金额会变成<b>负数</b>（绿字），"
    "那部分就是<b>预收款</b>——客户先给钱后拿货，不用另建一张单去装它；"
    "「数据校验」页会把预收单独提示一条。<br>"
    "<b>未收款</b>　不用录：未收 = 应收金额 − 已收金额（小计）− 抹零金额，带账龄（销售日期到今天）"
    "与逾期天数（约定收款日到今天）。这张表的数据全部取自「应收款明细」里未收大于 0 的行，"
    "不另存一份，那边改了这边跟着变。<br>"
    "<b>生成对账单</b>　选一个还欠钱的客户、填上对账联系人与电话，就能出一张 A4 对账单："
    "逐笔列未收、给出合计与逾期金额，末尾留供货方盖章与客户签字的位置。<br>"
    "<b>红线</b>　删应收单会把它下面的收款一起删（收款没有主单就说不清是哪笔账），"
    "删之前先确认银行那边确实没这笔钱。"
)

HELP_OPEN_EXTRA = ""

RECEIPT_COLS = {"receipt_date", "receipt_amount", "waiver", "_unpaid"}


def _subject_short(ctx, biz: str, store_id: int) -> str:
    """导出文件名里的核算主体：屠宰销售 / 门店名。"""
    if str(biz) == AR_BIZ_SLAUGHTER:
        return "屠宰销售"
    return repo.store_name(ctx.conn, store_id) or "门店"


class _ArTabBase(InlineLedgerPage):
    """两套账共用的骨架：锁 biz（与门店）、客户与结算方式下拉、导出路径。"""

    BIZ = AR_BIZ_SLAUGHTER
    BATCH_FILTER = False
    HELP_HTML = ""              # 页面级说明统一由 ReceivablePage 出，避免两份重复
    CARD_TITLE = "台账明细"

    def __init__(self, ctx, parent: QWidget | None = None, store_id: int = 0,
                 biz: str = "") -> None:
        # refresh() 在基类 __init__ 里就会跑，biz 必须先落好
        self._biz = str(biz or self.BIZ)
        super().__init__(ctx, parent, store_id=store_id)
        self.card.set_title(self.CARD_TITLE)

    @property
    def biz(self) -> str:
        return self._biz

    # ---------------------------------------------------------- 下拉
    def customer_options(self) -> list[str]:
        return repo.ar_customers(self.ctx.conn, self._biz, self.store_id)

    def _options(self, spec: FieldSpec) -> list[str]:
        if spec.key == "customer":
            return self.customer_options()
        if spec.key == "settle":
            return list(SETTLE_METHODS)
        return super()._options(spec)

    # ---------------------------------------------------------- 导出
    def subject_short(self) -> str:
        return _subject_short(self.ctx, self._biz, self.store_id)

    def export_path(self, stem: str) -> Path:
        config.ensure_dirs()
        return Path(config.EXPORT_DIR) / f"{stem}-{self.subject_short()}-{self.d1}_{self.d2}.xlsx"


class ArInvoiceTab(_ArTabBase):
    """应收款：一张挂账一张单，单下面跟着它的每一笔收款（一对多）。"""

    TITLE = "应收款"
    MODULE = "ar_invoice"
    EXPORT_STEM = "应收款项-应收款"
    ROW_NAME = "应收单"
    CARD_TITLE = "应收款明细（挂账应收 + 逐笔收款）"
    KEYWORD_TIP = "客户 / 销售批次 / 商品…"
    RECEIPT_EDIT = ("receipt_date", "receipt_amount", "waiver")
    FIELDS = [
        FieldSpec("sale_batch", "销售批次", "text", 100, "center",
                  hint="类型编码 + 销售日期：对外销售 T、内部调拨 N，如 T20261115"),
        FieldSpec("customer", "客户名称", "combo", 114, options=(), editable=True, required=True),
        FieldSpec("phone", "联系电话", "text", 96),
        FieldSpec("summary", "商品 / 摘要", "text", 98),
        FieldSpec("amount", "应收金额", "money", 90, "right"),
        FieldSpec("settle", "结算方式", "combo", 84, options=SETTLE_METHODS),
        FieldSpec("due_date", "约定收款日", "date_opt", 106, "center"),
        FieldSpec("receipt_date", "收款日期", "date", 110, "center"),
        FieldSpec("receipt_amount", "已收金额", "money", 96, "right"),
        FieldSpec("waiver", "抹零金额", "money", 88, "right"),
        FieldSpec("_unpaid", "未收金额", "computed", 96, "right", decimals=2),
        FieldSpec("salesman", "业务员", "text", 62),
        FieldSpec("remark", "备注", "text", 150, stretch=True),
    ]

    # ---------------------------------------------------------- 按钮
    def extra_buttons(self):
        self.btn_sync = button("按销售挂账重算", "Gold", self.on_sync,
                               tip="按销售单的挂账部分重算应收：缺的补上，改了金额 / 客户的跟着更新")
        return [self.btn_sync]

    # ---------------------------------------------------------- 取数
    def fetch(self) -> list[dict]:
        return calc.ar_detail_rows(self.ctx.conn, self._biz, self.store_id,
                                   self.d1, self.d2, self.keyword)

    def blank(self) -> dict:
        day = self.ctx.biz_date
        return {
            "id": 0, "_kind": "invoice", "date": day,
            "sale_batch": sale_batch_code(day, ""), "customer": "", "phone": "",
            "summary": "", "amount": 0.0, "settle": "", "due_date": "",
            "receipt_date": "", "receipt_amount": 0.0, "waiver": 0.0,
            "salesman": "", "remark": "", "_received": 0.0, "_unpaid": 0.0,
        }

    # ---------------------------------------------------------- 行类型
    def locked_keys(self, rec: dict) -> set[str]:
        """自动提取出来的应收单：销售批次与金额跟销售单走，灰底只读，要改去改销售单。"""
        if str(rec.get("_kind")) == "receipt" or not int(rec.get("id") or 0):
            return set()
        if str(rec.get("link_key") or ""):
            return {"sale_batch", "amount"}
        return set()

    def editable_keys(self, rec: dict) -> set[str] | None:
        """收款行只让填「收款日期 / 收款金额」；应收单行除了这两列都能改。"""
        if str(rec.get("_kind")) == "receipt":
            return set(self.RECEIPT_EDIT)
        return {f.key for f in self.FIELDS if f.key not in self.RECEIPT_EDIT}

    def row_bg(self, rec: dict) -> str:
        return "#F4F8FD" if str((rec or {}).get("_kind")) == "receipt" else ""

    def row_label(self, rec: dict) -> str:
        if str(rec.get("_kind")) == "receipt":
            return (f"收款　{rec.get('receipt_date') or ''}　"
                    f"{money(rec.get('receipt_amount'))} 元")
        inv_id = int(rec.get("id") or 0)
        kids = [r for r in self._rows
                if str(r.get("_kind")) == "receipt" and int(r.get("invoice_id") or 0) == inv_id]
        text = (f"{rec.get('sale_batch') or ''}　{rec.get('customer') or '未填客户'}　"
                f"应收 {money(rec.get('_amount'))}　未收 {money(rec.get('_unpaid'))}")
        if kids:
            text += f"\n（这张单下面还有 {len(kids)} 笔收款，会跟着一起删）"
        return text

    def _cell(self, rec: dict, spec: FieldSpec) -> str:
        kind = str(rec.get("_kind"))
        if kind == "receipt" and spec.key not in RECEIPT_COLS:
            return ""
        if kind == "invoice":
            # 应收单这一行：「已收金额 / 抹零金额」放的是下面几笔的小计，不是某一笔到账
            if spec.key == "receipt_date":
                return "小计"
            if spec.key == "receipt_amount":
                total = r2(float(rec.get("_received") or 0))
                return money(total) if total else "—"
            if spec.key == "waiver":
                total = r2(float(rec.get("_waiver") or 0))
                return money(total) if total else "—"
        return super()._cell(rec, spec)

    def cell_color(self, rec: dict, spec) -> str:
        # 「小计」是说明字，浅一点，别跟金额抢眼
        if str(rec.get("_kind")) == "invoice" and spec.key == "receipt_date":
            return theme.MUTED
        if spec.key == "_unpaid" and float(rec.get("_unpaid") or 0) < -0.005:
            return theme.NEGATIVE        # 负数＝收多了，是预收款，用绿字跟欠款分开
        return ""

    def _collect(self) -> dict:
        """除了控件里的值，带上这一行是应收单还是收款单、认的是哪张单。"""
        values = super()._collect()
        src = getattr(self, "_base", None) or {}
        values["_kind"] = str(src.get("_kind") or "invoice")
        values["invoice_id"] = int(src.get("invoice_id") or 0)
        values["date"] = str(src.get("date") or self.ctx.biz_date)
        if not str(values.get("customer") or "").strip():
            values["customer"] = str(src.get("customer") or "")
        return values

    # ---------------------------------------------------------- 计算
    def recalc(self, values: dict, base: dict | None) -> dict:
        base = base or {}
        if str(base.get("_kind")) == "receipt":
            return {}
        amount = r2(float(values.get("amount") or 0))
        paid = r2(float(base.get("_received") or 0))
        waiver = r2(float(base.get("_waiver") or 0))
        patch: dict = {"_received": paid, "_unpaid": r2(amount - paid - waiver)}

        # 客户一换，结算方式跟客户名录走（名录里没登记就留着，让人自己选）
        if str(values.get("customer") or "").strip() != str(base.get("customer") or "").strip():
            settle = calc.customer_settle(self.ctx.conn, values.get("customer"))
            if settle:
                patch["settle"] = settle
                values["settle"] = settle

        # 约定收款日 = 销售日期（销售批次后 8 位）+ 账期；手工改过的不覆盖
        day = sale_batch_date(values.get("sale_batch")) or str(values.get("date") or "")
        auto = settle_due_date(day, str(values.get("settle") or ""))
        old_auto = settle_due_date(str(base.get("date") or ""), str(base.get("settle") or ""))
        due = str(values.get("due_date") or "").strip()
        if auto and (not due or due == old_auto):
            patch["due_date"] = auto
        return patch

    def validate(self, values: dict) -> str:
        if str(values.get("_kind")) == "receipt":
            if not str(values.get("receipt_date") or "").strip():
                return "收款日期不能为空（照银行流水那天填）"
            if float(values.get("receipt_amount") or 0) <= 0:
                return "已收金额要大于 0"
            if float(values.get("waiver") or 0) < 0:
                return "抹零金额不能是负数"
            return ""
        if not str(values.get("customer") or "").strip():
            return "客户名称不能为空（应收按客户归口）"
        if float(values.get("amount") or 0) <= 0:
            return "应收金额要大于 0"
        return ""

    # ---------------------------------------------------------- 落库
    def save_record(self, data: dict, rid: int | None) -> dict:
        if str(data.get("_kind")) == "receipt" or (rid is not None and int(rid) < 0):
            rid_r = abs(int(rid)) if rid is not None else None
            old = self.ctx.conn.get(T_ARR, rid_r) if rid_r else (self._base or {})
            payload = {
                "biz": self._biz,
                "store_id": int(self.store_id),
                "invoice_id": int(data.get("invoice_id") or old.get("invoice_id") or 0),
                "date": data.get("receipt_date") or self.ctx.biz_date,
                "customer": data.get("customer") or old.get("customer") or "",
                "amount": r2(float(data.get("receipt_amount") or 0)),
                "waiver": r2(float(data.get("waiver") or 0)),
                "pay_method": old.get("pay_method") or "",
                "remark": data.get("remark") or old.get("remark") or "",
            }
            saved = repo.save_ar_receipt(self.ctx.conn, payload, rid_r)
            inv = self.ctx.conn.get(T_AR, payload["invoice_id"]) or {}
            over = r2(float(payload["amount"]) + float(payload.get("waiver") or 0)
                      - float(inv.get("amount") or 0))
            if inv and over > 0.005:
                self.notify("这笔收款比应收金额还多：多出的部分在「未收金额」显示为负数，就是预收款",
                            "warn")
            return saved

        payload = {
            "biz": self._biz,
            "store_id": int(self.store_id),
            "date": data.get("date") or self.ctx.biz_date,
            "sale_batch": str(data.get("sale_batch") or "").strip(),
            "customer": str(data.get("customer") or "").strip(),
            "phone": data.get("phone") or "",
            "summary": data.get("summary") or "",
            "amount": r2(float(data.get("amount") or 0)),
            "settle": data.get("settle") or "",
            "due_date": data.get("due_date") or "",
            "salesman": data.get("salesman") or "",
            "remark": data.get("remark") or "",
        }
        old = self.ctx.conn.get(T_AR, int(rid)) if rid else None
        if old and old.get("link_key"):
            payload["link_key"] = old.get("link_key")      # 改行不能把来源关系改丢
        return repo.save_ar_invoice(self.ctx.conn, payload, rid)

    def delete_record(self, rid: int) -> None:
        if int(rid) < 0:
            repo.delete_ar_receipt(self.ctx.conn, -int(rid))
        else:
            repo.delete_ar_invoice(self.ctx.conn, rid)

    def record_id(self, saved: dict, data: dict) -> int:
        """收款行在历史栈里记成负数：一张页面里混着应收单和收款单，id 会撞车。"""
        rid = int((saved or {}).get("id") or 0)
        return -rid if rid and str(data.get("_kind")) == "receipt" else rid

    # ---------------------------------------------------------- 删除 / 撤消
    def _apply_delete(self, rec: dict, push: bool = True) -> None:
        """删应收单会连它下面的收款一起删；收款跟着记进历史栈，撤消时原样挂回来。"""
        if str(rec.get("_kind")) == "receipt":
            super()._apply_delete(rec, push)
            return
        if str(rec.get("link_key") or ""):
            info(self, "这张应收单删不掉",
                 "它是销售单自动提取出来的（挂账 / 月结），删了下次进页面还会再提出来。\n\n"
                 "要它不再出现，请去「屠宰出库明细」（门店的就去「销售台账」）把那张单的"
                 "收款方式改成现款或删掉那张销售单——下次进这一页它会自动撤掉。")
            return
        rid = int(rec.get("id") or 0)
        kids = [dict(r) for r in self.ctx.conn.rows(T_ARR)
                if int(r.get("invoice_id") or 0) == rid]
        self.delete_record(rid)
        if push:
            self._push({"kind": "delete", "id": rid, "before": dict(rec), "after": None,
                        "label": "删除本行", "kids": kids})
        self._edit_id = None
        self._editors = {}
        self._edit_token += 1
        self.refresh()
        self.ctx.changed()
        self.history_changed.emit()
        self.notify("已删除" + (f"（连同 {len(kids)} 笔收款）" if kids else "")
                    + "，点顶部「撤消」可以捡回来")

    def _replay(self, cmd: dict, forward: bool) -> None:
        super()._replay(cmd, forward)
        kids = cmd.get("kids") or []
        if cmd.get("kind") != "delete" or not kids or forward:
            return                  # 重做删除时收款已随单据删掉，不用再管
        new_id = int(cmd.get("id") or 0)
        for k in kids:
            payload = {kk: vv for kk, vv in k.items()
                       if kk not in ("id", "created_at", "updated_at")}
            payload["invoice_id"] = new_id
            repo.save_ar_receipt(self.ctx.conn, payload)

    # ---------------------------------------------------------- 插行：多加一笔收款
    def blank_at(self, view_row: int) -> tuple[dict, int]:
        """点谁下面的「＋」：收款行 → 同一张单加一笔收款；应收单行 → 整张单的末尾插新单。"""
        rec = self._view[view_row] if 0 <= view_row < len(self._view) else None
        kind = str((rec or {}).get("_kind") or "")
        if kind == "receipt":
            inv_id = int(rec.get("invoice_id") or 0)
            return self._receipt_draft(inv_id), self._block_end(inv_id)
        if kind == "invoice":
            inv_id = int(rec.get("id") or 0)
            return self.blank(), self._block_end(inv_id)
        return self.blank(), max(0, min(view_row + 1, len(self._view)))

    def _block_end(self, inv_id: int) -> int:
        """这张应收单（含它下面的收款）最后一行的下一行。"""
        pos = 0
        for i, r in enumerate(self._view):
            if not r or int(r.get("id") or 0) != int(inv_id):
                continue
            if str(r.get("_kind")) != "invoice":
                continue
            pos = i + 1
            for j in range(i + 1, len(self._view)):
                nxt = self._view[j] or {}
                if (str(nxt.get("_kind")) == "receipt"
                        and int(nxt.get("invoice_id") or 0) == int(inv_id)):
                    pos = j + 1
                else:
                    break
        return pos

    def _receipt_draft(self, inv_id: int) -> dict:
        inv = next((r for r in self._rows
                    if str(r.get("_kind")) == "invoice" and int(r.get("id") or 0) == inv_id), {})
        return {
            "id": 0, "_kind": "receipt", "invoice_id": int(inv_id),
            "date": self.ctx.biz_date, "receipt_date": self.ctx.biz_date,
            "receipt_amount": 0.0, "waiver": 0.0, "amount": 0.0,
            "customer": str(inv.get("customer") or ""), "sale_batch": "",
            "settle": "", "due_date": "", "remark": "",
            "_received": 0.0, "_unpaid": 0.0,
        }

    def start_receipt(self, inv_rec: dict) -> None:
        """「记一笔收款」：在这张应收单的收款区末尾开一条新收款行。"""
        inv_id = int((inv_rec or {}).get("id") or 0)
        if not inv_id:
            return
        self._settle_edit()
        if self._draft is not None:
            self._draft_open = True
            self._edit_id = None
            self._editors = {}
            self._render()
            self._focus_first()
            self.notify("先把手上这张没保存的单据填完（同一时间只开一张）", "warn")
            return
        self._draft = self._receipt_draft(inv_id)
        self._draft_open = True
        self._draft_pos = self._block_end(inv_id)
        self._edit_id = None
        self._editors = {}
        self._render()
        row = self._editing_row()
        if row is not None:
            self.table.selectRow(row)
            anchor = self.table.item(row, 1)
            if anchor is not None:
                self.table.scrollToItem(anchor)
        self._focus_first()

    def _focus_first(self) -> None:
        w = (self._editors.get("receipt_date") or self._editors.get("sale_batch")
             or self._editors.get("customer") or next(iter(self._editors.values()), None))
        if isinstance(w, QWidget):
            w.setFocus()

    # ---------------------------------------------------------- 行头 / 序号 / 合计
    def _set_seq(self, row: int, draft: bool = False) -> None:
        """收款行不占号：序号只在应收单上，才是「第几张单」；收款行留个「＋」好加下一笔。"""
        rec = self._view[row] if 0 <= row < len(self._view) else None
        is_receipt = bool(rec) and str(rec.get("_kind")) == "receipt"
        number = "" if is_receipt else str(
            sum(1 for r in self._view[:row + 1]
                if r and str(r.get("_kind")) != "receipt"))
        cell = SeqCell(number, editable_row=not draft, draft=draft)
        cell.insertRequested.connect(lambda r=row: self.on_insert_at(r))
        self.table.setCellWidget(row, 0, cell)

    def _update_sums(self) -> None:
        invoices = [r for r in self._rows if str(r.get("_kind")) != "receipt"]
        receipts = len(self._rows) - len(invoices)
        total = sum(float(r.get("_amount") or 0) for r in invoices)
        received = sum(float(r.get("_received") or 0) for r in invoices)
        waived = sum(float(r.get("_waiver") or 0) for r in invoices)
        unpaid = sum(max(float(r.get("_unpaid") or 0), 0.0) for r in invoices)
        prepaid = sum(-min(float(r.get("_unpaid") or 0), 0.0) for r in invoices)
        tail = f"应收 {money(total)}　·　已收 {money(received)}　·　未收 {money(unpaid)}"
        if waived > 0.005:
            tail += f"　·　抹零 {money(waived)}"
        if prepaid > 0.005:
            tail += f"　·　预收 {money(prepaid)}"
        self.sums.set_text(
            f"共 {len(invoices)} 张应收单 · {receipts} 笔收款", tail)

    def card_hint(self) -> None:
        self.card.set_hint(
            f"{self.d1} 至 {self.d2}　·　应收单按销售挂账自动提取，收款照银行流水分笔登记"
            f"　·　未收 = 应收 − 已收 − 抹零，负数＝预收"
            f"　·　双击一行就地改；收款行前面「＋」＝这张单再记一笔收款")

    def _prepare(self, rows: list[dict]) -> list[dict]:
        """排序 / 筛选只作用在应收单上，收款行始终跟着自己的那张单。"""
        invoices = [r for r in rows if str(r.get("_kind")) != "receipt"]
        blocks: dict[int, list[dict]] = {}
        for r in rows:
            if str(r.get("_kind")) == "receipt":
                blocks.setdefault(int(r.get("invoice_id") or 0), []).append(r)
        out: list[dict] = []
        for inv in super()._prepare(invoices):
            out.append(inv)
            out.extend(blocks.pop(int(inv.get("id") or 0), []))
        return out

    # ---------------------------------------------------------- 菜单
    def _more_menu(self, row: int, anchor: QWidget) -> None:
        rec = self._view[row] if 0 <= row < len(self._view) else None
        if rec is None:
            return
        menu = QMenu(self)
        acts: list[tuple[object, object]] = []
        if str(rec.get("_kind")) == "invoice":
            act = menu.addAction("记一笔收款（照银行流水）")
            acts.append((act, lambda: self.start_receipt(rec)))
            menu.addSeparator()
        elif str(rec.get("_kind")) == "receipt":
            inv_id = int(rec.get("invoice_id") or 0)
            inv = next((r for r in self._rows
                        if str(r.get("_kind")) == "invoice"
                        and int(r.get("id") or 0) == inv_id), None)
            if inv is not None:
                act = menu.addAction("同一张单再记一笔收款")
                acts.append((act, lambda: self.start_receipt(inv)))
                menu.addSeparator()
        act_del = menu.addAction(icons.trash_icon(), "删除本行")
        acts.append((act_del, lambda: self.delete_row(row)))
        chosen = menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height() + 2)))
        for act, fn in acts:
            if chosen is act:
                fn()
                return

    # ---------------------------------------------------------- 同步 / 导出
    def on_sync(self) -> None:
        created, updated, cancelled = repo.sync_ar_from_sales(
            self.ctx.conn, self._biz, self.store_id)
        if not created and not updated and not cancelled:
            self.notify("应收已经和销售单对上了：没有需要补的挂账", "warn")
            return
        self.refresh()
        self.ctx.changed()
        text = f"已按销售挂账重算：新增 {created} 张、更新 {updated} 张、撤销 {cancelled} 张"
        self.notify(text)
        info(self, "按销售挂账重算", text)

    def on_export(self) -> None:
        self._settle_edit()
        if not self._rows:
            self.notify("当前筛选没有可导出的数据", "warn")
            return
        path = self.export_path(self.EXPORT_STEM)
        xl_export.export_ar_invoice(path, self.ctx.conn, self._biz, self.store_id,
                                    self.d1, self.d2)
        self.notify(f"已导出：{path.name}")
        info(self, "导出完成", f"已导出到：\n{path}")


class ArOpenTab(QWidget):
    """未收款：应收 − 已收 的余额，只读。"""

    COLS = [
        Column("序号", 44, "center"),
        Column("销售批次", 100, "center"),
        Column("客户名称", 128),
        Column("商品 / 摘要", 102),
        Column("应收金额", 92, "right"),
        Column("结算方式", 78, "center"),
        Column("约定收款日", 96, "center"),
        Column("已收金额", 88, "right"),
        Column("抹零金额", 82, "right"),
        Column("未收金额", 92, "right"),
        Column("账龄(天)", 72, "right"),
        Column("逾期(天)", 72, "right"),
        Column("客户联系电话", 108),
        Column("业务员", 64),
        Column("备注", 118, stretch=True),
    ]

    def __init__(self, ctx, biz: str, store_id: int = 0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._biz = str(biz)
        self.store_id = int(store_id or 0)
        self._rows: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(0)

        strip = FilterStrip()
        strip.add_label("截至业务日期")
        self.lbl_day = label("", "Strong")
        strip.add(self.lbl_day)
        self.f_kw = search_input("客户 / 销售批次 / 商品…", 180)
        self.f_kw.textChanged.connect(self.refresh)
        strip.add(self.f_kw)
        self.chk_overdue = QCheckBox("只看已逾期")
        self.chk_overdue.toggled.connect(self.refresh)
        strip.add(self.chk_overdue)
        strip.add(button("重置", "", self.reset))
        strip.add_stretch()
        strip.add(button("生成对账单", "Gold", self.on_statement,
                         tip="选一个还欠钱的客户，按未收款逐笔出一张对账单（A4 竖版，带签章区），"
                             "打印出来给客户核对签字"))
        strip.add(button("导出应收+未收", "", self.export_all,
                         tip="应收款（含逐笔收款）/ 未收款打成一个工作簿，月末对账一次拿走"))
        strip.add(button("导出未收款", "", self.export_open))
        strip.add(button("刷新", "Primary", self.refresh))
        root.addWidget(strip)

        self.table = DataTable(self.COLS, row_height=30)
        root.addWidget(self.table, 1)
        self.sums = SumBar(self.table)
        root.addWidget(self.sums)

    # ---------------------------------------------------------- 数据
    def refresh(self) -> None:
        as_of = self.ctx.biz_date
        self.lbl_day.setText(as_of)
        self._rows = calc.ar_open_items(
            self.ctx.conn, self._biz, self.store_id, as_of,
            self.f_kw.text().strip(), self.chk_overdue.isChecked())
        body, colors = [], {}
        for i, r in enumerate(self._rows):
            body.append([
                str(i + 1), r.get("sale_batch") or "", r.get("customer") or "—",
                r.get("summary") or "", money(r.get("_amount")), r.get("settle") or "—",
                r.get("due_date") or "", money(r.get("_received")),
                money(r.get("_waiver")) if float(r.get("_waiver") or 0) else "",
                money(r.get("_unpaid")),
                str(int(r.get("_age") or 0)),
                str(int(r.get("_overdue") or 0)) if r.get("_overdue") else "",
                r.get("phone") or "", r.get("salesman") or "", r.get("remark") or "",
            ])
            if float(r.get("_overdue") or 0) > 0:
                colors[(i, 11)] = theme.DANGER
                colors[(i, 9)] = theme.DANGER
        self.table.set_rows(
            body, self._rows, colors=colors,
            empty_text="截至这天没有未收款：要么没有挂账，要么都收清了")
        for i in range(len(body)):
            self.table.setRowHeight(i, 30)

        total = sum(float(r.get("_unpaid") or 0) for r in self._rows)
        overdue = sum(float(r.get("_unpaid") or 0) for r in self._rows
                      if float(r.get("_overdue") or 0) > 0)
        customers = len({calc.ar_customer_key(r.get("customer")) for r in self._rows})
        summary = calc.ar_summary(self.ctx.conn, self._biz, self.store_id, "", as_of, as_of)
        prepaid = float(summary.get("prepaid") or 0)
        tail = f"未收合计 {money(total)}"
        if overdue > 0.005:
            tail += f"　·　其中逾期 {money(overdue)}"
        if prepaid > 0.005:
            tail += f"　·　预收 {money(prepaid)}（应收款明细里未收为负数的行）"
        self.sums.set_text(
            f"共 {len(self._rows)} 笔 · {customers} 个客户 · 截至 {as_of}", tail)

    # ---------------------------------------------------------- 对账单
    def on_statement(self) -> None:
        """生成对账单：选客户 → 手填四个联系信息 → 照模板「对账单2」出 A4 纵向一页。"""
        names = sorted({str(r.get("customer") or "").strip() for r in self._rows} - {""})
        if not names:
            self.notify("没有可对账的客户：未收款为空，或欠款都挂在「未填客户」名下", "warn")
            return
        fields = [
            Field("customer", "客户名称", "combo", True, tuple(names),
                  hint="只列截至这天还有未收款的客户"),
            Field("as_of", "对账日期", "date", False, hint="默认业务日期"),
            Field("contact", "客户联系人", "text", False, placeholder="客户那边对接的人"),
            Field("phone", "客户联系电话", "text", False, placeholder="138xxxx / 座机"),
            Field("our_contact", "我公司联系人", "text", False, placeholder="我方业务员"),
            Field("our_phone", "我公司联系电话", "text", False, placeholder="138xxxx / 座机"),
        ]
        dlg = FormDialog(
            "生成对账单", fields,
            {"customer": names[0], "as_of": self.ctx.biz_date}, self,
            hint="四个联系人 / 电话都手工填，填什么打印什么；正文按这位客户截至对账日的"
                 "未收款逐笔列示（未收 = 应收 − 已收 − 抹零），版式照《账表记录-羊》的「对账单2」。",
        )
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        customer = str(v.get("customer") or "").strip()
        day = str(v.get("as_of") or self.ctx.biz_date)
        count = sum(1 for r in self._rows
                    if str(r.get("customer") or "").strip() == customer)
        if not count:
            self.notify(f"「{customer}」截至 {day} 没有未收款", "warn")
            return
        config.ensure_dirs()
        safe = re.sub(r'[\\/:*?"<>|]', "_", customer) or "客户"
        path = Path(config.EXPORT_DIR) / f"对账单-{safe}-{day}.xlsx"
        xl_export.export_statement(path, self.ctx.conn, self._biz, self.store_id,
                                   customer, v.get("contact") or "", v.get("phone") or "",
                                   day, v.get("our_contact") or "", v.get("our_phone") or "")
        self.notify(f"已生成对账单：{path.name}")
        info(self, "对账单已生成",
             f"客户：{customer}　·　{count} 笔未收　·　截至 {day}\n\n{path}")

    def reset(self) -> None:
        self.f_kw.blockSignals(True)
        self.f_kw.clear()
        self.f_kw.blockSignals(False)
        self.chk_overdue.blockSignals(True)
        self.chk_overdue.setChecked(False)
        self.chk_overdue.blockSignals(False)
        self.refresh()

    # ---------------------------------------------------------- 导出
    def _subject(self) -> str:
        return _subject_short(self.ctx, self._biz, self.store_id)

    def export_open(self) -> None:
        if not self._rows:
            self.notify("截至业务日期没有未收款可导出", "warn")
            return
        config.ensure_dirs()
        path = Path(config.EXPORT_DIR) / (
            f"应收款项-未收款-{self._subject()}-{self.ctx.biz_date}.xlsx")
        xl_export.export_ar_open(path, self.ctx.conn, self._biz, self.store_id,
                                 self.ctx.biz_date)
        self.notify(f"已导出：{path.name}")
        info(self, "导出完成", f"已导出到：\n{path}")

    def export_all(self) -> None:
        config.ensure_dirs()
        d2 = self.ctx.biz_date
        d1 = month_start(d2)
        path = Path(config.EXPORT_DIR) / (
            f"应收款项-应收款与未收款-{self._subject()}-{d1}_{d2}.xlsx")
        xl_export.export_receivable_workbook(path, self.ctx.conn, self._biz,
                                             self.store_id, d1, d2)
        self.notify(f"已导出：{path.name}")
        info(self, "导出完成", f"应收款（含逐笔收款）/ 未收款已导出到：\n{path}")

    def notify(self, message: str, level: str = "info") -> None:
        self.ctx.notify(message, level)


class ReceivablePage(PageBase):
    """应收款项（两张表）：屠宰销售 / 门店销售共用，靠 BIZ 区分。"""

    BIZ = AR_BIZ_SLAUGHTER
    TITLE = "应收款项"
    LEDGER = True

    def __init__(self, ctx, parent: QWidget | None = None, store_id: int = 0,
                 biz: str = "") -> None:
        super().__init__(ctx, parent)
        self.store_id = int(store_id or 0)
        self._biz = str(biz or self.BIZ)
        self._syncing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 6, 14, 4)
        root.setSpacing(0)

        self.help = HelpPanel(HELP_MAIN)
        root.addWidget(self.help)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            f"QTabWidget::pane{{border:1px solid {theme.BORDER};border-radius:8px;"
            f"background:{theme.CARD};}}"
            f"QTabBar::tab{{background:transparent;color:{theme.MUTED};padding:6px 22px;"
            f"font-size:12.5px;border-bottom:2px solid transparent;}}"
            f"QTabBar::tab:selected{{color:{theme.NAVY};font-weight:bold;"
            f"border-bottom:2px solid {theme.GOLD};}}"
            f"QTabBar::tab:hover{{color:{theme.NAVY_2};}}")
        self.tab_inv = ArInvoiceTab(ctx, store_id=self.store_id, biz=self._biz)
        self.tab_open = ArOpenTab(ctx, self._biz, self.store_id)
        self.tabs.addTab(self.tab_inv, "应收款")
        self.tabs.addTab(self.tab_open, "未收款")
        root.addWidget(self.tabs, 1)

        self.tab_inv.history_changed.connect(self.history_changed.emit)
        self.tabs.currentChanged.connect(self._on_tab_changed)

    # ---------------------------------------------------------- 刷新
    def refresh(self) -> None:
        self._sync_from_sales()
        self.tab_inv.refresh()
        self.tab_open.refresh()

    def _sync_from_sales(self) -> None:
        """进页面先把「挂账」的销售单提取成应收（幂等）：销售单改了，应收跟着变。"""
        if self._syncing:
            return
        self._syncing = True
        try:
            created, updated, cancelled = repo.sync_ar_from_sales(
                self.ctx.conn, self._biz, self.store_id)
        except Exception as exc:                    # 同步失败别把整页卡死
            self.notify(f"按挂账提取应收时出错：{exc}", "warn")
            created = updated = cancelled = 0
        finally:
            self._syncing = False
        if created or updated or cancelled:
            parts = []
            if created:
                parts.append(f"新增 {created} 张")
            if updated:
                parts.append(f"更新 {updated} 张")
            if cancelled:
                parts.append(f"撤销 {cancelled} 张（销售单已改成现款）")
            self.notify("已按销售挂账自动提取应收：" + "、".join(parts))

    def _on_tab_changed(self, _index: int) -> None:
        # 应收改完就来未收看余额，这里每次切页都重算一遍
        self.tab_open.refresh()
        self.history_changed.emit()

    # ---------------------------------------------------------- 保存 / 撤消代理
    @property
    def _ledger(self) -> InlineLedgerPage | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, InlineLedgerPage) else None

    def has_pending(self) -> bool:
        page = self._ledger
        return bool(page and page.has_pending())

    def save_pending(self) -> None:
        page = self._ledger
        if page is not None:
            page.save_pending()

    def can_undo(self) -> bool:
        page = self._ledger
        return bool(page and page.can_undo())

    def can_redo(self) -> bool:
        page = self._ledger
        return bool(page and page.can_redo())

    def undo(self) -> None:
        page = self._ledger
        if page is not None:
            page.undo()

    def redo(self) -> None:
        page = self._ledger
        if page is not None:
            page.redo()


class SlaughterReceivablePage(ReceivablePage):
    """屠宰场直接对外销售挂的应收。"""

    BIZ = AR_BIZ_SLAUGHTER
    TITLE = "应收款项 · 屠宰销售"


class StoreReceivablePage(ReceivablePage):
    """门店对外销售挂的应收（锁定门店）。"""

    BIZ = AR_BIZ_STORE
    TITLE = "应收款项"
