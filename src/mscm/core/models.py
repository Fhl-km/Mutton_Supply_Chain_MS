"""业务模型与领域常量。

口径来自《账表记录-羊.xlsx》七张台账：

    屠宰场暂养出入库台账   批次 × 日期：入库（供应商/标识/只数/kg/单价/金额）→ 出库（用途/只数/kg/金额）→ 当日结余
    养殖记录               批次 × 日期：期初存栏 − 出栏 = 期末存栏；投料（原材料/单位/数量/单价/金额）
    屠宰记录               屠宰单：领入只数 / 毛重 → 产出明细（白条、分割品、副产品）→ 出肉率
    屠宰出库明细           屠宰场销售 / 内部调拨（调拨到门店 = 门店入库的来源）
    门店入库台账           门店收货：来源 / 批次 / 商品 / 只数 / kg / 单价 / 金额
    门店销售台账           门店销售：应收 / 实收 / 收款方式 / 客户
    门店结存/盘点台账      门店实盘：批次 / 存放地点 / 库存只数 / kg / 单价 / 金额

应收款项（2026-11 新增，分「屠宰销售」「门店销售」两套，结构相同）：
    应收款                 挂账应收单：销售批次 / 客户 / 商品摘要 / 应收金额 / 结算方式 / 约定收款日
                           —— 由销售单（出库单或门店销售）里「收款方式＝挂账 / 月结」的行自动提取
    已收款                 到账登记：日期 / 客户 / 已收金额 / 抹零金额 / 收款方式 /
                           归属的应收单（invoice_id）
                           —— 不单独成表，按「一对多」挂在应收单下面逐笔列示，由出纳照银行流水填
    未收款                 不落库：应收金额 − 已收金额 − 抹零金额，现算

客户名录（2026-11 新增，版式照用户模板《客户名录.xlsx》）：
    归属 / 客户名称 / 统一信用代码或身份证号 / 联系人 / 联系电话 / 经营配送地址 /
    结算方式 / 首次供货时间 / 业务对接人 / 备注
    用途：客户底表。应收款项里填客户时，名录里的名字直接出现在下拉候选里。

应付款项 · 活羊采购与付款（2026-11 新增，版式照模板「应付款」表）：
    应付款                 序号 / 入库批次 / 供应商名称 / 联系电话 / 商品 / 应付金额 /
                           付款日期 / 已付款金额 / 未付款余额
                           —— 由「活羊入库&结余」的入栏金额（kg × 均价）自动提取，一次采购一张单
    付款                   到账（出账）登记：付款日期 / 已付款金额 / 付款方式 /
                           归属的应付单（invoice_id）
                           —— 不单独成表，按「一对多」挂在应付单下面逐笔列示
    未付款                 不落库：应付金额 − 已付款金额，现算，带账龄

关键勾稽（程序内自动算，数据校验页逐条核）：
    暂养结存只数 = Σ入库只数 − Σ出库只数（按批次累计）
    养殖期末存栏 = 期初存栏 − 出栏只数
    屠宰出肉率   = 产出合计 kg ÷ 领入毛重 kg
    门店账面库存 = Σ门店入库 kg − Σ门店销售 kg
    门店盘点差异 = 实盘 kg − 账面 kg
    未收款余额   = Σ应收款 − Σ已收款（逐笔挂到应收单上；老数据没挂单的按客户先进先出核销；
                   收超了就是负数，代表预收款）
    未付款余额   = Σ应付款 − Σ已付款（逐笔挂到应付单上；多付了就是负数，代表预付 / 多付）
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

# ---------------------------------------------------------------- 台账表名
T_BATCH = "batch"                 # 羊群批次档案
T_PRODUCT = "product"             # 商品档案（屠宰产出 / 门店商品）
T_STORE = "store"                 # 门店档案
T_FEED = "feed"                   # 屠宰场暂养出入库台账
T_BREED = "breeding"              # 养殖记录
T_SLAUGHTER = "slaughter"         # 屠宰记录（主表）
T_YIELD = "yield_line"            # 屠宰产出明细（子表）
T_SOUT = "slaughter_out"          # 屠宰出库明细
T_SIN = "store_in"                # 门店入库台账
T_SSALE = "store_sale"            # 门店销售台账
T_SSTOCK = "store_stock"          # 门店结存/盘点台账
T_AR = "ar_invoice"               # 应收款（挂账应收单）
T_ARR = "ar_receipt"              # 收款（到账登记，挂在应收单上，一张单可多笔）
T_AP = "ap_invoice"               # 应付款（采购应付单，由入库批次自动提取）
T_APP = "ap_payment"              # 付款（逐笔，挂在应付单上，一张单可多笔）
T_CUSTOMER = "customer"           # 客户名录（门头 / 单位档案）

TABLES: tuple[str, ...] = (T_BATCH, T_PRODUCT, T_STORE, T_FEED, T_BREED,
                           T_SLAUGHTER, T_YIELD, T_SOUT, T_SIN, T_SSALE, T_SSTOCK,
                           T_AR, T_ARR, T_AP, T_APP, T_CUSTOMER)

# ---------------------------------------------------------------- 品类 / 选项
SHEEP_CATEGORIES: tuple[str, ...] = ("育肥羊", "滩羊", "山羊", "绵羊", "羔羊", "母羊", "种公羊")

PRODUCT_CATS: tuple[str, ...] = ("白条", "分割品", "副产品")
DEFAULT_PRODUCTS: tuple[tuple[str, str], ...] = (
    ("白条羊", "白条"),
    ("羊排", "分割品"),
    ("羊腿", "分割品"),
    ("羊蝎子", "分割品"),
    ("羊肉卷", "分割品"),
    ("羊杂", "副产品"),
    ("羊头", "副产品"),
    ("羊蹄", "副产品"),
    ("羊皮", "副产品"),
    ("羊油", "副产品"),
)

# 暂养出库用途：去屠宰 / 转圈 / 死亡 / 退回
FEED_OUT_USES: tuple[str, ...] = ("屠宰领用", "转栏", "死亡损耗", "退回供应商")
# 养殖出栏用途
BREED_OUT_USES: tuple[str, ...] = ("屠宰出栏", "转栏", "销售活羊", "死亡损耗")

STORE_IN_SOURCES: tuple[str, ...] = ("屠宰场调拨", "外购", "退库", "其他")
OUT_TARGETS: tuple[str, ...] = ("门店调拨", "对外销售", "客户直供", "赠送")
SALE_TARGETS: tuple[str, ...] = ("零售", "批发", "配送", "赠送", "内部调拨")
PAY_METHODS: tuple[str, ...] = ("现款", "微信", "支付宝", "银行转账", "挂账", "月结")
STOCK_LOCATIONS: tuple[str, ...] = ("冷藏库", "冷冻库", "展示柜", "操作间")

# 客户名录（版式与表头照用户模板《客户名录.xlsx》）
# 归属：这个客户算在哪本账下——屠宰场直销 / 门店零售配送
CUSTOMER_ORGS: tuple[str, ...] = ("屠宰场", "门店")
# 结算方式：与模板里那一列的下拉选项完全一致，别自己加词
SETTLE_METHODS: tuple[str, ...] = ("现结", "周结", "半月结", "月结", "预付")

# 结算方式 → 账期天数：约定收款日 = 销售日期 + 账期（客户名录里怎么结算，就怎么算）
# 月结按 30 天算是一次性简化；若某客户另有约定，直接在「约定收款日」上手改，改过的不再被覆盖。
SETTLE_TERMS: dict[str, int] = {"现结": 0, "预付": 0, "周结": 7, "半月结": 15, "月结": 30}

# 销售批次 = 销售类型编码 + 销售日期 8 位，如 对外销售 T20261115 / 内部调拨 N20261115
SALE_CODE_OUT = "T"        # 对外销售（含客户直供、赠送——都是出屠宰场卖 / 送出去）
SALE_CODE_INNER = "N"      # 内部调拨（调拨到门店，不形成对外收入）

MAT_UNITS: tuple[str, ...] = ("kg", "袋", "件", "桶", "t")
# 常用养殖投入品（下拉候选，可手填）
COMMON_MATS: tuple[str, ...] = ("玉米", "豆粕", "羊草", "苜蓿草", "青贮", "预混料", "兽药", "疫苗")

DEFAULT_STORE_NAME = "关一店"

# 应收款项的两套账：屠宰场直销 / 门店销售（同一套表结构，用 biz 字段分开）
AR_BIZ_SLAUGHTER = "slaughter"
AR_BIZ_STORE = "store"
AR_BIZ_LABELS: tuple[tuple[str, str], ...] = (
    (AR_BIZ_SLAUGHTER, "屠宰销售"),
    (AR_BIZ_STORE, "门店销售"),
)
AR_BIZ_TITLE = dict(AR_BIZ_LABELS)

# 应收单来源：按销售单生成的标出来源，手工补录的记「手工登记」
AR_SOURCES: tuple[str, ...] = ("屠宰销售", "门店销售", "手工登记")
# 哪些收款方式算「挂账」——按销售单生成应收时只认这两种
CREDIT_PAY_METHODS: tuple[str, ...] = ("挂账", "月结")

# 应付款项（活羊采购与付款）：按《账表记录-羊》的「应付款」表头设表
# 应付单由「活羊入库&结余」自动提取（一次采购一张单），付款照银行流水逐笔挂在单下面
AP_SOURCES: tuple[str, ...] = ("采购入库", "手工登记")
AP_ITEM_DEFAULT = "活羊"          # 模板「商品」列写的就是活羊，可改
AP_NO_SUPPLIER = "（未填供应商）"
AP_AGING_DAYS = 30                # 未付款「账龄超 30 天」的提示线（不是合同账期，只作催付参照）


# ---------------------------------------------------------------- 日期与数值
def today() -> str:
    return date.today().isoformat()


def to_date(value: str | date | datetime | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def norm_date(value: str | date | datetime | None, fallback: str | None = None) -> str:
    d = to_date(value)
    return d.isoformat() if d else (fallback or today())


def shift(day: str, days: int) -> str:
    d = to_date(day) or date.today()
    return (d + timedelta(days=days)).isoformat()


def month_start(day: str) -> str:
    d = to_date(day) or date.today()
    return d.replace(day=1).isoformat()


def r1(v: float | None) -> float:
    return round(float(v or 0), 1)


def r2(v: float | None) -> float:
    return round(float(v or 0), 2)


def in_period(day: str, d1: str, d2: str) -> bool:
    """日期是否落在闭区间内（空起止表示不限）。"""
    if not day:
        return False
    if d1 and day < d1:
        return False
    if d2 and day > d2:
        return False
    return True


# ---------------------------------------------------------------- 销售批次 / 账期
def sale_type_code(target: str | None) -> str:
    """销售类型编码：内部调拨 N，其余（对外销售 / 客户直供 / 赠送）T。"""
    return SALE_CODE_INNER if "调拨" in str(target or "") else SALE_CODE_OUT


def sale_batch_code(day: str | date | None, target: str | None = "") -> str:
    """销售批次 = 类型编码 + 销售日期 8 位，如 T20261115。"""
    d = to_date(day)
    return sale_type_code(target) + (d.strftime("%Y%m%d") if d else "")


def sale_batch_date(code: str | None) -> str:
    """销售批次的后 8 位就是销售日期（T20261115 → 2026-11-15）；认不出就返回空。"""
    text = str(code or "").strip()
    tail = text[-8:]
    if not (len(tail) == 8 and tail.isdigit()):
        return ""
    d = to_date(tail)
    return d.isoformat() if d else ""


def norm_sale_batch(code: str | None, day: str | date | None = "",
                    target: str | None = "") -> str:
    """把手工输入规整成「编码 + 8 位日期」：只写 8 位数字就按对外销售补一个 T。"""
    text = str(code or "").strip().upper()
    if not text:
        return sale_batch_code(day, target)
    if text.isdigit() and len(text) == 8:
        return SALE_CODE_OUT + text
    if len(text) == 9 and text[0].isalpha() and text[1:].isdigit():
        return text
    return text          # 认不出的原样留着，由页面校验去提示


def settle_due_date(day: str | date | None, settle: str | None) -> str:
    """约定收款日 = 销售日期 + 账期天数；结算方式空着就算不出来。"""
    d = to_date(day)
    term = str(settle or "").strip()
    if not d or not term:
        return ""
    return (d + timedelta(days=SETTLE_TERMS.get(term, 0))).isoformat()


# ---------------------------------------------------------------- 台账行模型
@dataclass
class BatchBalance:
    """批次结存：暂养台账累计出来的该批次存栏与库存资金。"""

    batch_id: int = 0
    batch_code: str = ""
    category: str = ""
    pen: str = ""
    in_count: float = 0.0
    in_weight: float = 0.0
    in_amount: float = 0.0
    out_count: float = 0.0
    out_weight: float = 0.0
    out_amount: float = 0.0

    @property
    def count(self) -> float:
        return r1(self.in_count - self.out_count)

    @property
    def weight(self) -> float:
        return r1(self.in_weight - self.out_weight)

    @property
    def amount(self) -> float:
        return r2(self.in_amount - self.out_amount)

    @property
    def avg_price(self) -> float:
        """结存加权平均单价 = 结存金额 ÷ 结存 kg。"""
        return r2(self.amount / self.weight) if self.weight else 0.0


@dataclass
class StoreStock:
    """门店账面库存：入库 − 销售，可与实盘对比。"""

    store_id: int = 0
    store_name: str = ""
    batch_code: str = ""
    product: str = ""
    in_count: float = 0.0
    in_weight: float = 0.0
    in_amount: float = 0.0
    sale_count: float = 0.0
    sale_weight: float = 0.0
    sale_amount: float = 0.0

    @property
    def count(self) -> float:
        return r1(self.in_count - self.sale_count)

    @property
    def weight(self) -> float:
        return r1(self.in_weight - self.sale_weight)

    @property
    def amount(self) -> float:
        return r2(self.in_amount - self.sale_amount)

    @property
    def avg_price(self) -> float:
        return r2(self.amount / self.weight) if self.weight else 0.0


@dataclass
class CheckRow:
    """数据校验的一行结论。"""

    level: str = "ok"          # ok / warn / bad
    item: str = ""
    detail: str = ""
    expect: str = ""
    actual: str = ""

    @property
    def label(self) -> str:
        return {"ok": "通过", "warn": "注意", "bad": "异常"}.get(self.level, self.level)


@dataclass
class StoreFlow:
    """门店某日、某商品的一行进销存（数量按 kg）。

    口径照门店日报表的「进销存台账」：
        上日结余 = 截至前一日累计入库 − 累计销售
        当日采购 = 当日门店入库
        当日结余 = 当日盘点实盘；当天没盘点的商品退回账面
        当日出库 = 上日结余 + 当日采购 − 当日结余（倒算，含盘亏 / 盘盈）
        当日销售 = 当日销售台账
        当日损益 = 当日销售 − 当日出库
    """

    cat1: str = ""             # 一级明细：商品档案的类别（白条 / 分割品 / 副产品）
    cat2: str = ""             # 二级明细：商品名称
    open_qty: float = 0.0
    open_amt: float = 0.0
    in_qty: float = 0.0
    in_amt: float = 0.0
    out_qty: float = 0.0
    out_amt: float = 0.0
    close_qty: float = 0.0
    close_amt: float = 0.0
    sale_qty: float = 0.0
    sale_amt: float = 0.0
    counted: bool = False      # 当日结余是否取了盘点实盘

    @property
    def gain_qty(self) -> float:
        return round(self.sale_qty - self.out_qty, 2)

    @property
    def gain_amt(self) -> float:
        return round(self.sale_amt - self.out_amt, 2)


@dataclass
class StorePnl:
    """门店损益：按一级明细归集的产出 / 投入 / 损益。"""

    cat1: str = ""
    sale_qty: float = 0.0
    sale_amt: float = 0.0
    out_qty: float = 0.0
    out_amt: float = 0.0

    @property
    def gain_qty(self) -> float:
        return round(self.sale_qty - self.out_qty, 2)

    @property
    def gain_amt(self) -> float:
        return round(self.sale_amt - self.out_amt, 2)
