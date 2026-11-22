"""应付款项 · 活羊采购与付款：应付款（含逐笔付款）/ 未付款两张表。

结构完全照「应收款项 · 屠宰销售」的思路，只是方向反过来——我们欠供应商的钱：

    应付款   不手填。活羊入库&结余里每一笔采购（入栏 kg × 入栏均价）自动提取成一张应付单，
             一次采购一张单；批次的供应商 / 供应商电话 / 入库日期 / 金额改了，应付单跟着变。
             表头照《账表记录-羊.xlsx》的「应付款」：
             序号 / 入库批次 / 供应商名称 / 联系电话 / 商品 / 应付金额 / 付款日期 /
             已付款金额 / 未付款余额（另加一列备注）。
    付款     不单独成表，按「一对多」挂在应付单下面：一笔货款分三次付就有三条付款行。
             付款日期 / 已付款金额由出纳照银行流水分笔登记，未付款余额自动往下减。
    未付款   现算、只读：应付 − 已付 的余额，带账龄（入库日期到今天）；
             还欠得多的供应商可以一键出一张「采购对账单」，打印出来跟供应商核对签章。

为什么未付不按期间切：未付是**余额**，上月欠的货款不会因为换个月就不用还；
应付按期间看发生额，未付看截至业务日期的余额，两者才勾得上。
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QCheckBox, QDialog, QMenu, QTabWidget, QVBoxLayout, QWidget

from mscm import config
from mscm.core import calc, repo
from mscm.core.models import AP_ITEM_DEFAULT, T_AP, T_APP, month_start, r2
from mscm.core.services import export as xl_export
from mscm.ui import icons, theme
from mscm.ui.dialogs import Field, FormDialog, info
from mscm.ui.pages.base_ledger import FieldSpec, InlineLedgerPage, SeqCell
from mscm.ui.widgets import (
    Column, DataTable, FilterStrip, HelpPanel, PageBase, SumBar,
    button, label, money, search_input,
)

HELP_MAIN = (
    "<b>这一页是什么</b>　活羊采购与付款：一头是<b>应付</b>（进了多少羊、欠供应商多少），"
    "一头是<b>付款</b>（银行流水实际付出去多少）。两张表——应付款、未付款。<br>"
    "<b>应付款是自动提取的，不用手填</b>　「活羊入库&amp;结余」里每登记一批采购，"
    "这里就自动多一张应付单：<b>一次采购一张单</b>，应付金额 = 入栏 kg × 入栏均价。"
    "批次的进价、供应商、入库日期改了，应付单跟着变；要补一张手工应付，点右上「＋ 新增」。<br>"
    "<b>自动提取的行改了没用</b>　入库批次、应付金额是跟着「活羊入库&amp;结余」走的（灰底只读）；"
    "要改就回「活羊入库&amp;结余」改进价 / 只数 / kg，这一页跟着变。<br>"
    "<b>联系电话</b>　「活羊入库&amp;结余」不再摆电话列；批次上以前填过的电话仍会自动带过来，要补要改就在这一列手填（手填的不会被空值抹掉）。<br>"
    "<b>付款怎么登</b>　应付单行右侧「多功能集 › 记一笔付款」，或点<b>已有付款行</b>前面的「＋」，"
    "就能在同一张单下面再加一笔；付款日期、已付款金额照<b>银行流水</b>填，"
    "未付款余额自动往下减。应付单那行的「已付款金额」是下面几笔的<b>小计</b>。<br>"
    "<b>未付款余额</b>　= 应付金额 − 已付款金额（小计）。"
    "付多了会变成<b>负数</b>（绿字），那部分是<b>预付 / 多付</b>；"
    "「数据校验」页会把多付单独提示一条。<br>"
    "<b>未付款</b>　不用录：应付 − 已付 的余额，带账龄（采购入库日期到今天）。"
    "这张表的数据全部取自「应付款明细」里未付大于 0 的行，不另存一份。"
    "欠得最久的排在最前面，排付款计划按这个顺序走。<br>"
    "<b>生成采购对账单</b>　选一个还欠着钱的供应商、填上对账联系人与电话，"
    "就出一张 A4 采购对账单：逐笔列未付、给出合计与人民币大写，末尾留采购方盖章与供应商签字的位置，"
    "版式照《账表记录-羊》的「对账单2」。<br>"
    "<b>红线</b>　删应付单会把它下面的付款一起删（付款没有主单就说不清是哪笔账）；"
    "自动提取的应付单删不掉——要它不出现，去「活羊入库&amp;结余」把那一批删掉或把金额改成 0。"
)

PAY_COLS = {"pay_date", "pay_amount", "_unpaid"}
SUBTOTAL_COLS = {"pay_date", "pay_amount"}


class ApInvoiceTab(InlineLedgerPage):
    """应付款：一张采购一张单，单下面跟着它的每一笔付款（一对多）。"""

    TITLE = "应付款"
    MODULE = "ap_invoice"
    BATCH_FILTER = False            # 应付单本身就是按批次来的，不需要再筛批次
    HELP_HTML = ""                  # 页面级说明统一由 PayablePage 出，避免两份重复
    ROW_NAME = "应付单"
    EXPORT_STEM = "应付款项-应付款"
    KEYWORD_TIP = "供应商 / 入库批次 / 商品…"
    CARD_TITLE = "应付款明细（采购应付 + 逐笔付款）"
    PAY_EDIT = ("pay_date", "pay_amount")
    FIELDS = [
        FieldSpec("batch_code", "入库批次", "text", 100, "center",
                  hint="取「活羊入库&结余」的编号；手工单可以直接填批次号"),
        FieldSpec("supplier", "供应商名称", "combo", 122, options=(), editable=True,
                  required=True),
        FieldSpec("phone", "联系电话", "text", 100),
        FieldSpec("item", "商品", "text", 96),
        FieldSpec("amount", "应付金额", "money", 92, "right"),
        FieldSpec("pay_date", "付款日期", "date", 108, "center"),
        FieldSpec("pay_amount", "已付款金额", "money", 96, "right"),
        FieldSpec("_unpaid", "未付款余额", "computed", 96, "right", decimals=2),
        FieldSpec("remark", "备注", "text", 150, stretch=True),
    ]

    def __init__(self, ctx, parent: QWidget | None = None, store_id: int = 0) -> None:
        super().__init__(ctx, parent, store_id=store_id)
        self.card.set_title(self.CARD_TITLE)

    # ---------------------------------------------------------- 下拉
    def supplier_options(self) -> list[str]:
        return repo.ap_suppliers(self.ctx.conn)

    def _options(self, spec: FieldSpec) -> list[str]:
        if spec.key == "supplier":
            return self.supplier_options()
        return super()._options(spec)

    # ---------------------------------------------------------- 按钮
    def extra_buttons(self):
        self.btn_sync = button("按入库批次重算", "Gold", self.on_sync,
                               tip="按活羊入库&结余重算应付：缺的补上，改了进价 / 供应商的跟着更新")
        return [self.btn_sync]

    # ---------------------------------------------------------- 取数
    def fetch(self) -> list[dict]:
        return calc.ap_detail_rows(self.ctx.conn, self.d1, self.d2, self.keyword)

    def blank(self) -> dict:
        return {
            "id": 0, "_kind": "invoice", "date": "", "batch_id": 0, "batch_code": "",
            "supplier": "", "phone": "", "item": AP_ITEM_DEFAULT, "amount": 0.0,
            "pay_date": "", "pay_amount": 0.0, "remark": "",
            "_paid": 0.0, "_unpaid": 0.0,
        }

    # ---------------------------------------------------------- 行类型
    def locked_keys(self, rec: dict) -> set[str]:
        """自动提取出来的应付单：入库批次与金额跟批次走，灰底只读，要改去改批次。"""
        if str(rec.get("_kind")) == "payment" or not int(rec.get("id") or 0):
            return set()
        if str(rec.get("link_key") or ""):
            return {"batch_code", "amount"}
        return set()

    def editable_keys(self, rec: dict) -> set[str] | None:
        """付款行只让填「付款日期 / 已付款金额」；应付单行除了这两列都能改。"""
        if str(rec.get("_kind")) == "payment":
            return set(self.PAY_EDIT)
        return {f.key for f in self.FIELDS if f.key not in SUBTOTAL_COLS}

    def row_bg(self, rec: dict) -> str:
        return "#F4F8FD" if str((rec or {}).get("_kind")) == "payment" else ""

    def row_label(self, rec: dict) -> str:
        if str(rec.get("_kind")) == "payment":
            return (f"付款　{rec.get('pay_date') or ''}　"
                    f"{money(rec.get('pay_amount'))} 元")
        inv_id = int(rec.get("id") or 0)
        kids = [r for r in self._rows
                if str(r.get("_kind")) == "payment" and int(r.get("invoice_id") or 0) == inv_id]
        text = (f"{rec.get('batch_code') or ''}　{rec.get('supplier') or '未填供应商'}　"
                f"应付 {money(rec.get('_amount'))}　未付 {money(rec.get('_unpaid'))}")
        if kids:
            text += f"\n（这张单下面还有 {len(kids)} 笔付款，会跟着一起删）"
        return text

    def _cell(self, rec: dict, spec: FieldSpec) -> str:
        kind = str(rec.get("_kind"))
        if kind == "payment" and spec.key not in PAY_COLS:
            return ""
        if kind == "invoice":
            # 应付单这一行：「已付款金额」放的是下面几笔的小计，不是某一笔出账
            if spec.key == "pay_date":
                return "小计"
            if spec.key == "pay_amount":
                total = r2(float(rec.get("_paid") or 0))
                return money(total) if total else "—"
        return super()._cell(rec, spec)

    def cell_color(self, rec: dict, spec) -> str:
        if str(rec.get("_kind")) == "invoice" and spec.key == "pay_date":
            return theme.MUTED           # 「小计」是说明字，浅一点
        if spec.key == "_unpaid" and float(rec.get("_unpaid") or 0) < -0.005:
            return theme.NEGATIVE        # 负数＝付多了，是预付 / 多付，用绿字跟欠款分开
        return ""

    def _collect(self) -> dict:
        """除了控件里的值，带上这一行是应付单还是付款行、认的是哪张单。"""
        values = super()._collect()
        src = getattr(self, "_base", None) or {}
        values["_kind"] = str(src.get("_kind") or "invoice")
        values["invoice_id"] = int(src.get("invoice_id") or 0)
        if str(src.get("date") or ""):
            values["date"] = str(src.get("date"))
        return values

    # ---------------------------------------------------------- 计算
    def recalc(self, values: dict, base: dict | None) -> dict:
        base = base or {}
        if str(base.get("_kind")) == "payment":
            return {}
        amount = r2(float(values.get("amount") or 0))
        paid = r2(float(base.get("_paid") or 0))
        return {"_paid": paid, "_unpaid": r2(amount - paid)}

    def validate(self, values: dict) -> str:
        if str(values.get("_kind")) == "payment":
            if not str(values.get("pay_date") or "").strip():
                return "付款日期不能为空（照银行流水那天填）"
            if float(values.get("pay_amount") or 0) <= 0:
                return "已付款金额要大于 0"
            return ""
        if not str(values.get("supplier") or "").strip():
            return "供应商名称不能为空（应付按供应商归口）"
        if float(values.get("amount") or 0) <= 0:
            return "应付金额要大于 0"
        return ""

    # ---------------------------------------------------------- 落库
    def save_record(self, data: dict, rid: int | None) -> dict:
        if str(data.get("_kind")) == "payment" or (rid is not None and int(rid) < 0):
            rid_p = abs(int(rid)) if rid is not None else None
            old = self.ctx.conn.get(T_APP, rid_p) if rid_p else (self._base or {})
            payload = {
                "invoice_id": int(data.get("invoice_id") or old.get("invoice_id") or 0),
                "date": data.get("pay_date") or self.ctx.biz_date,
                "supplier": data.get("supplier") or old.get("supplier") or "",
                "amount": r2(float(data.get("pay_amount") or 0)),
                "pay_method": old.get("pay_method") or "",
                "remark": data.get("remark") or old.get("remark") or "",
            }
            saved = repo.save_ap_payment(self.ctx.conn, payload, rid_p)
            inv = self.ctx.conn.get(T_AP, payload["invoice_id"]) or {}
            over = r2(float(payload["amount"]) - float(inv.get("amount") or 0))
            if inv and over > 0.005:
                self.notify("这笔付款比应付金额还多：多出的部分在「未付款余额」显示为负数，"
                            "就是预付 / 多付", "warn")
            return saved

        payload = {
            "date": data.get("date") or "",
            "batch_code": str(data.get("batch_code") or "").strip(),
            "supplier": str(data.get("supplier") or "").strip(),
            "phone": data.get("phone") or "",
            "item": str(data.get("item") or AP_ITEM_DEFAULT).strip(),
            "amount": r2(float(data.get("amount") or 0)),
            "remark": data.get("remark") or "",
        }
        old = self.ctx.conn.get(T_AP, int(rid)) if rid else None
        if old:
            payload["batch_id"] = int(old.get("batch_id") or 0)
            if old.get("link_key"):
                payload["link_key"] = old.get("link_key")   # 改行不能把来源关系改丢
            payload["source"] = old.get("source") or "手工登记"
            payload["ref"] = old.get("ref") or ""
            payload["date"] = payload["date"] or str(old.get("date") or "")
        else:
            payload["source"] = "手工登记"
            # 能对上批次的交给 repo 取「采购入库日期」；纯手工单落在业务日期
            if not payload["batch_code"]:
                payload["date"] = payload["date"] or self.ctx.biz_date
        return repo.save_ap_invoice(self.ctx.conn, payload, rid)

    def delete_record(self, rid: int) -> None:
        if int(rid) < 0:
            repo.delete_ap_payment(self.ctx.conn, -int(rid))
        else:
            repo.delete_ap_invoice(self.ctx.conn, rid)

    def record_id(self, saved: dict, data: dict) -> int:
        """付款行在历史栈里记成负数：一页里混着应付单和付款单，id 会撞车。"""
        rid = int((saved or {}).get("id") or 0)
        return -rid if rid and str(data.get("_kind")) == "payment" else rid

    # ---------------------------------------------------------- 删除 / 撤消
    def _apply_delete(self, rec: dict, push: bool = True) -> None:
        """删应付单会连它下面的付款一起删；付款跟着记进历史栈，撤消时原样挂回来。"""
        if str(rec.get("_kind")) == "payment":
            super()._apply_delete(rec, push)
            return
        if str(rec.get("link_key") or ""):
            info(self, "这张应付单删不掉",
                 "它是入库批次自动提取出来的（一次采购一张单），删了下次进页面还会再提出来。\n\n"
                 "要它不再出现，请去「活羊入库&结余」把那一批删掉，或把入栏 kg / 均价改成 0——"
                 "下次进这一页它会自动撤掉（已经付过钱的单不会被自动撤，需先处理付款）。")
            return
        rid = int(rec.get("id") or 0)
        kids = [dict(r) for r in self.ctx.conn.rows(T_APP)
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
        self.notify("已删除" + (f"（连同 {len(kids)} 笔付款）" if kids else "")
                    + "，点顶部「撤消」可以捡回来")

    def _replay(self, cmd: dict, forward: bool) -> None:
        super()._replay(cmd, forward)
        kids = cmd.get("kids") or []
        if cmd.get("kind") != "delete" or not kids or forward:
            return                  # 重做删除时付款已随单据删掉，不用再管
        new_id = int(cmd.get("id") or 0)
        for k in kids:
            payload = {kk: vv for kk, vv in k.items()
                       if kk not in ("id", "created_at", "updated_at")}
            payload["invoice_id"] = new_id
            repo.save_ap_payment(self.ctx.conn, payload)

    # ---------------------------------------------------------- 插行：多加一笔付款
    def blank_at(self, view_row: int) -> tuple[dict, int]:
        """点谁下面的「＋」：付款行 → 同一张单加一笔付款；应付单行 → 整张单的末尾插新单。"""
        rec = self._view[view_row] if 0 <= view_row < len(self._view) else None
        kind = str((rec or {}).get("_kind") or "")
        if kind == "payment":
            inv_id = int(rec.get("invoice_id") or 0)
            return self._payment_draft(inv_id), self._block_end(inv_id)
        if kind == "invoice":
            inv_id = int(rec.get("id") or 0)
            return self.blank(), self._block_end(inv_id)
        return self.blank(), max(0, min(view_row + 1, len(self._view)))

    def _block_end(self, inv_id: int) -> int:
        """这张应付单（含它下面的付款）最后一行的下一行。"""
        pos = 0
        for i, r in enumerate(self._view):
            if not r or int(r.get("id") or 0) != int(inv_id):
                continue
            if str(r.get("_kind")) != "invoice":
                continue
            pos = i + 1
            for j in range(i + 1, len(self._view)):
                nxt = self._view[j] or {}
                if (str(nxt.get("_kind")) == "payment"
                        and int(nxt.get("invoice_id") or 0) == int(inv_id)):
                    pos = j + 1
                else:
                    break
        return pos

    def _payment_draft(self, inv_id: int) -> dict:
        inv = next((r for r in self._rows
                    if str(r.get("_kind")) == "invoice" and int(r.get("id") or 0) == inv_id), {})
        return {
            "id": 0, "_kind": "payment", "invoice_id": int(inv_id),
            "date": self.ctx.biz_date, "pay_date": self.ctx.biz_date,
            "pay_amount": 0.0, "amount": 0.0,
            "supplier": str(inv.get("supplier") or ""), "batch_code": "",
            "phone": "", "item": "", "remark": "", "_paid": 0.0, "_unpaid": 0.0,
        }

    def start_payment(self, inv_rec: dict) -> None:
        """「记一笔付款」：在这张应付单的付款区末尾开一条新付款行。"""
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
        self._draft = self._payment_draft(inv_id)
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
        w = (self._editors.get("pay_date") or self._editors.get("supplier")
             or next(iter(self._editors.values()), None))
        if isinstance(w, QWidget):
            w.setFocus()

    # ---------------------------------------------------------- 行头 / 序号 / 合计
    def _set_seq(self, row: int, draft: bool = False) -> None:
        """付款行不占号：序号只在应付单上，才是「第几张单」；付款行留个「＋」好加下一笔。"""
        rec = self._view[row] if 0 <= row < len(self._view) else None
        is_pay = bool(rec) and str(rec.get("_kind")) == "payment"
        number = "" if is_pay else str(
            sum(1 for r in self._view[:row + 1]
                if r and str(r.get("_kind")) != "payment"))
        cell = SeqCell(number, editable_row=not draft, draft=draft)
        cell.insertRequested.connect(lambda r=row: self.on_insert_at(r))
        self.table.setCellWidget(row, 0, cell)

    def _update_sums(self) -> None:
        invoices = [r for r in self._rows if str(r.get("_kind")) != "payment"]
        pays = len(self._rows) - len(invoices)
        total = sum(float(r.get("_amount") or 0) for r in invoices)
        paid = sum(float(r.get("_paid") or 0) for r in invoices)
        unpaid = sum(max(float(r.get("_unpaid") or 0), 0.0) for r in invoices)
        prepaid = sum(-min(float(r.get("_unpaid") or 0), 0.0) for r in invoices)
        tail = f"应付 {money(total)}　·　已付 {money(paid)}　·　未付 {money(unpaid)}"
        if prepaid > 0.005:
            tail += f"　·　预付 / 多付 {money(prepaid)}"
        self.sums.set_text(f"共 {len(invoices)} 张应付单 · {pays} 笔付款", tail)

    def card_hint(self) -> None:
        self.card.set_hint(
            f"{self.d1} 至 {self.d2}　·　应付单按入库批次自动提取，付款照银行流水分笔登记"
            f"　·　未付 = 应付 − 已付，负数＝预付 / 多付"
            f"　·　双击一行就地改；付款行前面「＋」＝这张单再记一笔付款")

    def _prepare(self, rows: list[dict]) -> list[dict]:
        """排序 / 筛选只作用在应付单上，付款行始终跟着自己的那张单。"""
        invoices = [r for r in rows if str(r.get("_kind")) != "payment"]
        blocks: dict[int, list[dict]] = {}
        for r in rows:
            if str(r.get("_kind")) == "payment":
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
            act = menu.addAction("记一笔付款（照银行流水）")
            acts.append((act, lambda: self.start_payment(rec)))
            menu.addSeparator()
        elif str(rec.get("_kind")) == "payment":
            inv_id = int(rec.get("invoice_id") or 0)
            inv = next((r for r in self._rows
                        if str(r.get("_kind")) == "invoice"
                        and int(r.get("id") or 0) == inv_id), None)
            if inv is not None:
                act = menu.addAction("同一张单再记一笔付款")
                acts.append((act, lambda: self.start_payment(inv)))
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
        created, updated, cancelled = repo.sync_ap_from_batches(self.ctx.conn)
        if not created and not updated and not cancelled:
            self.notify("应付已经和入库批次对上了：没有需要补的采购", "warn")
            return
        self.refresh()
        self.ctx.changed()
        text = f"已按入库批次重算：新增 {created} 张、更新 {updated} 张、撤销 {cancelled} 张"
        self.notify(text)
        info(self, "按入库批次重算", text)

    def export_path(self, stem: str) -> Path:
        config.ensure_dirs()
        return Path(config.EXPORT_DIR) / f"{stem}-{self.d1}_{self.d2}.xlsx"

    def on_export(self) -> None:
        self._settle_edit()
        if not self._rows:
            self.notify("当前筛选没有可导出的数据", "warn")
            return
        path = self.export_path(self.EXPORT_STEM)
        xl_export.export_ap_invoice(path, self.ctx.conn, self.d1, self.d2)
        self.notify(f"已导出：{path.name}")
        info(self, "导出完成", f"已导出到：\n{path}")


class ApOpenTab(QWidget):
    """未付款：应付 − 已付 的余额，只读。"""

    COLS = [
        Column("序号", 44, "center"),
        Column("入库批次", 100, "center"),
        Column("供应商名称", 132),
        Column("联系电话", 108),
        Column("商品", 96),
        Column("应付金额", 92, "right"),
        Column("已付款金额", 88, "right"),
        Column("未付款余额", 96, "right"),
        Column("账龄(天)", 76, "right"),
        Column("备注", 140, stretch=True),
    ]

    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._rows: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(0)

        strip = FilterStrip()
        strip.add_label("截至业务日期")
        self.lbl_day = label("", "Strong")
        strip.add(self.lbl_day)
        self.f_kw = search_input("供应商 / 入库批次 / 商品…", 180)
        self.f_kw.textChanged.connect(self.refresh)
        strip.add(self.f_kw)
        self.chk_aged = QCheckBox("只看账龄 30 天以上")
        self.chk_aged.setToolTip("账龄 = 采购入库日期到业务日期；不是合同账期，只作排付款计划的参照")
        self.chk_aged.toggled.connect(self.refresh)
        strip.add(self.chk_aged)
        strip.add(button("重置", "", self.reset))
        strip.add_stretch()
        strip.add(button("生成采购对账单", "Gold", self.on_statement,
                         tip="选一个还欠着钱的供应商，按未付款逐笔出一张采购对账单"
                             "（A4 竖版，带签章区），打印出来跟供应商核对签字"))
        strip.add(button("导出应付+未付", "", self.export_all,
                         tip="应付款（含逐笔付款）/ 未付款打成一个工作簿"))
        strip.add(button("导出未付款", "", self.export_open))
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
        self._rows = calc.ap_open_items(
            self.ctx.conn, as_of, self.f_kw.text().strip(), self.chk_aged.isChecked())
        body, colors = [], {}
        for i, r in enumerate(self._rows):
            body.append([
                str(i + 1), r.get("batch_code") or "", r.get("supplier") or "—",
                r.get("phone") or "", r.get("item") or "", money(r.get("_amount")),
                money(r.get("_paid")), money(r.get("_unpaid")),
                str(int(r.get("_age") or 0)), r.get("remark") or "",
            ])
            if r.get("_aged"):
                colors[(i, 8)] = theme.DANGER
                colors[(i, 7)] = theme.DANGER
        self.table.set_rows(
            body, self._rows, colors=colors,
            empty_text="截至这天没有未付款：要么没有挂账采购，要么都付清了")
        for i in range(len(body)):
            self.table.setRowHeight(i, 30)

        total = sum(float(r.get("_unpaid") or 0) for r in self._rows)
        aged = sum(float(r.get("_unpaid") or 0) for r in self._rows if r.get("_aged"))
        suppliers = len({calc.ap_supplier_key(r.get("supplier")) for r in self._rows})
        summary = calc.ap_summary(self.ctx.conn, "", as_of, as_of)
        prepaid = float(summary.get("prepaid") or 0)
        tail = f"未付合计 {money(total)}"
        if aged > 0.005:
            tail += f"　·　其中账龄 30 天以上 {money(aged)}"
        if prepaid > 0.005:
            tail += f"　·　预付 / 多付 {money(prepaid)}（应付款明细里未付为负数的行）"
        self.sums.set_text(
            f"共 {len(self._rows)} 笔 · {suppliers} 个供应商 · 截至 {as_of}", tail)

    # ---------------------------------------------------------- 采购对账单
    def on_statement(self) -> None:
        """生成采购对账单：选供应商 → 手填四个联系信息 → 照模板「对账单2」出 A4 纵向一页。"""
        names = sorted({str(r.get("supplier") or "").strip() for r in self._rows} - {""})
        if not names:
            self.notify("没有可对账的供应商：未付款为空，或欠款都挂在「未填供应商」名下", "warn")
            return
        fields = [
            Field("supplier", "供应商名称", "combo", True, tuple(names),
                  hint="只列截至这天还有未付款的供应商"),
            Field("as_of", "对账日期", "date", False, hint="默认业务日期"),
            Field("contact", "供应商联系人", "text", False, placeholder="供应商那边对接的人"),
            Field("phone", "供应商联系电话", "text", False, placeholder="138xxxx / 座机"),
            Field("our_contact", "我公司联系人", "text", False, placeholder="我方采购 / 财务"),
            Field("our_phone", "我公司联系电话", "text", False, placeholder="138xxxx / 座机"),
        ]
        dlg = FormDialog(
            "生成采购对账单", fields,
            {"supplier": names[0], "as_of": self.ctx.biz_date}, self,
            hint="四个联系人 / 电话都手工填，填什么打印什么；正文按这位供应商截至对账日的"
                 "未付款逐笔列示（未付 = 应付 − 已付），版式照《账表记录-羊》的「对账单2」。",
        )
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        supplier = str(v.get("supplier") or "").strip()
        day = str(v.get("as_of") or self.ctx.biz_date)
        count = sum(1 for r in self._rows
                    if str(r.get("supplier") or "").strip() == supplier)
        if not count:
            self.notify(f"「{supplier}」截至 {day} 没有未付款", "warn")
            return
        config.ensure_dirs()
        safe = re.sub(r'[\\/:*?"<>|]', "_", supplier) or "供应商"
        path = Path(config.EXPORT_DIR) / f"采购对账单-{safe}-{day}.xlsx"
        xl_export.export_ap_statement(path, self.ctx.conn, supplier,
                                      v.get("contact") or "", v.get("phone") or "", day,
                                      v.get("our_contact") or "", v.get("our_phone") or "")
        self.notify(f"已生成采购对账单：{path.name}")
        info(self, "采购对账单已生成",
             f"供应商：{supplier}　·　{count} 笔未付　·　截至 {day}\n\n{path}")

    def reset(self) -> None:
        self.f_kw.blockSignals(True)
        self.f_kw.clear()
        self.f_kw.blockSignals(False)
        self.chk_aged.blockSignals(True)
        self.chk_aged.setChecked(False)
        self.chk_aged.blockSignals(False)
        self.refresh()

    # ---------------------------------------------------------- 导出
    def export_open(self) -> None:
        if not self._rows:
            self.notify("截至业务日期没有未付款可导出", "warn")
            return
        config.ensure_dirs()
        path = Path(config.EXPORT_DIR) / f"应付款项-未付款-{self.ctx.biz_date}.xlsx"
        xl_export.export_ap_open(path, self.ctx.conn, self.ctx.biz_date)
        self.notify(f"已导出：{path.name}")
        info(self, "导出完成", f"已导出到：\n{path}")

    def export_all(self) -> None:
        config.ensure_dirs()
        d2 = self.ctx.biz_date
        d1 = month_start(d2)
        path = Path(config.EXPORT_DIR) / f"应付款项-应付与未付-{d1}_{d2}.xlsx"
        xl_export.export_payable_workbook(path, self.ctx.conn, d1, d2)
        self.notify(f"已导出：{path.name}")
        info(self, "导出完成", f"应付款（含逐笔付款）/ 未付款已导出到：\n{path}")

    def notify(self, message: str, level: str = "info") -> None:
        self.ctx.notify(message, level)


class PayablePage(PageBase):
    """应付款项（两张表）：活羊采购与付款。"""

    TITLE = "应付款项 · 活羊采购与付款"
    LEDGER = True

    def __init__(self, ctx, parent: QWidget | None = None, store_id: int = 0) -> None:
        super().__init__(ctx, parent)
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
        self.tab_inv = ApInvoiceTab(ctx)
        self.tab_open = ApOpenTab(ctx)
        self.tabs.addTab(self.tab_inv, "应付款")
        self.tabs.addTab(self.tab_open, "未付款")
        root.addWidget(self.tabs, 1)

        self.tab_inv.history_changed.connect(self.history_changed.emit)
        self.tabs.currentChanged.connect(self._on_tab_changed)

    # ---------------------------------------------------------- 刷新
    def refresh(self) -> None:
        self._sync_from_batches()
        self.tab_inv.refresh()
        self.tab_open.refresh()

    def _sync_from_batches(self) -> None:
        """进页面先把入库批次的采购提取成应付（幂等）：批次改了，应付跟着变。"""
        if self._syncing:
            return
        self._syncing = True
        try:
            created, updated, cancelled = repo.sync_ap_from_batches(self.ctx.conn)
        except Exception as exc:                    # 同步失败别把整页卡死
            self.notify(f"按入库批次提取应付时出错：{exc}", "warn")
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
                parts.append(f"撤销 {cancelled} 张（批次已删 / 金额归零）")
            self.notify("已按入库批次自动提取应付：" + "、".join(parts))

    def _on_tab_changed(self, _index: int) -> None:
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
