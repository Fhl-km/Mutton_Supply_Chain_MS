"""口径计算：暂养结存、养殖存栏、屠宰出品、门店库存、应收款项与数据校验。

设计原则：**派生数字一律现算，不落库**。
台账里只存「原始事实」（日期、批次、只数、kg、单价），金额 / 结存 / 出肉率 /
账面库存 / 差异 / 应收未收余额全部在这里按口径算出来。这样改一行原始数据，所有汇总自动跟着变，
不会出现「库里存了一份、界面又算了一份」两套数打架。
"""

from __future__ import annotations

from mscm.core.models import (
    AP_AGING_DAYS, AP_NO_SUPPLIER, AR_BIZ_SLAUGHTER, AR_BIZ_STORE, CREDIT_PAY_METHODS,
    T_AP, T_APP, T_AR, T_ARR, T_BATCH, T_BREED, T_CUSTOMER, T_FEED, T_PRODUCT, T_SLAUGHTER,
    T_SOUT, T_SIN, T_SSALE, T_SSTOCK, T_STORE, T_YIELD,
    PRODUCT_CATS, BatchBalance, CheckRow, StoreFlow, StorePnl, StoreStock,
    in_period, r1, r2, sale_batch_code, sale_batch_date, settle_due_date, to_date, today,
)


# ---------------------------------------------------------------- 小工具
def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _i(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def batch_map(store) -> dict[int, dict]:
    return {_i(b.get("id")): b for b in store.rows(T_BATCH)}


def batch_code(store, batch_id: int) -> str:
    b = batch_map(store).get(_i(batch_id)) or {}
    return str(b.get("code") or "")


def store_map(store) -> dict[int, dict]:
    return {_i(s.get("id")): s for s in store.rows(T_STORE)}


def batch_category(store, batch_id: int) -> str:
    return str((batch_map(store).get(_i(batch_id)) or {}).get("category") or "")


def store_name(store, store_id: int) -> str:
    s = store_map(store).get(_i(store_id)) or {}
    return str(s.get("name") or "")


def product_cat(store, name: str) -> str:
    for p in store.rows(T_PRODUCT):
        if str(p.get("name") or "") == str(name or ""):
            return str(p.get("cat") or "")
    return ""


# ---------------------------------------------------------------- 暂养台账
def feed_ledger(store, d1: str = "", d2: str = "", batch_id: int = 0,
                keyword: str = "") -> list[dict]:
    """屠宰场暂养出入库台账：逐行算入库金额、出库金额（加权平均）与当日结存。

    出库金额按**该批次累计入库加权平均单价**计价（金额 ÷ kg），不用固定价：
    批次进价变了，结存金额与出库成本跟着变，结存表才对得上。
    """
    rows = sorted(store.rows(T_FEED),
                  key=lambda r: (_i(r.get("batch_id")), str(r.get("date") or ""), _i(r.get("id"))))
    bmap = batch_map(store)
    acc: dict[int, list[float]] = {}
    out: list[dict] = []
    for r in rows:
        b = _i(r.get("batch_id"))
        in_c, in_w, in_p = _f(r.get("in_count")), _f(r.get("in_weight")), _f(r.get("in_price"))
        in_amt = r2(in_w * in_p)
        out_c, out_w = _f(r.get("out_count")), _f(r.get("out_weight"))

        st = acc.setdefault(b, [0.0, 0.0, 0.0])       # 只数 / kg / 金额
        st[0] += in_c
        st[1] += in_w
        st[2] += in_amt
        avg = (st[2] / st[1]) if st[1] else in_p
        out_amt = r2(out_w * avg) if out_w else 0.0
        st[0] -= out_c
        st[1] -= out_w
        st[2] -= out_amt

        rec = dict(r)
        rec["_batch_code"] = str((bmap.get(b) or {}).get("code") or "")
        rec["_pen"] = str((bmap.get(b) or {}).get("pen") or "")
        rec["_in_amount"] = in_amt
        rec["_out_amount"] = out_amt
        rec["_avg_price"] = r2(avg)
        rec["_bal_count"] = r1(st[0])
        rec["_bal_weight"] = r1(st[1])
        rec["_bal_amount"] = r2(st[2])
        out.append(rec)

    kw = str(keyword or "").strip()
    result = []
    for rec in out:
        if not in_period(str(rec.get("date") or ""), d1, d2):
            continue
        if batch_id and _i(rec.get("batch_id")) != int(batch_id):
            continue
        if kw:
            hay = " ".join(str(rec.get(k) or "") for k in
                           ("in_supplier", "in_tag", "out_use", "remark", "category"))
            hay += " " + str((bmap.get(_i(rec.get("batch_id"))) or {}).get("code") or "")
            if kw not in hay:
                continue
        result.append(rec)
    return result


def batch_balances(store, d2: str = "") -> list[BatchBalance]:
    """各批次结存（截至 d2）：入 − 出。"""
    rows = feed_ledger(store, "", d2)
    bmap = batch_map(store)
    acc: dict[int, BatchBalance] = {}
    for r in rows:
        b = _i(r.get("batch_id"))
        bal = acc.get(b)
        if bal is None:
            info = bmap.get(b) or {}
            bal = BatchBalance(batch_id=b, batch_code=str(info.get("code") or ""),
                               category=str(info.get("category") or r.get("category") or ""),
                               pen=str(info.get("pen") or ""))
            acc[b] = bal
        bal.in_count += _f(r.get("in_count"))
        bal.in_weight += _f(r.get("in_weight"))
        bal.in_amount += _f(r.get("_in_amount"))
        bal.out_count += _f(r.get("out_count"))
        bal.out_weight += _f(r.get("out_weight"))
        bal.out_amount += _f(r.get("_out_amount"))
    return sorted(acc.values(), key=lambda x: x.batch_code)


def batch_avg_price(store, batch_id: int) -> float:
    """批次入库加权平均单价（元/kg），用于屠宰领用成本与门店调拨计价。"""
    total_w = total_a = 0.0
    for r in store.rows(T_FEED):
        if _i(r.get("batch_id")) != _i(batch_id):
            continue
        w, p = _f(r.get("in_weight")), _f(r.get("in_price"))
        total_w += w
        total_a += w * p
    return r2(total_a / total_w) if total_w else 0.0


# ---------------------------------------------------------------- 养殖记录
def breeding_ledger(store, d1: str = "", d2: str = "", batch_id: int = 0,
                    keyword: str = "") -> list[dict]:
    """养殖记录：期初存栏接着上一行的期末，期末 = 期初 − 出栏。

    期初不让人手填，避免「上一行期末 120、这一行期初 125」这种对不上的账。
    批次第一次出现时，期初取批次档案的入栏只数。
    """
    bmap = batch_map(store)
    rows = sorted(store.rows(T_BREED),
                  key=lambda r: (_i(r.get("batch_id")), str(r.get("date") or ""), _i(r.get("id"))))
    stock: dict[int, float] = {}
    computed: list[dict] = []
    for r in rows:
        b = _i(r.get("batch_id"))
        if b not in stock:
            stock[b] = _f((bmap.get(b) or {}).get("count"))
        open_c = stock[b]
        out_c = _f(r.get("out_count"))
        close_c = r1(max(open_c - out_c, 0.0))
        stock[b] = close_c
        rec = dict(r)
        rec["_open_count"] = r1(open_c)
        rec["_close_count"] = close_c
        rec["_mat_amount"] = r2(_f(r.get("mat_qty")) * _f(r.get("mat_price")))
        computed.append(rec)

    kw = str(keyword or "").strip()
    result = []
    for rec in computed:
        if not in_period(str(rec.get("date") or ""), d1, d2):
            continue
        if batch_id and _i(rec.get("batch_id")) != int(batch_id):
            continue
        if kw:
            hay = " ".join(str(rec.get(k) or "") for k in
                           ("mat_name", "out_use", "tag", "recorder", "remark"))
            if kw not in hay:
                continue
        result.append(rec)
    return result


def current_stock(store, batch_id: int) -> float:
    """批次当前存栏（按养殖记录最后一行期末）。"""
    rows = breeding_ledger(store, "", "", batch_id)
    return rows[-1]["_close_count"] if rows else _f(
        (batch_map(store).get(_i(batch_id)) or {}).get("count"))


# ---------------------------------------------------------------- 屠宰
def slaughter_docs(store, d1: str = "", d2: str = "", batch_id: int = 0,
                   keyword: str = "") -> list[dict]:
    """屠宰记录主表：每张屠宰单一行，带产出合计、出肉率与领用成本。"""
    bmap = batch_map(store)
    lines: dict[int, list[dict]] = {}
    for ln in store.rows(T_YIELD):
        lines.setdefault(_i(ln.get("slaughter_id")), []).append(ln)

    docs: list[dict] = []
    for doc in sorted(store.rows(T_SLAUGHTER),
                      key=lambda r: (str(r.get("date") or ""), _i(r.get("id")))):
        did = _i(doc.get("id"))
        rows = lines.get(did, [])
        rec = dict(doc)
        rec["_line_count"] = len(rows)
        rec["_out_count"] = r1(sum(_f(x.get("count")) for x in rows))
        rec["_out_weight"] = r1(sum(_f(x.get("weight")) for x in rows))
        rec["_out_amount"] = r2(sum(
            _f(x.get("weight")) * _f(x.get("price")) if not _f(x.get("amount")) else _f(x.get("amount"))
            for x in rows))
        in_w = _f(doc.get("in_weight"))
        price = batch_avg_price(store, _i(doc.get("batch_id")))
        rec["_in_cost"] = r2(in_w * price)
        rec["_avg_price"] = price
        rec["_yield_rate"] = (rec["_out_weight"] / in_w) if in_w else 0.0
        rec["_unit_cost"] = r2(rec["_in_cost"] / rec["_out_weight"]) if rec["_out_weight"] else 0.0
        rec["_batch_code"] = str((bmap.get(_i(doc.get("batch_id"))) or {}).get("code") or "")
        docs.append(rec)

    kw = str(keyword or "").strip()
    result = []
    for rec in docs:
        if not in_period(str(rec.get("date") or ""), d1, d2):
            continue
        if batch_id and _i(rec.get("batch_id")) != int(batch_id):
            continue
        if kw:
            hay = f"{rec.get('doc_no') or ''} {rec.get('tag') or ''} {rec.get('operator') or ''} " \
                  f"{rec.get('category') or ''} {rec.get('_batch_code')} {rec.get('remark') or ''}"
            if kw not in hay:
                continue
        result.append(rec)
    return result


def yield_lines(store, slaughter_id: int) -> list[dict]:
    rows = [dict(x) for x in store.rows(T_YIELD) if _i(x.get("slaughter_id")) == _i(slaughter_id)]
    for r in rows:
        r["_amount"] = r2(_f(r.get("weight")) * _f(r.get("price")))
    return sorted(rows, key=lambda r: _i(r.get("id")))


def slaughter_out_rows(store, d1: str = "", d2: str = "", keyword: str = "",
                       target: str = "") -> list[dict]:
    bmap, smap = batch_map(store), store_map(store)
    kw = str(keyword or "").strip()
    out = []
    for r in sorted(store.rows(T_SOUT),
                    key=lambda x: (str(x.get("date") or ""), _i(x.get("id")))):
        if not in_period(str(r.get("date") or ""), d1, d2):
            continue
        if target and str(r.get("target") or "") != target:
            continue
        rec = dict(r)
        rec["_amount"] = r2(_f(r.get("weight")) * _f(r.get("price")))
        rec["_batch_code"] = str((bmap.get(_i(r.get("batch_id"))) or {}).get("code") or "")
        rec["_store_name"] = str((smap.get(_i(r.get("store_id"))) or {}).get("name") or "")
        rec["_sale_batch"] = sale_batch_code(r.get("date"), r.get("target"))
        if kw:
            hay = " ".join(str(rec.get(k) or "") for k in
                           ("product", "target", "customer", "phone", "salesman", "remark"))
            hay += " " + rec["_batch_code"] + " " + rec["_store_name"] + " " + rec["_sale_batch"]
            if kw not in hay:
                continue
        out.append(rec)
    return out


# ---------------------------------------------------------------- 门店
def store_in_rows(store, store_id: int = 0, d1: str = "", d2: str = "",
                  keyword: str = "") -> list[dict]:
    bmap, smap = batch_map(store), store_map(store)
    kw = str(keyword or "").strip()
    out = []
    for r in sorted(store.rows(T_SIN), key=lambda x: (str(x.get("date") or ""), _i(x.get("id")))):
        if not in_period(str(r.get("date") or ""), d1, d2):
            continue
        if store_id and _i(r.get("store_id")) != int(store_id):
            continue
        rec = dict(r)
        rec["_amount"] = r2(_f(r.get("weight")) * _f(r.get("price")))
        rec["_batch_code"] = str((bmap.get(_i(r.get("batch_id"))) or {}).get("code") or "")
        rec["_store_name"] = str((smap.get(_i(r.get("store_id"))) or {}).get("name") or "")
        if kw:
            hay = " ".join(str(rec.get(k) or "") for k in ("product", "source", "remark"))
            hay += " " + rec["_batch_code"]
            if kw not in hay:
                continue
        out.append(rec)
    return out


def store_sale_rows(store, store_id: int = 0, d1: str = "", d2: str = "",
                    keyword: str = "") -> list[dict]:
    bmap, smap = batch_map(store), store_map(store)
    kw = str(keyword or "").strip()
    out = []
    for r in sorted(store.rows(T_SSALE), key=lambda x: (str(x.get("date") or ""), _i(x.get("id")))):
        if not in_period(str(r.get("date") or ""), d1, d2):
            continue
        if store_id and _i(r.get("store_id")) != int(store_id):
            continue
        rec = dict(r)
        due = _f(r.get("due"))
        if not due:
            due = r2(_f(r.get("weight")) * _f(r.get("price")))
        rec["_due"] = r2(due)
        rec["_paid"] = r2(_f(r.get("paid")))
        rec["_unpaid"] = r2(rec["_due"] - rec["_paid"])
        rec["_batch_code"] = str((bmap.get(_i(r.get("batch_id"))) or {}).get("code") or "")
        rec["_store_name"] = str((smap.get(_i(r.get("store_id"))) or {}).get("name") or "")
        if kw:
            hay = " ".join(str(rec.get(k) or "") for k in
                           ("product", "target", "customer", "phone", "salesman", "remark"))
            hay += " " + rec["_batch_code"]
            if kw not in hay:
                continue
        out.append(rec)
    return out


def store_stock_rows(store, store_id: int = 0, d1: str = "", d2: str = "",
                     keyword: str = "") -> list[dict]:
    bmap, smap = batch_map(store), store_map(store)
    kw = str(keyword or "").strip()
    out = []
    for r in sorted(store.rows(T_SSTOCK), key=lambda x: (str(x.get("date") or ""), _i(x.get("id")))):
        if not in_period(str(r.get("date") or ""), d1, d2):
            continue
        if store_id and _i(r.get("store_id")) != int(store_id):
            continue
        rec = dict(r)
        rec["_amount"] = r2(_f(r.get("weight")) * _f(r.get("price")))
        rec["_batch_code"] = str((bmap.get(_i(r.get("batch_id"))) or {}).get("code") or "")
        rec["_store_name"] = str((smap.get(_i(r.get("store_id"))) or {}).get("name") or "")
        if kw:
            hay = " ".join(str(rec.get(k) or "") for k in ("product", "location", "remark"))
            hay += " " + rec["_batch_code"]
            if kw not in hay:
                continue
        out.append(rec)
    return out


def store_book_stock(store, store_id: int = 0, d2: str = "") -> list[StoreStock]:
    """门店账面库存 = Σ入库 − Σ销售（按 门店 × 批次 × 商品）。

    账面只是「应该有多少」，实盘以《结存/盘点台账》为准，差异在校验页列示。
    """
    acc: dict[tuple[int, str, str], StoreStock] = {}
    smap = store_map(store)
    for r in store_in_rows(store, store_id, "", d2):
        key = (_i(r.get("store_id")), str(r.get("_batch_code") or ""), str(r.get("product") or ""))
        row = acc.setdefault(key, StoreStock(store_id=key[0],
                                             store_name=str((smap.get(key[0]) or {}).get("name") or ""),
                                             batch_code=key[1], product=key[2]))
        row.in_count += _f(r.get("count"))
        row.in_weight += _f(r.get("weight"))
        row.in_amount += _f(r.get("_amount"))
    for r in store_sale_rows(store, store_id, "", d2):
        key = (_i(r.get("store_id")), str(r.get("_batch_code") or ""), str(r.get("product") or ""))
        row = acc.setdefault(key, StoreStock(store_id=key[0],
                                             store_name=str((smap.get(key[0]) or {}).get("name") or ""),
                                             batch_code=key[1], product=key[2]))
        row.sale_count += _f(r.get("count"))
        row.sale_weight += _f(r.get("weight"))
        row.sale_amount += _f(r.get("_due"))
    return sorted([r for r in acc.values() if r.weight or r.count or r.amount],
                  key=lambda x: (x.store_name, x.batch_code, x.product))


def store_totals(store, store_id: int = 0, d1: str = "", d2: str = "") -> dict:
    ins = store_in_rows(store, store_id, d1, d2)
    sales = store_sale_rows(store, store_id, d1, d2)
    return {
        "in_count": r1(sum(_f(r.get("count")) for r in ins)),
        "in_weight": r1(sum(_f(r.get("weight")) for r in ins)),
        "in_amount": r2(sum(_f(r.get("_amount")) for r in ins)),
        "sale_count": r1(sum(_f(r.get("count")) for r in sales)),
        "sale_weight": r1(sum(_f(r.get("weight")) for r in sales)),
        "sale_due": r2(sum(_f(r.get("_due")) for r in sales)),
        "sale_paid": r2(sum(_f(r.get("_paid")) for r in sales)),
        "unpaid": r2(sum(_f(r.get("_unpaid")) for r in sales)),
    }


# ---------------------------------------------------------------- 门店经营报表
STORE_NO_CAT = "未分类"


def store_product_cat_map(store) -> dict[str, str]:
    """商品名 → 商品档案里的类别；档案里查不到的归「未分类」。"""
    out: dict[str, str] = {}
    for p in store.rows(T_PRODUCT):
        name = str(p.get("name") or "").strip()
        if name:
            out[name] = str(p.get("cat") or "").strip() or STORE_NO_CAT
    return out


def store_flow_rows(store, store_id: int = 0, day: str = "") -> list[StoreFlow]:
    """单店某日的进销存（按 商品 归并，一级明细取商品档案的类别）。

    出库不单独录，由「上日结余 + 当日采购 − 当日结余」倒算；当天记了盘点的商品，
    结余取实盘数（盘亏 / 盘盈就落在出库里），没记盘点的退回账面
    （= 上日结余 + 当日入库 − 当日销售），不会因为漏盘就把出库算大。

    金额一律按「累计入库加权平均单价」计价：上日结余金额 = 上日结余 kg × 均价，
    当日结余金额 = 当日结余 kg × 当日加权均价，出库金额 = 期初金额 + 入库金额 − 结余金额。
    """
    day = str(day or "")
    if not day:
        return []
    cat_of = store_product_cat_map(store)
    acc: dict[str, dict] = {}

    def slot(product: str) -> dict:
        rec = acc.get(product)
        if rec is None:
            rec = acc[product] = {
                "cum_qty": 0.0, "cum_amt": 0.0, "cum_sale": 0.0,
                "in_qty": 0.0, "in_amt": 0.0, "sale_qty": 0.0, "sale_amt": 0.0,
                "stock_qty": 0.0, "counted": False,
            }
        return rec

    def mine(row: dict) -> bool:
        return not store_id or _i(row.get("store_id")) == int(store_id)

    for r in store.rows(T_SIN):
        if not mine(r):
            continue
        product = str(r.get("product") or "").strip()
        if not product:
            continue
        d = str(r.get("date") or "")
        rec = slot(product)
        w = _f(r.get("weight"))
        a = r2(w * _f(r.get("price")))
        if d < day:
            rec["cum_qty"] += w
            rec["cum_amt"] += a
        elif d == day:
            rec["in_qty"] += w
            rec["in_amt"] += a

    for r in store.rows(T_SSALE):
        if not mine(r):
            continue
        product = str(r.get("product") or "").strip()
        if not product:
            continue
        d = str(r.get("date") or "")
        rec = slot(product)
        w = _f(r.get("weight"))
        due = _f(r.get("due")) or r2(w * _f(r.get("price")))
        if d < day:
            rec["cum_sale"] += w
        elif d == day:
            rec["sale_qty"] += w
            rec["sale_amt"] += due

    for r in store.rows(T_SSTOCK):
        if not mine(r):
            continue
        product = str(r.get("product") or "").strip()
        if not product or str(r.get("date") or "") != day:
            continue
        rec = slot(product)
        rec["stock_qty"] += _f(r.get("weight"))
        rec["counted"] = True

    rows: list[StoreFlow] = []
    for product, rec in acc.items():
        open_qty = round(rec["cum_qty"] - rec["cum_sale"], 2)
        avg_open = (rec["cum_amt"] / rec["cum_qty"]) if rec["cum_qty"] else 0.0
        open_amt = round(open_qty * avg_open, 2)
        in_qty, in_amt = round(rec["in_qty"], 2), round(rec["in_amt"], 2)
        sale_qty, sale_amt = round(rec["sale_qty"], 2), round(rec["sale_amt"], 2)
        if rec["counted"]:
            close_qty = round(rec["stock_qty"], 2)
        else:
            close_qty = round(open_qty + in_qty - sale_qty, 2)
        base_qty = open_qty + in_qty
        avg_cost = ((open_amt + in_amt) / base_qty) if base_qty else 0.0
        close_amt = round(close_qty * avg_cost, 2)
        out_qty = round(base_qty - close_qty, 2)
        out_amt = round(open_amt + in_amt - close_amt, 2)
        row = StoreFlow(
            cat1=cat_of.get(product, STORE_NO_CAT), cat2=product,
            open_qty=open_qty, open_amt=open_amt,
            in_qty=in_qty, in_amt=in_amt,
            out_qty=out_qty, out_amt=out_amt,
            close_qty=close_qty, close_amt=close_amt,
            sale_qty=sale_qty, sale_amt=sale_amt, counted=bool(rec["counted"]),
        )
        if any((row.open_qty, row.in_qty, row.out_qty, row.close_qty,
                row.sale_qty, row.sale_amt, row.open_amt, row.in_amt)):
            rows.append(row)
    order = {name: i for i, name in enumerate(PRODUCT_CATS)}
    return sorted(rows, key=lambda r: (order.get(r.cat1, 90), r.cat1, r.cat2))


def store_flow_total(rows: list[StoreFlow]) -> StoreFlow:
    total = StoreFlow(cat1="小计", cat2="")
    for r in rows:
        for key in ("open_qty", "open_amt", "in_qty", "in_amt", "out_qty", "out_amt",
                    "close_qty", "close_amt", "sale_qty", "sale_amt"):
            setattr(total, key, round(getattr(total, key) + getattr(r, key), 2))
    return total


def store_pnl_rows(store, store_id: int = 0, day: str = "") -> tuple[list[StorePnl], StorePnl]:
    """门店损益：按一级明细（商品类别）归集销售与出库成本。

    一级明细的行序固定按商品档案的三个类别（白条 / 分割品 / 副产品）排，
    当天没有发生额的类别也留一行 0，报表行结构不随数据跳动。
    """
    flows = store_flow_rows(store, store_id, day)
    cats = list(PRODUCT_CATS)
    for f in flows:
        if f.cat1 not in cats:
            cats.append(f.cat1)
    acc = {c: StorePnl(cat1=c) for c in cats}
    for f in flows:
        p = acc[f.cat1]
        p.sale_qty = round(p.sale_qty + f.sale_qty, 2)
        p.sale_amt = round(p.sale_amt + f.sale_amt, 2)
        p.out_qty = round(p.out_qty + f.out_qty, 2)
        p.out_amt = round(p.out_amt + f.out_amt, 2)
    rows = [acc[c] for c in cats]
    total = StorePnl(cat1="合计")
    for p in rows:
        total.sale_qty = round(total.sale_qty + p.sale_qty, 2)
        total.sale_amt = round(total.sale_amt + p.sale_amt, 2)
        total.out_qty = round(total.out_qty + p.out_qty, 2)
        total.out_amt = round(total.out_amt + p.out_amt, 2)
    return rows, total


def store_day_sale_amount(store, store_id: int = 0, day: str = "") -> float:
    """当日销售台账的原始应收合计（损益报表勾稽用）。"""
    return r2(sum(_f(r.get("_due")) for r in store_sale_rows(store, store_id, day, day)))


# ---------------------------------------------------------------- 应收款项
AR_NO_CUSTOMER = "（未填客户）"


def ar_customer_key(name) -> str:
    """核销按客户名归口：空客户统一落到「未填客户」，免得各算各的。"""
    return str(name or "").strip() or AR_NO_CUSTOMER


def _ar_scope(store, biz: str, store_id: int = 0, table: str = T_AR) -> list[dict]:
    """取出某一套账（屠宰销售 / 某家门店）的应收单或收款单。"""
    out: list[dict] = []
    for r in store.rows(table):
        if str(r.get("biz") or "") != str(biz or ""):
            continue
        if store_id and _i(r.get("store_id")) != int(store_id):
            continue
        out.append(dict(r))
    return out


def customer_info(store, name) -> dict:
    """客户名录里的那条记录（联系人 / 电话 / 结算方式都在这儿）。"""
    key = str(name or "").strip()
    if not key:
        return {}
    for c in store.rows(T_CUSTOMER):
        if str(c.get("name") or "").strip() == key:
            return dict(c)
    return {}


def customer_settle(store, name) -> str:
    """结算方式取客户名录：名录里怎么结算，应收的账期就怎么算。"""
    return str(customer_info(store, name).get("settle") or "").strip()


def ar_sale_batch(inv: dict) -> str:
    """应收单的销售批次：存了就用存的，没存按销售日期补一个对外销售的 T。"""
    code = str(inv.get("sale_batch") or "").strip()
    return code or sale_batch_code(inv.get("date"), inv.get("target") or "")


def ar_settle(store, inv: dict) -> str:
    """结算方式：应收单上填了就用填的，没填去客户名录里取。"""
    return str(inv.get("settle") or "").strip() or customer_settle(store, inv.get("customer"))


def ar_due_date(store, inv: dict) -> str:
    """约定收款日：存了就用存的；没存按「销售日期（销售批次后 8 位）+ 账期」算。"""
    due = str(inv.get("due_date") or "").strip()
    if due:
        return due
    day = sale_batch_date(inv.get("sale_batch")) or str(inv.get("date") or "")
    return settle_due_date(day, ar_settle(store, inv))


def _ar_receipt_groups(store, biz: str, store_id: int = 0, as_of: str = "") -> tuple[
        dict[int, list[dict]], dict[str, float], dict[int, float], dict[int, float]]:
    """把收款逐笔挂到应收单上，同时算出每张单已收多少。

    归属规则：
        1. 收款上写了 ``invoice_id`` 的，**整笔**冲那张单——收多了就让它冲成负数，
           未收金额列示为负、代表预收（客户先给钱后拿货）；
        2. 没写归属的（老账套 / 手工补录），按**客户先进先出**冲到最早的应收单上，
           一张单最多冲到零，余下的钱挂在客户名下当预收。

    返回（{应收单 id: [收款行…]}, {客户: 预收}, {应收单 id: 已收}, {应收单 id: 抹零}）。
    收款行上的 ``_applied`` 是这笔钱实际冲掉这张单多少（一笔钱横跨两张单时小于收款金额）；
    ``waiver`` 是这笔到账时抹掉的零头（银行流水取整，如应收 6,232、实到 6,200，抹零 32），
    也按单归集——未收 = 应收 − 已收 − 抹零。
    核销池只算**截至 as_of 的收款**：期末之后才到的钱不能提前冲当期应收。
    """
    invoices = sorted(_ar_scope(store, biz, store_id),
                      key=lambda r: (str(r.get("date") or ""), _i(r.get("id"))))
    amount_of = {_i(r.get("id")): r2(_f(r.get("amount"))) for r in invoices}
    used: dict[int, float] = {iid: 0.0 for iid in amount_of}
    waived: dict[int, float] = {iid: 0.0 for iid in amount_of}
    groups: dict[int, list[dict]] = {}
    credit: dict[str, float] = {}
    loose: dict[str, list[dict]] = {}

    for r in sorted(_ar_scope(store, biz, store_id, T_ARR),
                    key=lambda x: (str(x.get("date") or ""), _i(x.get("id")))):
        if as_of and str(r.get("date") or "") > as_of:
            continue
        amt = r2(_f(r.get("amount")))
        if amt <= 0.005:
            continue
        key = ar_customer_key(r.get("customer"))
        iid = _i(r.get("invoice_id"))
        waiver = r2(_f(r.get("waiver")))
        if iid and iid in amount_of:
            # 指到哪张单就整笔冲哪张单：收多了不截断，让这张单的未收变成负数（预收）
            row = dict(r)
            row["_applied"] = amt
            row["_waiver"] = waiver
            groups.setdefault(iid, []).append(row)
            used[iid] = r2(used[iid] + amt)
            waived[iid] = r2(waived[iid] + waiver)
        else:
            loose.setdefault(key, []).append(dict(r))

    # 没指定应收单的收款：按客户先进先出，一张单冲完再冲下一张
    for inv in invoices:
        key = ar_customer_key(inv.get("customer"))
        iid = _i(inv.get("id"))
        queue = loose.get(key) or []
        while queue:
            room = r2(max(amount_of[iid] - used[iid], 0.0))
            if room <= 0.005:
                break
            row = queue[0]
            amt = r2(_f(row.get("amount")))
            take = r2(min(amt, room))
            shown = dict(row)
            shown["_applied"] = take
            shown["_waiver"] = r2(_f(row.get("waiver")))
            groups.setdefault(iid, []).append(shown)
            used[iid] = r2(used[iid] + take)
            waived[iid] = r2(waived[iid] + _f(row.get("waiver")))
            if amt - take > 0.005:
                row["amount"] = r2(amt - take)      # 余下的留给下一张单
                break
            queue.pop(0)
        if not queue:
            loose.pop(key, None)

    for key, rows in loose.items():
        left = r2(sum(_f(x.get("amount")) for x in rows))
        if left > 0.005:
            credit[key] = r2(credit.get(key, 0.0) + left)

    return groups, {k: v for k, v in credit.items() if v > 0.005}, used, waived


def ar_allocate(store, biz: str, store_id: int = 0,
                as_of: str = "") -> tuple[dict[int, float], dict[str, float]]:
    """按客户先进先出核销：返回（每张应收单已收金额, 各客户预收余额）。"""
    _groups, credit, used, _waived = _ar_receipt_groups(store, biz, store_id, as_of)
    return used, credit


def ar_waivers(store, biz: str, store_id: int = 0, as_of: str = "") -> dict[int, float]:
    """每张应收单收到的钱里抹掉的零头（元）。"""
    _groups, _credit, _used, waived = _ar_receipt_groups(store, biz, store_id, as_of)
    return waived


def ar_invoices(store, biz: str, store_id: int = 0, d1: str = "", d2: str = "",
                keyword: str = "") -> list[dict]:
    """应收款明细：一行一张应收单，带核销后的已收 / 未收（核销截至 d2）。"""
    alloc, _credit = ar_allocate(store, biz, store_id, d2)
    waivers = ar_waivers(store, biz, store_id, d2)
    smap = store_map(store)
    kw = str(keyword or "").strip()
    out: list[dict] = []
    for r in sorted(_ar_scope(store, biz, store_id),
                    key=lambda x: (str(x.get("date") or ""), _i(x.get("id")))):
        if not in_period(str(r.get("date") or ""), d1, d2):
            continue
        amount = r2(_f(r.get("amount")))
        paid = r2(alloc.get(_i(r.get("id")), 0.0))
        waiver = r2(waivers.get(_i(r.get("id")), 0.0))
        rec = dict(r)
        rec["_kind"] = "invoice"
        rec["_amount"] = amount
        rec["_received"] = paid
        rec["_waiver"] = waiver
        rec["_unpaid"] = r2(amount - paid - waiver)
        rec["_store_name"] = str((smap.get(_i(r.get("store_id"))) or {}).get("name") or "")
        rec["sale_batch"] = ar_sale_batch(r)
        rec["settle"] = ar_settle(store, r)
        rec["due_date"] = ar_due_date(store, rec)
        if kw:
            hay = " ".join(str(rec.get(k) or "") for k in
                           ("customer", "phone", "summary", "ref", "salesman", "remark",
                            "source", "sale_batch", "settle"))
            if kw not in hay:
                continue
        out.append(rec)
    return out


def ar_detail_rows(store, biz: str, store_id: int = 0, d1: str = "", d2: str = "",
                   keyword: str = "") -> list[dict]:
    """应收款明细（含收款子行）：一张应收单后面跟着它的每一笔收款。

    收款行 ``_kind="receipt"``、``id`` 取负数（与应收单 id 错开，界面才好分辨行属于哪张表），
    真实主键在 ``_rid``；``_unpaid`` 是收完这一笔之后的剩余未收，逐行往下减——照银行流水看。
    """
    groups, _credit, _used, _waived = _ar_receipt_groups(store, biz, store_id, d2)
    out: list[dict] = []
    for inv in ar_invoices(store, biz, store_id, d1, d2, keyword):
        out.append(inv)
        running = r2(_f(inv.get("_amount")))
        for r in groups.get(_i(inv.get("id")), []):
            applied = r2(r.get("_applied") if r.get("_applied") is not None else r.get("amount"))
            waiver = r2(r.get("_waiver") if r.get("_waiver") is not None else r.get("waiver"))
            running = r2(running - applied - waiver)   # 收超了就是负数：这部分是预收
            out.append({
                "_kind": "receipt",
                "id": -_i(r.get("id")),
                "_rid": _i(r.get("id")),
                "invoice_id": _i(inv.get("id")),
                "biz": str(r.get("biz") or biz),
                "store_id": _i(r.get("store_id")),
                "customer": str(inv.get("customer") or ""),
                "sale_batch": "",
                "date": str(r.get("date") or ""),            # 收款日期（真字段就叫 date）
                "receipt_date": str(r.get("date") or ""),
                "receipt_amount": r2(_f(r.get("amount"))),
                "waiver": r2(_f(r.get("waiver"))),
                "pay_method": str(r.get("pay_method") or ""),
                "remark": str(r.get("remark") or ""),
                "_applied": applied,
                "_unpaid": running,
            })
    return out


def ar_receipts(store, biz: str, store_id: int = 0, d1: str = "", d2: str = "",
                keyword: str = "") -> list[dict]:
    """收款流水（一行一笔到账）：界面上挂在应收单下面显示，这里用于合计与对账。"""
    smap = store_map(store)
    kw = str(keyword or "").strip()
    out: list[dict] = []
    for r in sorted(_ar_scope(store, biz, store_id, T_ARR),
                    key=lambda x: (str(x.get("date") or ""), _i(x.get("id")))):
        if not in_period(str(r.get("date") or ""), d1, d2):
            continue
        rec = dict(r)
        rec["_amount"] = r2(_f(r.get("amount")))
        rec["_store_name"] = str((smap.get(_i(r.get("store_id"))) or {}).get("name") or "")
        if kw:
            hay = " ".join(str(rec.get(k) or "") for k in
                           ("customer", "pay_method", "ref", "remark"))
            if kw not in hay:
                continue
        out.append(rec)
    return out


def _days_between(start: str, end: str) -> int:
    a, b = to_date(start), to_date(end)
    return (b - a).days if a and b else 0


def ar_open_items(store, biz: str, store_id: int = 0, as_of: str = "",
                  keyword: str = "", overdue_only: bool = False) -> list[dict]:
    """未收款：截至 as_of 仍有余额的应收单（先进先出核销后）。

    未收是**余额**概念，不按期间切：期间只影响应收 / 已收那两张表，
    这里始终是「截至业务日期还欠多少」，否则上月欠款会被切没。
    """
    day = str(as_of or today())
    alloc, _credit = ar_allocate(store, biz, store_id, day)
    smap = store_map(store)
    kw = str(keyword or "").strip()
    out: list[dict] = []
    waivers = ar_waivers(store, biz, store_id, day)
    for inv in _ar_scope(store, biz, store_id):
        amount = r2(_f(inv.get("amount")))
        paid = r2(alloc.get(_i(inv.get("id")), 0.0))
        waiver = r2(waivers.get(_i(inv.get("id")), 0.0))
        unpaid = r2(amount - paid - waiver)
        if unpaid <= 0.005:
            continue
        inv_date = str(inv.get("date") or "")
        rec = dict(inv)
        rec["sale_batch"] = ar_sale_batch(inv)
        rec["settle"] = ar_settle(store, inv)
        rec["due_date"] = ar_due_date(store, rec)
        due_date = str(rec.get("due_date") or "")
        overdue = _days_between(due_date, day) if due_date and due_date < day else 0
        if overdue_only and overdue <= 0:
            continue
        rec["_amount"] = amount
        rec["_received"] = paid
        rec["_waiver"] = waiver
        rec["_unpaid"] = unpaid
        rec["_age"] = max(_days_between(inv_date, day), 0) if inv_date else 0
        rec["_overdue"] = overdue
        rec["_store_name"] = str((smap.get(_i(inv.get("store_id"))) or {}).get("name") or "")
        if kw:
            hay = " ".join(str(rec.get(k) or "") for k in
                           ("customer", "phone", "summary", "ref", "salesman", "remark",
                            "source", "sale_batch", "settle"))
            if kw not in hay:
                continue
        out.append(rec)
    # 欠得久的在前；同账龄按金额大的在前——催收按这个顺序走
    return sorted(out, key=lambda r: (-_i(r.get("_age")), -_f(r.get("_unpaid"))))


def ar_summary(store, biz: str, store_id: int = 0, d1: str = "", d2: str = "",
               as_of: str = "") -> dict:
    """应收款项的合计数：期间应收 / 期间收款 / 截至日未收。"""
    invoices = ar_invoices(store, biz, store_id, d1, d2)
    receipts = ar_receipts(store, biz, store_id, d1, d2)
    opens = ar_open_items(store, biz, store_id, as_of or d2)
    _alloc, credit = ar_allocate(store, biz, store_id, as_of or d2)
    day = as_of or d2
    negatives = [r for r in invoices if _f(r.get("_unpaid")) < -0.005]
    return {
        "invoice_count": len(invoices),
        "invoice_amount": r2(sum(_f(r.get("_amount")) for r in invoices)),
        "receipt_count": len(receipts),
        "receipt_amount": r2(sum(_f(r.get("_amount")) for r in receipts)),
        "open_count": len(opens),
        "unpaid": r2(sum(_f(r.get("_unpaid")) for r in opens)),
        "overdue_count": sum(1 for r in opens if _f(r.get("_overdue")) > 0),
        "overdue": r2(sum(_f(r.get("_unpaid")) for r in opens if _f(r.get("_overdue")) > 0)),
        "customers": len({ar_customer_key(r.get("customer")) for r in opens}),
        # 预收：应收单被收成负数的部分（未收列示为负）+ 挂不到单上的余款
        "prepaid": r2(-sum(_f(r.get("_unpaid")) for r in negatives)),
        "credit": r2(sum(credit.values())),
        "as_of": day,
    }


def _ar_scope_labels(store) -> list[tuple[str, int, str]]:
    """两套账逐一核：屠宰销售（不分店）+ 每家门店的门店销售。"""
    out: list[tuple[str, int, str]] = [(AR_BIZ_SLAUGHTER, 0, "屠宰销售")]
    for st in sorted(store.rows(T_STORE), key=lambda s: _i(s.get("id"))):
        out.append((AR_BIZ_STORE, _i(st.get("id")), f"门店 {st.get('name') or st.get('id')}"))
    return out


# ---------------------------------------------------------------- 应付款项（活羊采购与付款）
def ap_supplier_key(name) -> str:
    """核销按供应商归口：空供应商统一落到「（未填供应商）」，免得各算各的。"""
    return str(name or "").strip() or AP_NO_SUPPLIER


def _ap_scope(store, table: str = T_AP) -> list[dict]:
    """应付款这一套账只有一本（活羊采购），不用 biz / 门店区分。"""
    return [dict(r) for r in store.rows(table)]


def ap_supplier_phone(store, name) -> str:
    """供应商电话：先在入库批次档案里找，再退回应付单上填的。"""
    key = str(name or "").strip()
    if not key:
        return ""
    for b in store.rows(T_BATCH):
        if str(b.get("supplier") or "").strip() == key:
            phone = str(b.get("supplier_phone") or "").strip()
            if phone:
                return phone
    return ""


def _ap_payment_groups(store, as_of: str = "") -> tuple[
        dict[int, list[dict]], dict[str, float], dict[int, float]]:
    """把付款逐笔挂到应付单上，同时算出每张单已付多少。

    归属规则跟应收一模一样：
        1. 付款上写了 ``invoice_id`` 的，整笔冲那张单——付多了就冲成负数（预付 / 多付）；
        2. 没写归属的（老账套 / 手工补录），按**供应商先进先出**冲到最早的应付单上，
           一张单最多冲到零，余下的钱挂在该供应商名下当预付。

    返回（{应付单 id: [付款行…]}, {供应商: 预付}, {应付单 id: 已付}）。
    核销池只算**截至 as_of 的付款**：期末之后才付的钱不能提前冲当期应付。
    """
    invoices = sorted(_ap_scope(store), key=lambda r: (str(r.get("date") or ""), _i(r.get("id"))))
    amount_of = {_i(r.get("id")): r2(_f(r.get("amount"))) for r in invoices}
    used: dict[int, float] = {iid: 0.0 for iid in amount_of}
    groups: dict[int, list[dict]] = {}
    prepaid: dict[str, float] = {}
    loose: dict[str, list[dict]] = {}

    for r in sorted(_ap_scope(store, T_APP), key=lambda x: (str(x.get("date") or ""), _i(x.get("id")))):
        if as_of and str(r.get("date") or "") > as_of:
            continue
        amt = r2(_f(r.get("amount")))
        if amt <= 0.005:
            continue
        key = ap_supplier_key(r.get("supplier"))
        iid = _i(r.get("invoice_id"))
        if iid and iid in amount_of:
            row = dict(r)
            row["_applied"] = amt
            groups.setdefault(iid, []).append(row)
            used[iid] = r2(used[iid] + amt)
        else:
            loose.setdefault(key, []).append(dict(r))

    # 没指定应付单的付款：按供应商先进先出，一张单冲完再冲下一张
    for inv in invoices:
        key = ap_supplier_key(inv.get("supplier"))
        iid = _i(inv.get("id"))
        queue = loose.get(key) or []
        while queue:
            room = r2(max(amount_of[iid] - used[iid], 0.0))
            if room <= 0.005:
                break
            row = queue[0]
            amt = r2(_f(row.get("amount")))
            take = r2(min(amt, room))
            shown = dict(row)
            shown["_applied"] = take
            groups.setdefault(iid, []).append(shown)
            used[iid] = r2(used[iid] + take)
            if amt - take > 0.005:
                row["amount"] = r2(amt - take)      # 余下的留给下一张单
                break
            queue.pop(0)
        if not queue:
            loose.pop(key, None)

    for key, rows_left in loose.items():
        left = r2(sum(_f(x.get("amount")) for x in rows_left))
        if left > 0.005:
            prepaid[key] = r2(prepaid.get(key, 0.0) + left)

    return groups, {k: v for k, v in prepaid.items() if v > 0.005}, used


def ap_allocate(store, as_of: str = "") -> tuple[dict[int, float], dict[str, float]]:
    """按供应商先进先出核销：返回（每张应付单已付金额, 各供应商预付余额）。"""
    _groups, prepaid, used = _ap_payment_groups(store, as_of)
    return used, prepaid


def ap_invoices(store, d1: str = "", d2: str = "", keyword: str = "") -> list[dict]:
    """应付款明细：一行一张应付单，带核销后的已付 / 未付（核销截至 d2）。"""
    alloc, _prepaid = ap_allocate(store, d2)
    kw = str(keyword or "").strip()
    out: list[dict] = []
    for r in sorted(_ap_scope(store), key=lambda x: (str(x.get("date") or ""), _i(x.get("id")))):
        if not in_period(str(r.get("date") or ""), d1, d2):
            continue
        amount = r2(_f(r.get("amount")))
        paid = r2(alloc.get(_i(r.get("id")), 0.0))
        rec = dict(r)
        rec["_kind"] = "invoice"
        rec["_amount"] = amount
        rec["_paid"] = paid
        rec["_unpaid"] = r2(amount - paid)
        rec["_batch_code"] = str(rec.get("batch_code")
                                  or batch_code(store, _i(rec.get("batch_id"))))
        if kw:
            hay = " ".join(str(rec.get(k) or "") for k in
                           ("supplier", "phone", "item", "ref", "remark", "source",
                            "batch_code"))
            if kw not in hay:
                continue
        out.append(rec)
    return out


def ap_detail_rows(store, d1: str = "", d2: str = "", keyword: str = "") -> list[dict]:
    """应付款明细（含付款子行）：一张应付单后面跟着它的每一笔付款。

    付款行 ``_kind="payment"``、``id`` 取负数（与应付单 id 错开），真实主键在 ``_rid``；
    ``_unpaid`` 是付完这一笔之后的剩余未付，逐行往下减——照银行流水看。
    """
    groups, _prepaid, _used = _ap_payment_groups(store, d2)
    out: list[dict] = []
    for inv in ap_invoices(store, d1, d2, keyword):
        out.append(inv)
        running = r2(_f(inv.get("_amount")))
        for r in groups.get(_i(inv.get("id")), []):
            applied = r2(r.get("_applied") if r.get("_applied") is not None else r.get("amount"))
            running = r2(running - applied)          # 付多了就是负数：这部分是预付 / 多付
            out.append({
                "_kind": "payment",
                "id": -_i(r.get("id")),
                "_rid": _i(r.get("id")),
                "invoice_id": _i(inv.get("id")),
                "supplier": str(inv.get("supplier") or ""),
                "batch_code": "",
                "date": str(r.get("date") or ""),            # 付款日期（真字段就叫 date）
                "pay_date": str(r.get("date") or ""),
                "pay_amount": r2(_f(r.get("amount"))),
                "pay_method": str(r.get("pay_method") or ""),
                "remark": str(r.get("remark") or ""),
                "_applied": applied,
                "_unpaid": running,
            })
    return out


def ap_payments(store, d1: str = "", d2: str = "", keyword: str = "") -> list[dict]:
    """付款流水（一行一笔出账）：界面上挂在应付单下面显示，这里用于合计与对账。"""
    kw = str(keyword or "").strip()
    out: list[dict] = []
    for r in sorted(_ap_scope(store, T_APP), key=lambda x: (str(x.get("date") or ""), _i(x.get("id")))):
        if not in_period(str(r.get("date") or ""), d1, d2):
            continue
        rec = dict(r)
        rec["_amount"] = r2(_f(r.get("amount")))
        if kw:
            hay = " ".join(str(rec.get(k) or "") for k in
                           ("supplier", "pay_method", "ref", "remark"))
            if kw not in hay:
                continue
        out.append(rec)
    return out


def ap_open_items(store, as_of: str = "", keyword: str = "",
                  aged_only: bool = False) -> list[dict]:
    """未付款：截至 as_of 仍有余额的应付单（先进先出核销后）。

    跟未收款一样是**余额**概念，不按期间切：期间只影响应付 / 已付，
    这里始终是「截至业务日期还欠供应商多少」，否则上月欠款会被切没。
    账龄 = 截至日 − 入库日期（一次采购一张单，账龄就是这笔货款挂了多久）。
    """
    day = str(as_of or today())
    alloc, _prepaid = ap_allocate(store, day)
    kw = str(keyword or "").strip()
    out: list[dict] = []
    for inv in _ap_scope(store):
        amount = r2(_f(inv.get("amount")))
        paid = r2(alloc.get(_i(inv.get("id")), 0.0))
        unpaid = r2(amount - paid)
        if unpaid <= 0.005:
            continue
        inv_date = str(inv.get("date") or "")
        rec = dict(inv)
        rec["batch_code"] = str(inv.get("batch_code") or batch_code(store, _i(inv.get("batch_id"))))
        rec["_amount"] = amount
        rec["_paid"] = paid
        rec["_unpaid"] = unpaid
        rec["_age"] = max(_days_between(inv_date, day), 0) if inv_date else 0
        rec["_aged"] = rec["_age"] >= AP_AGING_DAYS
        if aged_only and not rec["_aged"]:
            continue
        if kw:
            hay = " ".join(str(rec.get(k) or "") for k in
                           ("supplier", "phone", "item", "ref", "remark", "source",
                            "batch_code"))
            if kw not in hay:
                continue
        out.append(rec)
    # 挂得最久的在前；同账龄按金额大的在前——排付款计划按这个顺序走
    return sorted(out, key=lambda r: (-_i(r.get("_age")), -_f(r.get("_unpaid"))))


def ap_summary(store, d1: str = "", d2: str = "", as_of: str = "") -> dict:
    """应付款项的合计数：期间应付 / 期间付款 / 截至日未付。"""
    invoices = ap_invoices(store, d1, d2)
    payments = ap_payments(store, d1, d2)
    day = as_of or d2
    opens = ap_open_items(store, day)
    _alloc, prepaid = ap_allocate(store, day)
    negatives = [r for r in invoices if _f(r.get("_unpaid")) < -0.005]
    return {
        "invoice_count": len(invoices),
        "invoice_amount": r2(sum(_f(r.get("_amount")) for r in invoices)),
        "payment_count": len(payments),
        "payment_amount": r2(sum(_f(r.get("_amount")) for r in payments)),
        "open_count": len(opens),
        "unpaid": r2(sum(_f(r.get("_unpaid")) for r in opens)),
        "aged_count": sum(1 for r in opens if r.get("_aged")),
        "aged": r2(sum(_f(r.get("_unpaid")) for r in opens if r.get("_aged"))),
        "suppliers": len({ap_supplier_key(r.get("supplier")) for r in opens}),
        # 预付 / 多付：应付单被付成负数的部分 + 挂不到单上的余款
        "prepaid": r2(-sum(_f(r.get("_unpaid")) for r in negatives)),
        "credit": r2(sum(prepaid.values())),
        "as_of": day,
    }



# ---------------------------------------------------------------- 校验
def checks(store) -> list[CheckRow]:
    """全链路勾稽：批次存栏 → 屠宰出品 → 出库 → 门店库存。"""
    rows: list[CheckRow] = []

    # 1. 暂养台账：批次结存不能为负
    for bal in batch_balances(store):
        if bal.count < -0.001 or bal.weight < -0.001:
            rows.append(CheckRow("bad", f"暂养结存为负 · {bal.batch_code}",
                                 "该批次出库超过入库，先补入库或冲红错单",
                                 "≥ 0", f"{bal.count:,.1f} 只 / {bal.weight:,.1f} kg"))

    # 2. 暂养出库只数 ≤ 批次入库只数
    for b in store.rows(T_BATCH):
        bid = _i(b.get("id"))
        in_c = sum(_f(r.get("in_count")) for r in store.rows(T_FEED) if _i(r.get("batch_id")) == bid)
        out_c = sum(_f(r.get("out_count")) for r in store.rows(T_FEED) if _i(r.get("batch_id")) == bid)
        if in_c and out_c > in_c + 0.001:
            rows.append(CheckRow("bad", f"暂养出库超入库 · {b.get('code')}",
                                 "出库只数大于入库只数", f"{in_c:,.1f} 只", f"{out_c:,.1f} 只"))
        elif in_c and abs(in_c - _f(b.get("count"))) > 0.001:
            rows.append(CheckRow("warn", f"批次入栏只数与台账不一致 · {b.get('code')}",
                                 "批次档案入栏只数与暂养台账入库合计不等（改过台账或分批入栏）",
                                 f"{_f(b.get('count')):,.1f} 只", f"{in_c:,.1f} 只"))

    # 3. 养殖：累计出栏不超过批次入库只数
    for b in store.rows(T_BATCH):
        bid = _i(b.get("id"))
        out = sum(_f(r.get("out_count")) for r in store.rows(T_BREED) if _i(r.get("batch_id")) == bid)
        in_c = sum(_f(r.get("in_count")) for r in store.rows(T_FEED) if _i(r.get("batch_id")) == bid) \
            or _f(b.get("count"))
        if in_c and out > in_c + 0.001:
            rows.append(CheckRow("bad", f"养殖出栏超存栏 · {b.get('code')}",
                                 "养殖记录累计出栏大于批次入栏", f"{in_c:,.1f} 只", f"{out:,.1f} 只"))

    # 4. 屠宰单：产出必须登记，出肉率在合理区间
    for doc in slaughter_docs(store):
        if not doc["_line_count"]:
            rows.append(CheckRow("bad", f"屠宰单未登记产出 · {doc.get('doc_no')}",
                                 "主表有领入、产出明细为空", "≥ 1 行产出", "0 行"))
            continue
        if not _f(doc.get("in_weight")):
            rows.append(CheckRow("warn", f"屠宰单缺领入毛重 · {doc.get('doc_no')}",
                                 "没有毛重就算不出出肉率与单位成本", "> 0 kg", "0 kg"))
        rate = doc["_yield_rate"]
        if rate and not (0.30 <= rate <= 0.65):
            rows.append(CheckRow("warn", f"出肉率异常 · {doc.get('doc_no')}",
                                 "整羊出肉率一般 35%~55%，请核对领入毛重或产出 kg",
                                 "30%~65%", f"{rate * 100:,.1f}%"))

    # 5. 屠宰出库 ≤ 产出（按商品名汇总）
    produced: dict[str, float] = {}
    for ln in store.rows(T_YIELD):
        produced[str(ln.get("product") or "")] = produced.get(str(ln.get("product") or ""), 0.0) \
            + _f(ln.get("weight"))
    sold: dict[str, float] = {}
    for r in store.rows(T_SOUT):
        sold[str(r.get("product") or "")] = sold.get(str(r.get("product") or ""), 0.0) + _f(r.get("weight"))
    for product, w in sold.items():
        if w > produced.get(product, 0.0) + 0.05:
            rows.append(CheckRow("bad", f"屠宰出库超产出 · {product}",
                                 "出库 kg 大于该商品累计产出 kg，检查商品名称是否串行",
                                 f"{produced.get(product, 0.0):,.1f} kg", f"{w:,.1f} kg"))

    # 6. 门店：账面库存不能为负
    for row in store_book_stock(store):
        if row.weight < -0.05 or row.count < -0.001:
            rows.append(CheckRow("bad", f"门店库存为负 · {row.store_name} {row.product}",
                                 f"批次 {row.batch_code or '—'} 销售超过入库，先补入库单或核对销售批次",
                                 "≥ 0", f"{row.count:,.1f} 只 / {row.weight:,.1f} kg"))

    # 7. 门店销售：实收 − 应收 的差额（挂账属正常，只提示）
    unpaid = sum(_f(r.get("_unpaid")) for r in store_sale_rows(store))
    if unpaid > 0.005:
        rows.append(CheckRow("warn", "门店销售台账未收（挂账发生额）",
                             "应收 − 实收，是销售当时挂出去的账；之后收回多少记在「应收款项」里，"
                             "剩余余额见下一条「应收款项未收」",
                             "—", f"{unpaid:,.2f} 元"))

    # 8. 最新盘点 vs 账面
    seen: set[tuple[int, str, str]] = set()
    for r in sorted(store.rows(T_SSTOCK), key=lambda x: str(x.get("date") or "")):
        key = (_i(r.get("store_id")), str(r.get("_batch_code") or batch_code(store, _i(r.get("batch_id")))),
               str(r.get("product") or ""))
        if key in seen:
            continue
        seen.add(key)
        book = [x for x in store_book_stock(store, key[0])
                if x.batch_code == key[1] and x.product == key[2]]
        book_w = book[0].weight if book else 0.0
        diff = r2(_f(r.get("weight")) - book_w)
        if abs(diff) > 0.1:
            rows.append(CheckRow("warn", f"盘点差异 · {key[1] or '—'} {key[2]}",
                                 "实盘 kg 与账面入库−销售不一致，确认是损耗、串货还是漏单",
                                 f"账面 {book_w:,.1f} kg", f"实盘 {_f(r.get('weight')):,.1f} kg（差 {diff:+,.1f}）"))

    # 9. 应收款项：未收余额 / 超收 / 来源单已删
    for biz, sid, label in _ar_scope_labels(store):
        opens = ar_open_items(store, biz, sid)
        if opens:
            total = r2(sum(_f(x.get("_unpaid")) for x in opens))
            rows.append(CheckRow("warn", f"应收款项未收 · {label}",
                                 "按客户先进先出核销后的未收余额；对账 / 催收按客户跟进，"
                                 "明细见该模块「应收款项 · 未收款」",
                                 "—", f"{total:,.2f} 元 / {len(opens)} 笔"))
        _alloc, credit = ar_allocate(store, biz, sid)
        for cust, amt in credit.items():
            rows.append(CheckRow("warn", f"收款超过应收 · {label} {cust}",
                                 "该客户收款合计大于应收合计，确认是预收、还是客户名写岔了",
                                 "≤ 应收合计", f"预收 {amt:,.2f} 元"))
        for inv in ar_invoices(store, biz, sid):
            unpaid = _f(inv.get("_unpaid"))
            if unpaid >= -0.005:
                continue
            rows.append(CheckRow(
                "warn", f"预收款 · {label} {inv.get('customer') or '未填客户'}",
                f"{inv.get('sale_batch') or ''} 这张应收单收到的钱比应收多，"
                f"多出的部分在「未收金额」里以负数列示（预收）；"
                f"确认是客户预付、还是这笔收款登到了别的单上",
                "≤ 应收金额", f"预收 {-unpaid:,.2f} 元"))
        for inv in _ar_scope(store, biz, sid):
            link = str(inv.get("link_key") or "")
            if not link:
                continue
            kind, _sep, ref = link.partition(":")
            table = {"sout": T_SOUT, "sale": T_SSALE}.get(kind, "")
            if not table:
                continue
            source = store.get(table, _i(ref))
            if not source:
                rows.append(CheckRow("warn", f"应收单来源已删 · {label}",
                                     f"{inv.get('date')} {inv.get('customer') or '未填客户'} 的应收单"
                                     f"挂着 {link}，来源销售单已删除，确认是否连带冲销这笔应收",
                                     "来源单存在", f"应收 {_f(inv.get('amount')):,.2f} 元"))
                continue
            pay = str(source.get("pay_method") or "")
            if kind == "sout" and pay and pay not in CREDIT_PAY_METHODS:
                rows.append(CheckRow("warn", f"应收单来源已改为现款 · {label}",
                                     f"{inv.get('date')} {inv.get('customer') or '未填客户'} 的应收"
                                     f"{_f(inv.get('amount')):,.2f} 元 来自 {link}，"
                                     f"该出库单收款方式现在是「{pay}」；"
                                     f"若确实现款结清，请把这张应收连收款一起删掉",
                                     "挂账 / 月结", f"现为 {pay}"))

    # 10. 应付款项：未付余额 / 多付（预付）/ 来源批次已删
    opens = ap_open_items(store)
    if opens:
        total = r2(sum(_f(x.get("_unpaid")) for x in opens))
        aged = r2(sum(_f(x.get("_unpaid")) for x in opens if x.get("_aged")))
        rows.append(CheckRow(
            "warn", "应付款项未付 · 活羊采购与付款",
            "按供应商先进先出核销后的未付余额；排付款计划按账龄走，"
            "明细见「应付款项 · 活羊采购与付款 › 未付款」",
            "—", f"{total:,.2f} 元 / {len(opens)} 笔"
                 + (f"（其中账龄超 {AP_AGING_DAYS} 天 {aged:,.2f} 元）" if aged > 0.005 else "")))
    _alloc, prepaid = ap_allocate(store)
    for supplier, amt in prepaid.items():
        rows.append(CheckRow("warn", f"付款超过应付 · {supplier}",
                             "该供应商付款合计大于应付合计，确认是预付货款、还是供应商名写岔了",
                             "≤ 应付合计", f"预付 {amt:,.2f} 元"))
    for inv in ap_invoices(store):
        unpaid = _f(inv.get("_unpaid"))
        if unpaid >= -0.005:
            continue
        rows.append(CheckRow(
            "warn", f"多付款 · 活羊采购 {inv.get('supplier') or '未填供应商'}",
            f"{inv.get('batch_code') or ''} 这张应付单付的钱比应付多，"
            f"多出的部分在「未付款余额」里以负数列示（预付 / 多付）；"
            f"确认是预付货款、还是这笔付款登到了别的单上",
            "≤ 应付金额", f"多付 {-unpaid:,.2f} 元"))
    for inv in _ap_scope(store):
        link = str(inv.get("link_key") or "")
        ref = _i(str(link).partition(":")[2]) if str(link).startswith("batch:") else 0
        if not ref:
            continue
        if not store.get(T_BATCH, ref):
            rows.append(CheckRow("warn", "应付单来源批次已删 · 活羊采购",
                                 f"{inv.get('date')} {inv.get('supplier') or '未填供应商'} 的应付单"
                                 f"挂着 {link}，来源入库批次已删除，确认是否连带冲销这笔应付",
                                 "来源批次存在", f"应付 {_f(inv.get('amount')):,.2f} 元"))

    if not rows:
        rows.append(CheckRow("ok", "全部勾稽通过", "暂养、养殖、屠宰、出库、门店库存均对得上", "—", "—"))
    return rows


def dashboard_stats(store, day: str) -> dict:
    """概览指标：一天的经营 + 全盘结存。"""
    from mscm.core.models import month_start
    m1 = month_start(day)
    balances = batch_balances(store, day)
    docs = slaughter_docs(store, m1, day)
    sales = store_sale_rows(store, 0, m1, day)
    outs = slaughter_out_rows(store, m1, day)
    book = store_book_stock(store, 0, day)
    month_sale = r2(sum(_f(r.get("_due")) for r in sales))
    month_out = r2(sum(_f(r.get("_amount")) for r in outs))
    return {
        "pen_count": r1(sum(b.count for b in balances)),
        "pen_weight": r1(sum(b.weight for b in balances)),
        "pen_amount": r2(sum(b.amount for b in balances)),
        "breed_stock": r1(sum(current_stock(store, _i(b.get("id"))) for b in store.rows(T_BATCH))),
        "month_slaughter": len(docs),
        "month_in_count": r1(sum(_f(d.get("in_count")) for d in docs)),
        "month_yield_weight": r1(sum(_f(d.get("_out_weight")) for d in docs)),
        "month_yield_rate": (sum(_f(d.get("_out_weight")) for d in docs)
                             / sum(_f(d.get("in_weight")) for d in docs))
                            if sum(_f(d.get("in_weight")) for d in docs) else 0.0,
        "store_stock_weight": r1(sum(r.weight for r in book)),
        "store_stock_amount": r2(sum(r.amount for r in book)),
        "month_sale": month_sale,
        "month_out": month_out,
        "month_unpaid": r2(sum(_f(r.get("_unpaid")) for r in sales)),
        # 毛利不在这里算：要区分直销 / 调拨、按已售商品成本配比，见 pages/dashboard._gross
    }
