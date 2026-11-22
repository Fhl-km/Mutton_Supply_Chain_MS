"""数据仓库：档案维护 + 台账增删改 + 下拉数据源。

UI 只跟这里打交道，不直接碰 JsonStore 的表结构：
新增 / 编辑 / 删除都在这里收口（含「批次品类回填」「屠宰单连同产出明细一起删」
这类一致性动作），界面层不重复写一遍。
"""

from __future__ import annotations

from datetime import date

from mscm.core import calc
from mscm.core.models import (
    AP_ITEM_DEFAULT, AR_BIZ_SLAUGHTER, CREDIT_PAY_METHODS, CUSTOMER_ORGS,
    DEFAULT_PRODUCTS, DEFAULT_STORE_NAME, SHEEP_CATEGORIES,
    T_AP, T_APP, T_AR, T_ARR, T_BATCH, T_BREED, T_CUSTOMER, T_FEED, T_PRODUCT, T_SLAUGHTER,
    T_SOUT, T_SIN, T_SSALE, T_SSTOCK, T_STORE, T_YIELD,
    norm_sale_batch, r1, r2, sale_batch_code, sale_batch_date, settle_due_date, today,
)


# ---------------------------------------------------------------- 设置
def get_setting(conn, key: str, default: str = "") -> str:
    return conn.setting(key, default)


def set_setting(conn, key: str, value) -> None:
    conn.set_setting(key, value)
    conn.commit()


# ---------------------------------------------------------------- 门店
def list_stores(conn, only_active: bool = True) -> list[dict]:
    rows = [s for s in conn.rows(T_STORE) if not only_active or s.get("is_active", True)]
    return sorted(rows, key=lambda s: (str(s.get("code") or ""), int(s.get("id") or 0)))


def get_store(conn, store_id: int) -> dict | None:
    return conn.get(T_STORE, store_id)


def store_name(conn, store_id: int) -> str:
    row = conn.get(T_STORE, store_id) or {}
    return str(row.get("name") or "")


def store_options(conn) -> list[str]:
    return [str(s.get("name")) for s in list_stores(conn)]


def store_id_by_name(conn, name: str) -> int:
    for s in list_stores(conn, only_active=False):
        if str(s.get("name")) == str(name or ""):
            return int(s.get("id") or 0)
    return 0


def save_store(conn, data: dict, rid: int | None = None) -> dict:
    row = conn.update(T_STORE, int(rid), data) if rid else conn.insert(T_STORE, data)
    conn.commit()
    return row or {}


def delete_store(conn, store_id: int) -> tuple[bool, str]:
    used = sum(len([r for r in conn.rows(t) if int(r.get("store_id") or 0) == int(store_id)])
               for t in (T_SIN, T_SSALE, T_SSTOCK, T_SOUT))
    if used:
        return False, f"该门店已有 {used} 条台账记录，先删记录再删门店"
    conn.delete(T_STORE, store_id)
    conn.commit()
    return True, ""


# ---------------------------------------------------------------- 批次
def list_batches(conn, only_open: bool = False) -> list[dict]:
    rows = list(conn.rows(T_BATCH))
    if only_open:
        rows = [b for b in rows if str(b.get("status") or "在养") != "已清栏"]
    return sorted(rows, key=lambda b: str(b.get("code") or ""))


def get_batch(conn, batch_id: int) -> dict | None:
    return conn.get(T_BATCH, batch_id)


def batch_label(b: dict) -> str:
    """下拉里显示的批次名：编号（品类 · 圈号）。"""
    code = str(b.get("code") or "")
    extra = " · ".join(x for x in (str(b.get("category") or ""), str(b.get("pen") or "")) if x)
    return f"{code}（{extra}）" if extra else code


def batch_options(conn, include_blank: bool = False) -> list[tuple[str, int]]:
    out = [(batch_label(b), int(b.get("id") or 0)) for b in list_batches(conn)]
    return ([("（不指定批次）", 0)] if include_blank else []) + out


def batch_code(conn, batch_id: int) -> str:
    return str((conn.get(T_BATCH, batch_id) or {}).get("code") or "")


def batch_category(conn, batch_id: int) -> str:
    return str((conn.get(T_BATCH, batch_id) or {}).get("category") or "")


def batch_code_for(conn, entry_date: str, exclude_id: int | None = None) -> str:
    """批次编号＝采购入库日期（YYYYMMDD）；同一天进两批就挂 -2、-3。"""
    base = str(entry_date or today()).replace("-", "").strip()[:8]
    if len(base) != 8 or not base.isdigit():
        base = today().replace("-", "")
    taken = {str(b.get("code") or "") for b in conn.rows(T_BATCH)
             if int(b.get("id") or 0) != int(exclude_id or 0)}
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def batch_usage(conn, batch_id: int) -> int:
    return sum(len([r for r in conn.rows(t) if int(r.get("batch_id") or 0) == int(batch_id)])
               for t in (T_FEED, T_BREED, T_SLAUGHTER, T_SOUT, T_SIN, T_SSALE, T_SSTOCK))


def save_batch(conn, data: dict, rid: int | None = None) -> dict:
    """批次（采购入库）是入库数据的唯一来源：存完顺手刷一遍暂养台账的入库行。

    编号在这里兜一遍底：不管谁调用，都按采购入库日期重算，免得出两个口径。
    """
    payload = dict(data)
    payload["code"] = batch_code_for(conn, str(payload.get("entry_date") or today()),
                                     exclude_id=rid)
    row = conn.update(T_BATCH, int(rid), payload) if rid else conn.insert(T_BATCH, payload)
    conn.commit()
    if row:
        sync_feed_inbound(conn, row)
        sync_ap_from_batches(conn)      # 采购金额 / 供应商 / 日期改了，应付单跟着变
    return row or {}


def delete_batch(conn, batch_id: int) -> tuple[bool, str]:
    used = batch_usage(conn, batch_id)
    if used:
        return False, f"该批次已被 {used} 条台账记录使用，先删记录再删批次"
    conn.delete(T_BATCH, batch_id)
    conn.commit()
    return True, ""


# ---------------------------------------------------------------- 商品
def list_products(conn) -> list[dict]:
    return sorted(conn.rows(T_PRODUCT), key=lambda p: (str(p.get("cat") or ""), int(p.get("id") or 0)))


def product_names(conn) -> list[str]:
    return [str(p.get("name")) for p in list_products(conn) if p.get("name")]


def product_cat(conn, name: str) -> str:
    for p in conn.rows(T_PRODUCT):
        if str(p.get("name")) == str(name or ""):
            return str(p.get("cat") or "")
    return ""


def save_product(conn, data: dict, rid: int | None = None) -> dict:
    row = conn.update(T_PRODUCT, int(rid), data) if rid else conn.insert(T_PRODUCT, data)
    conn.commit()
    return row or {}


def delete_product(conn, pid: int) -> tuple[bool, str]:
    name = str((conn.get(T_PRODUCT, pid) or {}).get("name") or "")
    used = sum(len([r for r in conn.rows(t) if str(r.get("product") or "") == name])
               for t in (T_YIELD, T_SOUT, T_SIN, T_SSALE, T_SSTOCK))
    if used:
        return False, f"「{name}」已被 {used} 条台账记录使用，不能删除"
    conn.delete(T_PRODUCT, pid)
    conn.commit()
    return True, ""


# ---------------------------------------------------------------- 客户名录
def list_customers(conn, org: str = "") -> list[dict]:
    """客户名录：屠宰场那块排在前面，门店那块排在后面（与模板的列法一致）。"""
    order = {name: i for i, name in enumerate(CUSTOMER_ORGS)}
    rows = [c for c in conn.rows(T_CUSTOMER) if c.get("is_active", True)]
    if org:
        rows = [c for c in rows if str(c.get("org") or "") == str(org)]
    return sorted(rows, key=lambda c: (order.get(str(c.get("org") or ""), 99),
                                       int(c.get("id") or 0)))


def customer_names(conn, org: str = "") -> list[str]:
    return [str(c.get("name") or "").strip() for c in list_customers(conn, org)
            if str(c.get("name") or "").strip()]


def save_customer(conn, data: dict, rid: int | None = None) -> dict:
    payload = dict(data)
    payload["name"] = str(payload.get("name") or "").strip()
    row = conn.update(T_CUSTOMER, int(rid), payload) if rid else conn.insert(T_CUSTOMER, payload)
    conn.commit()
    return row or {}


def delete_customer(conn, cid: int) -> tuple[bool, str]:
    """已被销售 / 应收挂过账的客户不给删，免得台账里剩一个查不到的名字。"""
    name = str((conn.get(T_CUSTOMER, cid) or {}).get("name") or "").strip()
    used = sum(len([r for r in conn.rows(t) if str(r.get("customer") or "").strip() == name])
               for t in (T_SOUT, T_SSALE, T_AR, T_ARR)) if name else 0
    if used:
        return False, f"「{name}」已有 {used} 条销售 / 应收记录，先把这些记录处理掉再删"
    conn.delete(T_CUSTOMER, cid)
    conn.commit()
    return True, ""


# ---------------------------------------------------------------- 暂养台账的「入库行」
def feed_kind(row: dict) -> str:
    """一行是入库行还是出库行（老数据没这字段，就按有没有入库数量推断）。"""
    kind = str(row.get("row_kind") or "").strip()
    if kind in ("in", "out"):
        return kind
    return "in" if (float(row.get("in_count") or 0) or float(row.get("in_weight") or 0)) else "out"


def feed_inbound_row(conn, batch_id: int) -> dict | None:
    for r in conn.rows(T_FEED):
        if int(r.get("batch_id") or 0) == int(batch_id) and feed_kind(r) == "in":
            return r
    return None


def sync_feed_inbound(conn, batch: dict) -> dict | None:
    """把「活羊入库&结余」的采购数据刷到暂养台账的入库行；没有就补一行。

    只动入库侧（日期 / 供应商 / 只数 / kg / 单价）与品类，出库与备注原样保留。
    """
    bid = int(batch.get("id") or 0)
    if not bid:
        return None
    payload = {
        "date": str(batch.get("entry_date") or today()),
        "batch_id": bid,
        "category": str(batch.get("category") or ""),
        "in_supplier": str(batch.get("supplier") or ""),
        "in_tag": str(batch.get("tag") or ""),
        "in_count": float(batch.get("count") or 0),
        "in_weight": float(batch.get("weight") or 0),
        "in_price": float(batch.get("price") or 0),
        "row_kind": "in",
    }
    row = feed_inbound_row(conn, bid)
    if row is None:
        payload.update({"out_use": "", "out_count": 0.0, "out_weight": 0.0,
                        "remark": "由活羊入库&结余自动生成"})
        created = conn.insert(T_FEED, payload)
        conn.commit()
        return created
    conn.update(T_FEED, int(row.get("id") or 0), payload)
    conn.commit()
    return row


def ensure_feed_inbound(conn) -> int:
    """老账套升级：标好每行的入/出库属性，给缺入库行的批次补一行。返回补了几行。"""
    made = 0
    for r in conn.rows(T_FEED):
        kind = feed_kind(r)
        if r.get("row_kind") != kind:
            r["row_kind"] = kind
            conn.touch()
    for b in conn.rows(T_BATCH):
        inbound = feed_inbound_row(conn, int(b.get("id") or 0))
        # 老账套：批次还没有「标识」时，从它原来的入库行接过来，别把人工填的耳标丢了
        if inbound is not None and not str(b.get("tag") or "").strip() \
                and str(inbound.get("in_tag") or "").strip():
            conn.update(T_BATCH, int(b.get("id") or 0), {"tag": inbound.get("in_tag")})
            b["tag"] = inbound.get("in_tag")
        if inbound is None and float(b.get("count") or 0) > 0:
            sync_feed_inbound(conn, b)
            made += 1
    conn.commit()
    return made


def ensure_batch_codes(conn) -> int:
    """把老编号（Y2026-001 之类）改成「采购日期」编号。返回改了几个。"""
    changed = 0
    for b in sorted(conn.rows(T_BATCH), key=lambda x: (str(x.get("entry_date") or ""),
                                                       int(x.get("id") or 0))):
        code = str(b.get("code") or "")
        want = batch_code_for(conn, str(b.get("entry_date") or ""), exclude_id=int(b.get("id") or 0))
        if code != want:
            conn.update(T_BATCH, int(b.get("id") or 0), {"code": want})
            changed += 1
    if changed:
        conn.commit()
    return changed


# ---------------------------------------------------------------- 通用台账 CRUD
def save_row(conn, table: str, data: dict, rid: int | None = None) -> dict:
    row = conn.update(table, int(rid), data) if rid else conn.insert(table, data)
    conn.commit()
    return row or {}


def delete_row(conn, table: str, rid: int) -> None:
    conn.delete(table, rid)
    conn.commit()


# ---------------------------------------------------------------- 屠宰单（主 + 明细）
def next_doc_no(conn, day: str) -> str:
    """屠宰单号：TZ-20261120-01，同一天按顺序编号。"""
    stem = "TZ-" + str(day or today()).replace("-", "") + "-"
    nums = []
    for d in conn.rows(T_SLAUGHTER):
        no = str(d.get("doc_no") or "")
        if no.startswith(stem):
            try:
                nums.append(int(no[len(stem):]))
            except ValueError:
                pass
    return f"{stem}{(max(nums) + 1 if nums else 1):02d}"


def save_slaughter(conn, data: dict, lines: list[dict], rid: int | None = None) -> dict:
    """保存屠宰单：主表 + 产出明细整体替换（明细没有独立身份，跟着单走）。"""
    if rid:
        doc = conn.update(T_SLAUGHTER, int(rid), data) or {}
        for old in [x for x in conn.rows(T_YIELD) if int(x.get("slaughter_id") or 0) == int(rid)]:
            conn.delete(T_YIELD, int(old.get("id") or 0))
    else:
        doc = conn.insert(T_SLAUGHTER, data)
    did = int(doc.get("id") or 0)
    for ln in lines:
        row = dict(ln)
        row["slaughter_id"] = did
        row["amount"] = r2(float(row.get("weight") or 0) * float(row.get("price") or 0))
        conn.insert(T_YIELD, row)
    conn.commit()
    return doc


def delete_slaughter(conn, rid: int) -> None:
    for old in [x for x in conn.rows(T_YIELD) if int(x.get("slaughter_id") or 0) == int(rid)]:
        conn.delete(T_YIELD, int(old.get("id") or 0))
    conn.delete(T_SLAUGHTER, rid)
    conn.commit()


def find_slaughter_by_no(conn, doc_no: str) -> dict | None:
    for d in conn.rows(T_SLAUGHTER):
        if str(d.get("doc_no") or "") == str(doc_no or ""):
            return d
    return None


# ---------------------------------------------------------------- 调拨贯通：屠宰出库 → 门店入库
def sync_store_in_from_out(conn) -> tuple[int, int, list[str]]:
    """把「去向 = 门店调拨」的屠宰出库单转成门店入库单。

    幂等：门店入库行上记 ``link_id`` = 屠宰出库行 id，已转过的跳过。
    返回（新增条数, 跳过条数, 提示）。
    """
    created = skipped = 0
    msgs: list[str] = []
    existing = {int(r.get("link_id") or 0) for r in conn.rows(T_SIN)}
    for r in sorted(conn.rows(T_SOUT), key=lambda x: int(x.get("id") or 0)):
        rid = int(r.get("id") or 0)
        if str(r.get("target") or "") != "门店调拨":
            continue
        sid = int(r.get("store_id") or 0)
        if not sid:
            msgs.append(f"出库单 #{rid} 去向是门店调拨但没选门店，已跳过")
            continue
        if rid in existing:
            skipped += 1
            continue
        conn.insert(T_SIN, {
            "store_id": sid,
            "date": str(r.get("date") or today()),
            "source": "屠宰场调拨",
            "batch_id": int(r.get("batch_id") or 0),
            "product": str(r.get("product") or ""),
            "count": float(r.get("count") or 0),
            "weight": float(r.get("weight") or 0),
            "price": float(r.get("price") or 0),
            "remark": f"由屠宰出库单 #{rid} 自动生成",
            "link_id": rid,
        })
        created += 1
    conn.commit()
    return created, skipped, msgs


# ---------------------------------------------------------------- 应收款项（应收单 + 挂在单上的收款）
def ar_customers(conn, biz: str, store_id: int = 0) -> list[str]:
    """客户候选：本套账已有应收 / 收款的客户，加上销售单上出现过的客户。"""
    names: set[str] = set()
    for table in (T_AR, T_ARR):
        for r in conn.rows(table):
            if str(r.get("biz") or "") != str(biz or ""):
                continue
            if store_id and int(r.get("store_id") or 0) != int(store_id):
                continue
            name = str(r.get("customer") or "").strip()
            if name:
                names.add(name)
    if biz == AR_BIZ_SLAUGHTER:
        for r in conn.rows(T_SOUT):
            if str(r.get("target") or "") in ("对外销售", "客户直供"):
                name = str(r.get("customer") or "").strip()
                if name:
                    names.add(name)
    else:
        for r in conn.rows(T_SSALE):
            if store_id and int(r.get("store_id") or 0) != int(store_id):
                continue
            name = str(r.get("customer") or "").strip()
            if name:
                names.add(name)
    # 客户名录就是客户底表：名录里登记过的名字，应收填客户时直接可选，不用重录一遍
    org = CUSTOMER_ORGS[0] if biz == AR_BIZ_SLAUGHTER else CUSTOMER_ORGS[1]
    for name in customer_names(conn, org):
        names.add(name)
    return sorted(names)


def save_ar_invoice(conn, data: dict, rid: int | None = None) -> dict:
    """存一张应收单：销售批次 / 销售日期 / 结算方式 / 约定收款日在这里兜一遍底。

    界面上的「销售批次」才是主字段：销售日期＝销售批次后 8 位；结算方式从客户名录带；
    约定收款日 = 销售日期 + 账期（填过就尊重填的，不再覆盖）。
    """
    payload = dict(data)
    payload["sale_batch"] = norm_sale_batch(payload.get("sale_batch"),
                                            payload.get("date") or today())
    day = sale_batch_date(payload["sale_batch"]) or str(payload.get("date") or today())
    payload["date"] = day
    settle = str(payload.get("settle") or "").strip() \
        or calc.customer_settle(conn, payload.get("customer"))
    payload["settle"] = settle
    if not str(payload.get("due_date") or "").strip():
        payload["due_date"] = settle_due_date(day, settle)
    row = conn.update(T_AR, int(rid), payload) if rid else conn.insert(T_AR, payload)
    conn.commit()
    return row or {}


def delete_ar_invoice(conn, rid: int) -> None:
    """删应收单：挂在这张单上的收款一起删，免得留下没人认领的到账款。"""
    for r in [x for x in conn.rows(T_ARR) if int(x.get("invoice_id") or 0) == int(rid)]:
        conn.delete(T_ARR, int(r.get("id") or 0))
    conn.delete(T_AR, rid)
    conn.commit()


def save_ar_receipt(conn, data: dict, rid: int | None = None) -> dict:
    payload = dict(data)
    payload["invoice_id"] = int(payload.get("invoice_id") or 0)
    row = conn.update(T_ARR, int(rid), payload) if rid else conn.insert(T_ARR, payload)
    conn.commit()
    return row or {}


def delete_ar_receipt(conn, rid: int) -> None:
    conn.delete(T_ARR, rid)
    conn.commit()


# ---------------------------------------------------------------- 应收自动提取
def _ar_defaults(conn, day: str, target: str, customer: str) -> dict:
    """应收单的派生字段：销售批次（类型编码 + 日期）、结算方式（客户名录）、约定收款日。"""
    settle = calc.customer_settle(conn, customer)
    return {
        "sale_batch": sale_batch_code(day, target),
        "settle": settle,
        "due_date": settle_due_date(day, settle),
    }


def ar_candidates(conn, biz: str, store_id: int = 0) -> list[dict]:
    """销售单里「该挂账」的行 → 应收单草案（自动提取的唯一口径）。

    屠宰销售：去向为对外销售 / 客户直供，且收款方式为挂账 / 月结的出库单（全额）；
    门店销售：应收 > 实收的差额（挂账的那部分）。
    """
    out: list[dict] = []
    if biz == AR_BIZ_SLAUGHTER:
        for r in sorted(conn.rows(T_SOUT), key=lambda x: (str(x.get("date") or ""),
                                                          int(x.get("id") or 0))):
            if str(r.get("target") or "") not in ("对外销售", "客户直供"):
                continue
            pay = str(r.get("pay_method") or "")
            if pay not in CREDIT_PAY_METHODS:
                continue
            amount = r2(float(r.get("weight") or 0) * float(r.get("price") or 0))
            if amount <= 0.005:
                continue
            cust = str(r.get("customer") or "").strip()
            day = str(r.get("date") or today())
            out.append({
                "biz": biz, "store_id": 0, "date": day,
                "customer": cust, "phone": str(r.get("phone") or ""),
                "summary": str(r.get("product") or ""), "amount": amount,
                "salesman": str(r.get("salesman") or ""),
                "source": "屠宰销售", "ref": f"出库#{int(r.get('id') or 0)}",
                "link_key": f"sout:{int(r.get('id') or 0)}",
                "remark": f"按出库单自动提取（{pay or '挂账'}）",
                **_ar_defaults(conn, day, str(r.get("target") or ""), cust),
            })
        return out

    for r in sorted(conn.rows(T_SSALE), key=lambda x: (str(x.get("date") or ""),
                                                       int(x.get("id") or 0))):
        if store_id and int(r.get("store_id") or 0) != int(store_id):
            continue
        due = r2(float(r.get("due") or 0)
                 or float(r.get("weight") or 0) * float(r.get("price") or 0))
        paid = r2(float(r.get("paid") or 0))
        unpaid = r2(due - paid)
        if unpaid <= 0.005:
            continue
        cust = str(r.get("customer") or "").strip()
        day = str(r.get("date") or today())
        out.append({
            "biz": biz, "store_id": int(r.get("store_id") or 0), "date": day,
            "customer": cust, "phone": str(r.get("phone") or ""),
            "summary": str(r.get("product") or ""), "amount": unpaid,
            "salesman": str(r.get("salesman") or ""),
            "source": "门店销售", "ref": f"销售#{int(r.get('id') or 0)}",
            "link_key": f"sale:{int(r.get('id') or 0)}",
            "remark": f"销售挂账差额（应收 {due:,.2f} / 实收 {paid:,.2f}）",
            **_ar_defaults(conn, day, str(r.get("target") or ""), cust),
        })
    return out


def seed_ar_from_sales(conn, biz: str, store_id: int = 0) -> tuple[int, int, list[str]]:
    """按销售单的挂账部分铺应收单（幂等：link_key 记来源行，生成过的跳过）。"""
    same_scope = [r for r in conn.rows(T_AR)
                  if str(r.get("biz") or "") == str(biz or "")
                  and (not store_id or int(r.get("store_id") or 0) == int(store_id))]
    existing = {str(r.get("link_key") or "") for r in same_scope}
    created = skipped = 0
    msgs: list[str] = []
    for cand in ar_candidates(conn, biz, store_id):
        if cand["link_key"] in existing:
            skipped += 1
            continue
        if not cand["customer"]:
            msgs.append(f"{cand['ref']} 是挂账但没填客户，已按「未填客户」入账")
        conn.insert(T_AR, cand)
        created += 1
    if created:
        conn.commit()
    return created, skipped, msgs


def sync_ar_from_sales(conn, biz: str, store_id: int = 0) -> tuple[int, int, int]:
    """自动提取应收：缺的补上、销售单改了金额 / 客户 / 日期的跟着更新、改错的撤掉。

    幂等、可反复跑（进应收页、点「按销售挂账重算」都会走这里）。

    两条安全边界：
        · 销售单的收款方式改成现款后，**还没收到钱**的应收单自动撤掉（改错的挂账不该挂在账上）；
        · 已经登记过收款的应收单不自动删——怕把出纳登的钱一起冲掉，改由「数据校验」提示人工处理。
    返回（新增, 更新, 撤销）。
    """
    same_scope = [r for r in conn.rows(T_AR)
                  if str(r.get("biz") or "") == str(biz or "")
                  and (not store_id or int(r.get("store_id") or 0) == int(store_id))]
    by_key = {str(r.get("link_key") or ""): r for r in same_scope if str(r.get("link_key") or "")}
    cands = ar_candidates(conn, biz, store_id)
    cand_keys = {str(c["link_key"]) for c in cands}
    paid_ids = {int(r.get("invoice_id") or 0) for r in conn.rows(T_ARR)
                if int(r.get("invoice_id") or 0)}
    created = updated = cancelled = 0

    for cand in cands:
        old = by_key.get(cand["link_key"])
        if old is None:
            conn.insert(T_AR, cand)
            created += 1
            continue
        patch: dict = {}
        for key in ("date", "customer", "phone", "summary", "amount", "salesman",
                    "sale_batch", "ref"):
            if key in ("customer", "phone", "summary") and not str(cand.get(key) or "").strip():
                continue            # 销售单上是空的：别把人在应收里补的客户 / 摘要抹掉
            if str(old.get(key) or "") != str(cand.get(key) or ""):
                patch[key] = cand[key]
        if not str(old.get("settle") or "").strip() and cand["settle"]:
            patch["settle"] = cand["settle"]
        if not str(old.get("due_date") or "").strip() and cand["due_date"]:
            patch["due_date"] = cand["due_date"]
        if patch:
            conn.update(T_AR, int(old.get("id") or 0), patch)
            updated += 1

    # 来源单改成了现款：没收到钱的自动撤掉；收过钱的留着，交校验页提示
    for key, old in by_key.items():
        if key in cand_keys:
            continue
        target, src = _source_of_link(conn, key)
        if not src:
            continue                        # 来源单已删：不自动删，校验页会提示
        credit = str(src.get("pay_method") or "") in CREDIT_PAY_METHODS and (
            key.startswith("sale:") or target in ("对外销售", "客户直供"))
        if credit:
            continue                        # 还是挂账，只是金额为 0 之类，别动
        if int(old.get("id") or 0) in paid_ids:
            continue
        conn.delete(T_AR, int(old.get("id") or 0))
        cancelled += 1

    if created or updated or cancelled:
        conn.commit()
    return created, updated, cancelled


def _source_of_link(conn, link_key: str) -> tuple[str, dict]:
    """link_key（sout:12 / sale:8）→（去向, 来源行），用来补销售批次。"""
    kind, _sep, ref = str(link_key or "").partition(":")
    table = {"sout": T_SOUT, "sale": T_SSALE}.get(kind, "")
    row = conn.get(table, int(ref)) if table and str(ref).isdigit() else None
    return str((row or {}).get("target") or ""), (row or {})


def ensure_ar_links(conn) -> tuple[int, int]:
    """老账套升级：应收单补销售批次 / 结算方式 / 约定收款日；老收款挂到应收单上。

    收款以前是单独一张表、不认单的，现在要按「一对多」挂在应收单下面，
    所以这里按客户先进先出给它找主；一笔钱横跨两张单时，把它拆成两条（合计金额不变）。
    返回（补了几张应收单, 拆了几笔收款）。
    """
    fixed = split = 0
    for inv in conn.rows(T_AR):
        patch: dict = {}
        sale_batch = str(inv.get("sale_batch") or "").strip()
        if not sale_batch:
            target, _src = _source_of_link(conn, str(inv.get("link_key") or ""))
            sale_batch = sale_batch_code(str(inv.get("date") or ""), target)
            patch["sale_batch"] = sale_batch
        settle = str(inv.get("settle") or "").strip() or calc.customer_settle(
            conn, inv.get("customer"))
        if settle and str(inv.get("settle") or "").strip() != settle:
            patch["settle"] = settle
        if settle and not str(inv.get("due_date") or "").strip():
            day = sale_batch_date(sale_batch) or str(inv.get("date") or "")
            due = settle_due_date(day, settle)
            if due:
                patch["due_date"] = due
        if patch:
            conn.update(T_AR, int(inv.get("id") or 0), patch)
            fixed += 1

    # 屠宰销售 + 每家门店的门店销售各跑一遍（按应收单里出现过的 biz/store 组合认）
    seen = {(str(r.get("biz") or ""), int(r.get("store_id") or 0)) for r in conn.rows(T_AR)}
    scopes = sorted(seen) or [(AR_BIZ_SLAUGHTER, 0)]

    for _round in range(4):        # 拆出来的余款要再挂一次，最多跑 4 轮
        changed = 0
        for biz, sid in scopes:
            groups, _credit, _used, _waived = calc._ar_receipt_groups(conn, biz, sid)
            for iid, rows in groups.items():
                for r in rows:
                    rid = int(r.get("id") or 0)
                    if not rid or int(r.get("invoice_id") or 0) == int(iid):
                        continue
                    applied = r2(r.get("_applied") if r.get("_applied") is not None
                                 else r.get("amount"))
                    amt = r2(r.get("amount"))
                    if applied <= 0.005:
                        continue
                    if applied >= amt - 0.005:
                        conn.update(T_ARR, rid, {"invoice_id": int(iid)})
                    else:                       # 一笔钱要冲两张单：拆开，各挂各的
                        tail = {k: v for k, v in r.items()
                                if k not in ("id", "created_at", "updated_at", "_applied")}
                        conn.update(T_ARR, rid, {
                            "invoice_id": int(iid), "amount": applied,
                            "remark": (str(r.get("remark") or "") + "（一笔款跨两张单，已拆分）").strip(),
                        })
                        tail["invoice_id"] = 0
                        tail["amount"] = r2(amt - applied)
                        tail["remark"] = (str(tail.get("remark") or "")
                                          + "（拆分余款）").strip()
                        conn.insert(T_ARR, tail)
                        split += 1
                    changed += 1
        if changed:
            conn.commit()
            fixed += changed
        else:
            break
    conn.commit()
    return fixed, split


# ---------------------------------------------------------------- 应付款项（应付单 + 挂在单上的付款）
def ap_suppliers(conn) -> list[str]:
    """供应商候选：入库批次上出现过的、应付单上填过的，合起来去重。"""
    names: set[str] = set()
    for b in conn.rows(T_BATCH):
        name = str(b.get("supplier") or "").strip()
        if name:
            names.add(name)
    for r in conn.rows(T_AP):
        name = str(r.get("supplier") or "").strip()
        if name:
            names.add(name)
    return sorted(names)


def ap_candidates(conn) -> list[dict]:
    """入库批次 → 应付单草案（自动提取的唯一口径）。

    一次采购一张单：应付金额 = 批次的入栏金额（kg × 入栏均价），
    入库批次、供应商、供应商电话、入库日期全部取自批次档案；没有金额的批次不成单。
    """
    out: list[dict] = []
    for b in sorted(conn.rows(T_BATCH), key=lambda x: (str(x.get("entry_date") or ""),
                                                      int(x.get("id") or 0))):
        amount = r2(float(b.get("amount") or 0)
                    or float(b.get("weight") or 0) * float(b.get("price") or 0))
        if amount <= 0.005:
            continue
        code = str(b.get("code") or "")
        out.append({
            "date": str(b.get("entry_date") or today()),
            "batch_id": int(b.get("id") or 0),
            "batch_code": code,
            "supplier": str(b.get("supplier") or "").strip(),
            "phone": str(b.get("supplier_phone") or "").strip(),
            "item": AP_ITEM_DEFAULT,
            "amount": amount,
            "source": "采购入库",
            "ref": f"批次{code}",
            "link_key": f"batch:{int(b.get('id') or 0)}",
            # 备注别写太长：对账单「备注」列很窄，长句会顶出页面
            "remark": "按批次自动提取",
        })
    return out


def sync_ap_from_batches(conn) -> tuple[int, int, int]:
    """自动提取应付：缺的补上、批次改了供应商 / 金额 / 日期的跟着更新、批次没了就撤掉。

    幂等、可反复跑（进应付页、点「按入库批次重算」都会走这里）。

    两条安全边界跟应收一致：
        · 批次被删 / 金额改成 0，**还没付过钱**的应付单自动撤掉；
        · 已经登记过付款的应付单不自动删——怕把出纳登的钱一起冲掉，改由「数据校验」提示人工处理。
    返回（新增, 更新, 撤销）。
    """
    by_key = {str(r.get("link_key") or ""): r for r in conn.rows(T_AP)
              if str(r.get("link_key") or "")}
    cands = ap_candidates(conn)
    cand_keys = {str(c["link_key"]) for c in cands}
    paid_ids = {int(r.get("invoice_id") or 0) for r in conn.rows(T_APP)
                if int(r.get("invoice_id") or 0)}
    created = updated = cancelled = 0

    for cand in cands:
        old = by_key.get(cand["link_key"])
        if old is None:
            conn.insert(T_AP, cand)
            created += 1
            continue
        patch: dict = {}
        for key in ("date", "batch_code", "supplier", "phone", "amount", "ref", "batch_id"):
            if key in ("supplier", "phone") and not str(cand.get(key) or "").strip():
                continue        # 批次上没填的：别把人在应付单里补的供应商 / 电话抹掉
            if str(old.get(key) or "") != str(cand.get(key) or ""):
                patch[key] = cand[key]
        if not str(old.get("item") or "").strip() and cand["item"]:
            patch["item"] = cand["item"]
        if patch:
            conn.update(T_AP, int(old.get("id") or 0), patch)
            updated += 1

    # 来源批次没了（或金额归零）：没付过钱的自动撤掉；付过钱的留着，交校验页提示
    for key, old in by_key.items():
        if key in cand_keys:
            continue
        if int(old.get("id") or 0) in paid_ids:
            continue
        conn.delete(T_AP, int(old.get("id") or 0))
        cancelled += 1

    if created or updated or cancelled:
        conn.commit()
    return created, updated, cancelled


def save_ap_invoice(conn, data: dict, rid: int | None = None) -> dict:
    """存一张应付单：入库批次 / 入库日期在这里兜一遍底。

    界面上的「入库批次」是主字段：能对上批次就按批次的编号与采购入库日期，
    对不上（手工登记）就尊重手填的编号和日期。
    """
    payload = dict(data)
    payload["supplier"] = str(payload.get("supplier") or "").strip()
    payload["item"] = str(payload.get("item") or AP_ITEM_DEFAULT).strip()
    code = str(payload.get("batch_code") or "").strip()
    batch = None
    for b in conn.rows(T_BATCH):
        if str(b.get("code") or "") == code:
            batch = b
            break
    if batch is not None:
        payload["batch_id"] = int(batch.get("id") or 0)
        payload["batch_code"] = str(batch.get("code") or code)
        payload["date"] = str(payload.get("date") or batch.get("entry_date") or today())
    else:
        payload["batch_id"] = int(payload.get("batch_id") or 0)
        payload["date"] = str(payload.get("date") or today())
    row = conn.update(T_AP, int(rid), payload) if rid else conn.insert(T_AP, payload)
    conn.commit()
    return row or {}


def delete_ap_invoice(conn, rid: int) -> None:
    """删应付单：挂在这张单上的付款一起删，免得留下没人认领的付款记录。"""
    for r in [x for x in conn.rows(T_APP) if int(x.get("invoice_id") or 0) == int(rid)]:
        conn.delete(T_APP, int(r.get("id") or 0))
    conn.delete(T_AP, rid)
    conn.commit()


def save_ap_payment(conn, data: dict, rid: int | None = None) -> dict:
    payload = dict(data)
    payload["invoice_id"] = int(payload.get("invoice_id") or 0)
    row = conn.update(T_APP, int(rid), payload) if rid else conn.insert(T_APP, payload)
    conn.commit()
    return row or {}


def delete_ap_payment(conn, rid: int) -> None:
    conn.delete(T_APP, rid)
    conn.commit()


# ---------------------------------------------------------------- 门店盘点：按账面生成
def build_stocktake_rows(conn, store_id: int, day: str) -> list[dict]:
    """按当前账面库存生成盘点行（人只需在实盘列上调整）。"""
    out = []
    for row in calc.store_book_stock(conn, store_id, day):
        bid = 0
        for b in conn.rows(T_BATCH):
            if str(b.get("code") or "") == row.batch_code:
                bid = int(b.get("id") or 0)
                break
        out.append({
            "store_id": store_id,
            "date": day,
            "batch_id": bid,
            "location": "冷藏库",
            "product": row.product,
            "count": r1(row.count),
            "weight": r1(row.weight),
            "price": row.avg_price,
            "remark": "按账面库存生成",
        })
    return out


# ---------------------------------------------------------------- 档案初始化
def ensure_reference_data(conn) -> str:
    """首启补最小档案：默认门店「关一店」+ 商品档案。已存在则跳过。"""
    notes: list[str] = []
    if not conn.rows(T_STORE):
        conn.insert(T_STORE, {
            "code": "01", "name": DEFAULT_STORE_NAME, "short": DEFAULT_STORE_NAME,
            "contact": "", "phone": "", "address": "", "is_active": True,
            "remark": "直营门店",
        })
        notes.append(f"门店档案：{DEFAULT_STORE_NAME}")
    if not conn.rows(T_PRODUCT):
        for name, cat in DEFAULT_PRODUCTS:
            conn.insert(T_PRODUCT, {"name": name, "cat": cat, "spec": "", "is_active": True, "remark": ""})
        notes.append(f"商品档案：{len(DEFAULT_PRODUCTS)} 个")
    conn.commit()
    return "、".join(notes)


def all_categories(conn) -> list[str]:
    cats = {str(b.get("category")) for b in conn.rows(T_BATCH) if b.get("category")}
    return list(SHEEP_CATEGORIES) + sorted(cats - set(SHEEP_CATEGORIES))


# 示例账套的客户底表：名录里有这个人，应收的「结算方式」才带得出来、约定收款日才算得出来
DEMO_CUSTOMERS: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("屠宰场", "马老三", "马老三", "138****6621", "现结", "昭通市昭阳区太平路"),
    ("屠宰场", "昭通马老三", "马老三", "138****6621", "周结", "昭通市昭阳区太平路"),
    ("屠宰场", "昭通小串烧烤", "赵老板", "139****3308", "月结", "昭通市昭阳区团结路 12 号"),
    ("门店", "李记羊肉馆", "李老板", "137****9012", "半月结", "关岭县城关镇解放街"),
)


def ensure_customer_seed(conn) -> int:
    """给示例账套补几条客户底表（已有的名字跳过，不覆盖人工维护的资料）。"""
    existing = {str(c.get("name") or "").strip() for c in conn.rows(T_CUSTOMER)}
    made = 0
    for org, name, contact, phone, settle, address in DEMO_CUSTOMERS:
        if name in existing:
            continue
        conn.insert(T_CUSTOMER, {
            "org": org, "name": name, "contact": contact, "phone": phone,
            "settle": settle, "address": address, "credit_code": "", "first_date": "",
            "owner": "李伟", "remark": "示例数据", "is_active": True,
        })
        made += 1
    if made:
        conn.commit()
    return made
