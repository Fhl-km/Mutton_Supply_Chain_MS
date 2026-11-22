"""客户名录：屠宰场 / 门店的客户底表。

版式与表头照用户提供的《客户名录.xlsx》：序号 / 归属 / 客户名称（店名/单位）/
统一信用代码/身份证号 / 联系人 / 联系电话 / 经营·配送地址 / 结算方式 /
首次供货时间 / 业务对接人 / 备注。

跟其它档案一样是「少量记录 + 弹窗表单」：客户资料改一次用很久，弹窗里把字段一次看全
比在窄列里逐个点更省事；导出按模板版式出，直接能交出去。

名录同时是应收款项的客户底表：这里登记过的名字，填应收 / 收款时的客户下拉里就有。
"""

from __future__ import annotations

from pathlib import Path

from mscm import config
from mscm.core import repo
from mscm.core.models import CUSTOMER_ORGS, SETTLE_METHODS, today
from mscm.core.services import export as xl_export
from mscm.ui.dialogs import Field, info
from mscm.ui.pages.archive import ArchivePage
from mscm.ui.widgets import Column, FilterStrip, button, combo

# 结算方式那一列允许「先空着，谈定再填」，所以下拉第一项是「（未填）」，落库时按空处理
SETTLE_BLANK = "（未填）"
ALL_ORGS = "全部归属"


class CustomerPage(ArchivePage):
    TITLE = "客户名录"
    TABLE = "customer"
    NEW_TITLE = "新增客户"
    NUMBERED = True
    SEARCH_TIP = "客户名称 / 联系人 / 电话 / 地址…"
    DIALOG_HINT = ("归属决定这个名字出现在哪套应收的下拉里；结算方式与模板一致（现结 / 周结 / "
                   "半月结 / 月结 / 预付），没谈定就留「（未填）」；首次供货时间可以空着。")
    HELP_HTML = (
        "<b>这本名录是干什么的</b>　客户底表：谁在供货、归哪个口子、怎么结算、谁对接。"
        "版式照《客户名录.xlsx》，导出的表可以直接给业务、对账、审计看。<br>"
        "<b>归属</b>　这本客户挂在哪块业务下——<b>屠宰场</b>（屠宰场直接对外销售 / 客户直供）、"
        "<b>门店</b>（门店零售、批发、配送）。归属只影响列表分组与应收下拉，不影响台账金额。<br>"
        "<b>统一信用代码 / 身份证号</b>　单位填 18 位统一社会信用代码，个人客户填身份证号；"
        "开票、签合同、追款都靠它，能填就填。<br>"
        "<b>结算方式</b>　现结 / 周结 / 半月结 / 月结 / 预付，与模板下拉一致；"
        "没谈定的先空着（下拉里是「（未填）」），别随手挑一个。<br>"
        "<b>首次供货时间</b>　第一次给这个客户送货的日期，可以空着；"
        "填了以后翻名录就能看出哪些是长期客户、哪些是新开的。<br>"
        "<b>业务对接人</b>　我方跟这个客户对口的人（业务员 / 店长），不是客户那边的联系人。<br>"
        "<b>和应收款项的关系</b>　这里登记过的名字，在「应收款」里直接出现在下拉里，而且<b>结算方式</b>会跟着带进应收单、据此算约定收款日；"
        "不用重复输入，也就不会出现「马老三 / 昭通马老三」两个客户。<br>"
        "<b>已被挂账的客户删不掉</b>　只要销售单或应收款上用过这个名字，就不给删，"
        "免得台账里剩一个查不到出处的客户。"
    )
    FIELDS = (
        Field("org", "归属", "combo", True, CUSTOMER_ORGS,
              hint="屠宰场 = 屠宰场直接对外销售；门店 = 门店零售 / 批发 / 配送"),
        Field("name", "客户名称", "text", True,
              placeholder="店名 / 单位全称，如 昭通小串烧烤"),
        Field("credit_code", "统一信用代码/身份证号", "text", False,
              placeholder="单位 91xxxx… / 个人身份证号", width=240),
        Field("contact", "联系人", "text", False),
        Field("phone", "联系电话", "text", False, placeholder="138xxxx / 座机"),
        # 表单两列排：对接人排在电话右边，正好补齐一行（表格里的列序仍照模板）
        Field("owner", "业务对接人", "text", False, placeholder="我方业务员 / 店长"),
        Field("address", "经营/配送地址", "text", False, span=True,
              placeholder="送货地址，写到门牌号，配送时直接照这个走"),
        Field("settle", "结算方式", "combo", False, (SETTLE_BLANK,) + SETTLE_METHODS),
        Field("first_date", "首次供货时间", "date_opt", False,
              hint="第一次供货的日期，可以空着"),
        Field("remark", "备注", "text", False, span=True),
    )
    COLUMNS = (
        Column("序号", 52, "center"),
        Column("归属", 74, "center"),
        Column("客户名称（店名/单位）", 186),
        Column("统一信用代码/身份证号", 176),
        Column("联系人", 84),
        Column("联系电话", 118),
        Column("经营/配送地址", 210, stretch=True),
        Column("结算方式", 82, "center"),
        Column("首次供货时间", 104, "center"),
        Column("业务对接人", 96, "center"),
        Column("备注", 132),
        Column("操作", 110, "center"),
    )

    # ---------------------------------------------------------- 筛选 / 按钮
    def add_filters(self, strip: FilterStrip) -> None:
        self.f_org = combo([ALL_ORGS] + list(CUSTOMER_ORGS), width=118)
        self.f_org.currentIndexChanged.connect(self.refresh)
        strip.add(self.f_org)

    def tool_buttons(self) -> list:
        return [button("导出名录", "Gold", self.on_export,
                       tip="按当前筛选导出 Excel，版式与《客户名录.xlsx》一致")]

    # ---------------------------------------------------------- 取数
    def fetch(self) -> list[dict]:
        org = self.f_org.currentText() if hasattr(self, "f_org") else ALL_ORGS
        rows = repo.list_customers(self.ctx.conn, "" if org == ALL_ORGS else org)
        kw = self.f_kw.text().strip()
        if kw:
            rows = [r for r in rows
                    if kw in " ".join(str(r.get(k) or "") for k in
                                      ("org", "name", "credit_code", "contact", "phone",
                                       "address", "settle", "owner", "remark"))]
        return rows

    def row_of(self, rec: dict) -> list:
        return [rec.get("org") or "", rec.get("name") or "", rec.get("credit_code") or "",
                rec.get("contact") or "", rec.get("phone") or "", rec.get("address") or "",
                rec.get("settle") or "", rec.get("first_date") or "",
                rec.get("owner") or "", rec.get("remark") or "", ""]

    def blank(self) -> dict:
        return {"org": CUSTOMER_ORGS[0], "settle": SETTLE_BLANK, "first_date": ""}

    def label_of(self, rec: dict) -> str:
        return str(rec.get("name") or "")

    # ---------------------------------------------------------- 落库
    def save(self, data: dict, rid: int | None) -> dict:
        settle = str(data.get("settle") or "").strip()
        payload = {
            "org": str(data.get("org") or CUSTOMER_ORGS[0]).strip(),
            "name": str(data.get("name") or "").strip(),
            "credit_code": str(data.get("credit_code") or "").strip(),
            "contact": str(data.get("contact") or "").strip(),
            "phone": str(data.get("phone") or "").strip(),
            "address": str(data.get("address") or "").strip(),
            "settle": "" if settle == SETTLE_BLANK else settle,
            "first_date": str(data.get("first_date") or "").strip(),
            "owner": str(data.get("owner") or "").strip(),
            "remark": str(data.get("remark") or "").strip(),
            "is_active": True,
        }
        return repo.save_customer(self.ctx.conn, payload, rid)

    def delete(self, rid: int) -> tuple[bool, str]:
        return repo.delete_customer(self.ctx.conn, rid)

    # ---------------------------------------------------------- 导出
    def on_export(self) -> None:
        if not self._rows:
            self.notify("当前筛选没有可导出的客户", "warn")
            return
        config.ensure_dirs()
        org = self.f_org.currentText()
        tag = "" if org == ALL_ORGS else f"-{org}"
        path = Path(config.EXPORT_DIR) / f"客户名录{tag}-{today()}.xlsx"
        xl_export.export_customers(path, self._rows)
        self.notify(f"已导出：{path.name}")
        info(self, "导出完成", f"已导出 {len(self._rows)} 户到：\n{path}")

    # ---------------------------------------------------------- 页脚
    @staticmethod
    def SUM_TEXT(rows: list[dict]) -> str:            # noqa: N802 - 基类按类属性调用
        if not rows:
            return "还没有客户：点右上「＋ 新增」"
        slaughter = len([r for r in rows if str(r.get("org")) == "屠宰场"])
        store = len([r for r in rows if str(r.get("org")) == "门店"])
        parts = [f"共 {len(rows)} 户"]
        if slaughter:
            parts.append(f"屠宰场 {slaughter}")
        if store:
            parts.append(f"门店 {store}")
        if len(rows) - slaughter - store:
            parts.append(f"未归类 {len(rows) - slaughter - store}")
        return "　·　".join(parts)
