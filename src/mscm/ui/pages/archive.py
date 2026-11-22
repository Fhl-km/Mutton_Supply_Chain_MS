"""基础档案：商品档案 / 门店档案。

两张档案都是「少量记录 + 弹窗表单」，跟台账的行内录入不是一回事：
档案改一次用很久，弹窗里把字段一次看全更合适。
（活羊入库&结余是台账不是档案，走行内录入，见 pages/batches.py）
"""

from __future__ import annotations

from typing import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from mscm.core import repo
from mscm.core.models import PRODUCT_CATS, T_PRODUCT, T_STORE
from mscm.ui import icons
from mscm.ui.dialogs import Field, FormDialog, confirm, info
from mscm.ui.pages.base_ledger import OpsStrip
from mscm.ui.widgets import (
    Card,
    Column,
    DataTable,
    FilterStrip,
    HelpPanel,
    PageBase,
    SumBar,
    button,
    num,
    search_input,
)


class ArchivePage(PageBase):
    """档案页骨架：只读列表 + 弹窗新增 / 编辑 / 删除。"""

    TITLE = "档案"
    TABLE = ""
    FIELDS: Sequence[Field] = ()
    COLUMNS: Sequence[Column] = ()
    HELP_HTML = ""
    NEW_TITLE = "新增"
    SEARCH_TIP = "搜索…"
    NUMBERED = False                # 列表要不要最左边那一列「序号」（客户名录照模板要有）
    DIALOG_HINT: str | None = None  # 弹窗里的提示；None = 直接用 HELP_HTML 全文
    SUM_TEXT: Callable[[list[dict]], str] | None = None

    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(ctx, parent)
        self._rows: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 6, 14, 4)
        root.setSpacing(0)

        strip = FilterStrip()
        strip.add_label("筛选")
        self.f_kw = search_input(self.SEARCH_TIP, 200)
        strip.add(self.f_kw)
        self.add_filters(strip)
        strip.add_stretch()
        for w in self.tool_buttons():
            strip.add(w)
        strip.add(button("＋ 新增", "Primary", self.on_new))
        root.addWidget(strip)

        self.help = HelpPanel(self.HELP_HTML) if self.HELP_HTML else None
        if self.help is not None:
            root.addWidget(self.help)

        self.card = Card(self.TITLE, "")
        cols = list(self.COLUMNS)
        if cols and cols[-1].title == "操作":
            cols = cols[:-1]                    # 操作挪到右侧冻结列，不再占表格宽度
        self.table = DataTable(cols, row_height=32)
        self.table.doubleClicked.connect(lambda *_: self.on_edit())
        self.ops = OpsStrip(self.table, [
            {"icon": icons.edit_icon, "tip": "编辑（也可以双击这一行）",
             "run": lambda r, a: self._edit_row(r)},
            {"icon": icons.trash_icon, "tip": "删除", "run": lambda r, a: self._del_row(r)},
        ], width=56)
        table_row = QWidget()
        table_row.setStyleSheet("background:transparent;")
        table_lay = QHBoxLayout(table_row)
        table_lay.setContentsMargins(0, 0, 0, 0)
        table_lay.setSpacing(0)
        table_lay.addWidget(self.table, 1)
        table_lay.addWidget(self.ops, 0)
        self.card.add(table_row, 1)
        self.sums = SumBar(self.table)
        self.card.add(self.sums)
        root.addWidget(self.card, 1)

        self.f_kw.textChanged.connect(self.refresh)
        self.refresh()

    # ---------------------------------------------------------- 子类接口
    def fetch(self) -> list[dict]:
        raise NotImplementedError

    def row_of(self, rec: dict) -> list:
        raise NotImplementedError

    def save(self, data: dict, rid: int | None) -> dict:
        raise NotImplementedError

    def delete(self, rid: int) -> tuple[bool, str]:
        raise NotImplementedError

    def blank(self) -> dict:
        return {}

    def label_of(self, rec: dict) -> str:
        return str(rec.get("name") or rec.get("code") or "")

    def form_calc(self, rid: int | None) -> Callable[[dict], dict] | None:
        """表单里的联动（子类按需覆写）：返回 values -> 要回填的字段。"""
        return None

    def add_filters(self, strip: FilterStrip) -> None:
        """筛选条上的专用筛选项（子类按需覆写，比如客户名录按「归属」筛）。"""
        return None

    def tool_buttons(self) -> list[QWidget]:
        """筛选条右侧的专用按钮（导出等），排在「＋ 新增」左边。"""
        return []

    # ---------------------------------------------------------- 渲染
    def refresh(self) -> None:
        self._rows = self.fetch()
        body = []
        for i, rec in enumerate(self._rows, start=1):
            row = self.row_of(rec)
            body.append([str(i)] + list(row) if self.NUMBERED else row)
        self.table.set_rows(body, self._rows, empty_text="还没有档案：点右上「＋ 新增」")
        for i in range(len(body)):
            self.table.setRowHeight(i, 32)
        self.ops.set_items([{"rec": r} for r in self._rows])
        self.card.set_hint(f"共 {len(body)} 条")
        text = self.SUM_TEXT(self._rows) if self.SUM_TEXT else f"共 {len(self._rows)} 条"
        self.sums.set_text(text, "")

    # ---------------------------------------------------------- 增删改
    def on_new(self) -> None:
        hint = self.HELP_HTML if self.DIALOG_HINT is None else self.DIALOG_HINT
        dlg = FormDialog(f"{self.NEW_TITLE} · {self.TITLE}", self.FIELDS,
                         values=self.blank(), parent=self, hint=hint,
                         calc=self.form_calc(None))
        if dlg.exec() != FormDialog.Accepted:
            return
        self.save(dlg.values(), None)
        self.refresh()
        self.ctx.changed()
        self.notify(f"已新增{self.TITLE}")

    def on_edit(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self._edit_row(row)

    def _edit_row(self, row: int) -> None:
        if not (0 <= row < len(self._rows)):
            return
        rec = self._rows[row]
        dlg = FormDialog(f"编辑 · {self.TITLE}", self.FIELDS, values=dict(rec), parent=self,
                         calc=self.form_calc(int(rec.get("id") or 0)))
        if dlg.exec() != FormDialog.Accepted:
            return
        self.save(dlg.values(), int(rec.get("id") or 0))
        self.refresh()
        self.ctx.changed()
        self.notify("已保存")

    def _del_row(self, row: int) -> None:
        if not (0 <= row < len(self._rows)):
            return
        rec = self._rows[row]
        if not confirm(self, "删除确认", f"确定删除「{self.label_of(rec)}」吗？", danger=True):
            return
        ok, msg = self.delete(int(rec.get("id") or 0))
        if not ok:
            info(self, "不能删除", msg)
            return
        self.refresh()
        self.ctx.changed()
        self.notify("已删除")


# ---------------------------------------------------------------- 商品档案
class ProductPage(ArchivePage):
    TITLE = "商品档案"
    TABLE = T_PRODUCT
    NEW_TITLE = "新增商品"
    SEARCH_TIP = "名称 / 分类…"
    HELP_HTML = (
        "<b>商品档案是下拉的底</b>　屠宰产出、屠宰出库、门店入库 / 销售 / 盘点里的"
        "「商品名称」都从这儿取，避免同一样东西写成三四个名字（白条 / 白条羊 / 整羊）。<br>"
        "<b>分类</b>　白条（整只胴体）/ 分割品（羊排、羊腿、羊蝎子、羊肉卷）/ "
        "副产品（羊杂、羊头、羊蹄、羊皮、羊油）。<br>"
        "<b>已被引用的商品不能删</b>，要停用就改名加「（停用）」，或先处理掉台账里的引用。"
    )
    FIELDS = (
        Field("name", "商品名称", "text", True),
        Field("cat", "分类", "combo", True, PRODUCT_CATS),
        Field("spec", "规格", "text", False, placeholder="如 整只 / 2kg 装"),
        Field("remark", "备注", "text", False, span=True),
    )
    COLUMNS = (
        Column("商品名称", 160),
        Column("分类", 96, "center"),
        Column("规格", 160),
        Column("累计产出(kg)", 120, "right"),
        Column("累计出库(kg)", 120, "right"),
        Column("备注", 160, stretch=True),
        Column("操作", 110, "center"),
    )

    def fetch(self) -> list[dict]:
        kw = self.f_kw.text().strip()
        rows = repo.list_products(self.ctx.conn)
        if kw:
            rows = [r for r in rows if kw in f"{r.get('name')} {r.get('cat')} {r.get('spec')}"]
        return rows

    def row_of(self, rec: dict) -> list:
        name = str(rec.get("name") or "")
        produced = sum(float(x.get("weight") or 0) for x in self.ctx.conn.rows("yield_line")
                       if str(x.get("product") or "") == name)
        sold = sum(float(x.get("weight") or 0) for x in self.ctx.conn.rows("slaughter_out")
                   if str(x.get("product") or "") == name)
        return [name, rec.get("cat") or "", rec.get("spec") or "",
                num(produced, 1), num(sold, 1), rec.get("remark") or "", ""]

    def blank(self) -> dict:
        return {"cat": PRODUCT_CATS[0]}

    def save(self, data: dict, rid: int | None) -> dict:
        payload = {"name": str(data.get("name") or "").strip(),
                   "cat": data.get("cat") or "",
                   "spec": data.get("spec") or "",
                   "remark": data.get("remark") or "",
                   "is_active": True}
        return repo.save_product(self.ctx.conn, payload, rid)

    def delete(self, rid: int) -> tuple[bool, str]:
        return repo.delete_product(self.ctx.conn, rid)


# ---------------------------------------------------------------- 门店档案
class StorePage(ArchivePage):
    TITLE = "门店档案"
    TABLE = T_STORE
    NEW_TITLE = "新增门店"
    SEARCH_TIP = "门店名称 / 编号…"
    HELP_HTML = (
        "<b>门店档案决定导航</b>　这里每加一家门店，左侧「门店管理」下就多一个门店节点，"
        "节点里固定挂六项：损益报表 / 进销存台账 / 入库台账 / 销售台账 / 结存/盘点台账 / 应收款项。<br>"
        "<b>已有台账记录的门店不能删</b>，避免台账变成孤儿数据。"
    )
    FIELDS = (
        Field("code", "门店编号", "text", True, placeholder="如 01"),
        Field("name", "门店名称", "text", True, placeholder="如 关一店"),
        Field("short", "简称", "text", False),
        Field("contact", "联系人", "text", False),
        Field("phone", "联系电话", "text", False),
        Field("address", "地址", "text", False, span=True),
        Field("remark", "备注", "text", False, span=True),
    )
    COLUMNS = (
        Column("编号", 70, "center"),
        Column("门店名称", 150),
        Column("简称", 110),
        Column("联系人", 100),
        Column("联系电话", 130),
        Column("地址", 220, stretch=True),
        Column("入库", 70, "right"),
        Column("销售", 70, "right"),
        Column("盘点", 70, "right"),
        Column("操作", 110, "center"),
    )

    def fetch(self) -> list[dict]:
        kw = self.f_kw.text().strip()
        rows = repo.list_stores(self.ctx.conn, only_active=False)
        if kw:
            rows = [r for r in rows if kw in f"{r.get('code')} {r.get('name')} {r.get('short')}"]
        return rows

    def row_of(self, rec: dict) -> list:
        sid = int(rec.get("id") or 0)

        def count(table: str) -> int:
            return len([x for x in self.ctx.conn.rows(table)
                        if int(x.get("store_id") or 0) == sid])

        return [rec.get("code") or "", rec.get("name") or "", rec.get("short") or "",
                rec.get("contact") or "", rec.get("phone") or "", rec.get("address") or "",
                count("store_in"), count("store_sale"), count("store_stock"), ""]

    def blank(self) -> dict:
        return {"code": f"{len(self.ctx.conn.rows(T_STORE)) + 1:02d}", "name": ""}

    def label_of(self, rec: dict) -> str:
        return str(rec.get("name") or "")

    def save(self, data: dict, rid: int | None) -> dict:
        payload = {
            "code": str(data.get("code") or "").strip(),
            "name": str(data.get("name") or "").strip(),
            "short": str(data.get("short") or data.get("name") or "").strip(),
            "contact": data.get("contact") or "",
            "phone": data.get("phone") or "",
            "address": data.get("address") or "",
            "remark": data.get("remark") or "",
            "is_active": True,
        }
        return repo.save_store(self.ctx.conn, payload, rid)

    def delete(self, rid: int) -> tuple[bool, str]:
        return repo.delete_store(self.ctx.conn, rid)
