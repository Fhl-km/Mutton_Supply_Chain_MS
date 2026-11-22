"""建账与示例数据。

首次打开（数据文件里一条台账都没有）自动建一套「能对上账」的示例：
2 个羊群批次 → 暂养出入库 → 养殖投料 → 5 张屠宰单 → 屠宰出库（含调拨门店）
→ 关一店入库 / 销售 / 盘点 → 应收款项（屠宰销售与门店销售各一套，含一笔到账）。
示例只用于跑通界面与勾稽，可在「系统设置」一键清空。
"""

from __future__ import annotations

from dataclasses import dataclass

from mscm.core import repo
from mscm.core.models import (
    AR_BIZ_SLAUGHTER, AR_BIZ_STORE,
    T_AP, T_APP, T_AR, T_ARR, T_BATCH, T_BREED, T_FEED, T_PRODUCT, T_STORE, T_SLAUGHTER, T_SOUT,
    T_SSALE, T_SSTOCK, T_SIN, T_YIELD, r1, r2, today,
)

D = "2026-11"


@dataclass
class SeedResult:
    seeded: bool = False
    message: str = ""


def _d(day: str) -> str:
    return f"{D}-{day:02d}"


def is_empty(conn) -> bool:
    return not any(conn.rows(t) for t in (T_BATCH, T_FEED, T_SLAUGHTER, T_SIN, T_SSALE))


def ensure_seed_data(conn) -> SeedResult:
    """首启建账：补档案；台账全空时灌一套示例。"""
    notes = [repo.ensure_reference_data(conn)]
    if is_empty(conn):
        seed_demo(conn)
        repo.ensure_batch_codes(conn)       # 批次编号＝采购入库日期
        repo.ensure_feed_inbound(conn)      # 每个批次都要有入库行
        repo.ensure_ar_links(conn)          # 应收补销售批次 / 结算方式 / 约定收款日
        repo.sync_ap_from_batches(conn)     # 每批采购都要有应付单
        return SeedResult(True, "已建立示例账套（2 个批次 / 5 张屠宰单 / 关一店台账）")
    # 老账套升级：批次编号改成日期式、补齐入库行、标好入/出库属性、应收补字段与收款挂单
    if repo.ensure_batch_codes(conn):
        notes.append("批次编号已改为采购日期格式")
    if repo.ensure_feed_inbound(conn):
        notes.append("已按批次补齐暂养入库行")
    fixed, split = repo.ensure_ar_links(conn)
    if fixed:
        notes.append(f"应收款项已补销售批次 / 结算方式 / 约定收款日（{fixed} 处）")
    if split:
        notes.append(f"跨单收款已拆分为 {split} 笔，逐笔挂到应收单上")
    ap_created, _ap_upd, _ap_cancel = repo.sync_ap_from_batches(conn)
    if ap_created:
        notes.append(f"应付款已按入库批次补 {ap_created} 张应付单")
    conn.set_setting("biz_date", conn.setting("biz_date", today()) or today())
    conn.commit()
    text = "、".join(x for x in notes if x)
    return SeedResult(False, text)


def clear_all(conn) -> None:
    conn.clear(T_BATCH, T_PRODUCT, T_STORE, T_FEED, T_BREED, T_SLAUGHTER,
               T_YIELD, T_SOUT, T_SIN, T_SSALE, T_SSTOCK, T_AR, T_ARR, T_AP, T_APP)
    conn.commit()
    repo.ensure_reference_data(conn)


def seed_demo(conn) -> None:
    """灌示例账套（先清台账，档案重建）。"""
    conn.clear(T_BATCH, T_FEED, T_BREED, T_SLAUGHTER, T_YIELD, T_SOUT,
               T_SIN, T_SSALE, T_SSTOCK, T_AR, T_ARR, T_AP, T_APP)
    conn.commit()
    repo.ensure_reference_data(conn)
    store = repo.list_stores(conn)[0]
    sid = int(store.get("id"))

    # ---------------- 批次 ----------------
    b1 = conn.insert(T_BATCH, {
        "code": "20261101", "category": "育肥羊", "pen": "A1", "supplier": "昭通鲁甸羊场",
        "supplier_phone": "138****1101",
        "tag": "A-001~120",
        "entry_date": _d(1), "count": 120, "weight": 4200.0, "price": 26.50,
        "amount": 111300.0, "status": "在养", "remark": "首批育肥羊，耳标 A-001~120",
    })
    b2 = conn.insert(T_BATCH, {
        "code": "20261108", "category": "山羊", "pen": "A2", "supplier": "会泽五星牧场",
        "supplier_phone": "139****2208",
        "tag": "B-001~080",
        "entry_date": _d(8), "count": 80, "weight": 3000.0, "price": 27.80,
        "amount": 83400.0, "status": "在养", "remark": "第二批山羊，耳标 B-001~080",
    })

    # ---------------- 暂养出入库 ----------------
    feeds = [
        # (日期, 批次, 入库只数, kg, 单价, 供应商, 标识, 出库用途, 出库只数, 出库kg)
        (_d(1), b1, 120, 4200.0, 26.50, "昭通鲁甸羊场", "A-001~120", "", 0, 0),
        (_d(5), b1, 0, 0, 0, "", "", "屠宰领用", 30, 1050.0),
        (_d(8), b2, 80, 3000.0, 27.80, "会泽五星牧场", "B-001~080", "", 0, 0),
        (_d(10), b1, 0, 0, 0, "", "", "屠宰领用", 30, 1030.0),
        (_d(12), b2, 0, 0, 0, "", "", "屠宰领用", 25, 940.0),
        (_d(15), b1, 0, 0, 0, "", "", "屠宰领用", 30, 1010.0),
        (_d(18), b2, 0, 0, 0, "", "", "屠宰领用", 25, 930.0),
    ]
    for day, b, in_c, in_w, price, sup, tag, use, out_c, out_w in feeds:
        conn.insert(T_FEED, {
            "date": day, "batch_id": int(b["id"]), "category": b["category"],
            "in_supplier": sup, "in_tag": tag,
            "in_count": in_c, "in_weight": in_w, "in_price": price,
            "out_use": use, "out_count": out_c, "out_weight": out_w, "remark": "",
        })

    # ---------------- 养殖记录 ----------------
    breeds = [
        (_d(1), b1, 0, "", "玉米", "kg", 800, 2.90, "杨志强"),
        (_d(5), b1, 30, "屠宰出栏", "羊草", "kg", 600, 1.20, "杨志强"),
        (_d(10), b1, 30, "屠宰出栏", "玉米", "kg", 700, 2.95, "杨志强"),
        (_d(15), b1, 30, "屠宰出栏", "羊草", "kg", 550, 1.25, "杨志强"),
        (_d(20), b1, 0, "", "玉米", "kg", 500, 2.95, "杨志强"),
        (_d(8), b2, 0, "", "羊草", "kg", 420, 1.30, "李国平"),
        (_d(12), b2, 25, "屠宰出栏", "玉米", "kg", 480, 2.95, "李国平"),
        (_d(18), b2, 25, "屠宰出栏", "羊草", "kg", 400, 1.25, "李国平"),
    ]
    for day, b, out_c, use, mat, unit, qty, price, who in breeds:
        conn.insert(T_BREED, {
            "date": day, "batch_id": int(b["id"]), "category": b["category"], "tag": "",
            "out_count": out_c, "out_use": use, "mat_name": mat, "mat_unit": unit,
            "mat_qty": qty, "mat_price": price, "recorder": who, "remark": "",
        })

    # ---------------- 屠宰单 ----------------
    docs = [
        # (日期, 批次, 只数, 毛重, 标识, 屠宰人, 产出[(商品, 只数, kg, 单价)])
        (_d(5), b1, 30, 1050.0, "A-001~030", "张志刚", [
            ("白条羊", 30, 400.0, 66.0), ("羊排", 30, 40.0, 74.0), ("羊腿", 30, 48.0, 70.0),
            ("羊蝎子", 30, 28.0, 44.0), ("羊杂", 30, 20.0, 28.0), ("羊皮", 30, 10.0, 10.0)]),
        (_d(10), b1, 30, 1030.0, "A-031~060", "张志刚", [
            ("白条羊", 30, 392.0, 66.0), ("羊排", 30, 39.0, 74.0), ("羊腿", 30, 47.0, 70.0),
            ("羊蝎子", 30, 27.0, 44.0), ("羊杂", 30, 19.0, 28.0), ("羊皮", 30, 10.0, 10.0)]),
        (_d(12), b2, 25, 940.0, "B-001~025", "张志刚", [
            ("白条羊", 25, 355.0, 68.0), ("羊排", 25, 36.0, 76.0), ("羊腿", 25, 42.0, 72.0),
            ("羊蝎子", 25, 25.0, 45.0), ("羊杂", 25, 17.0, 29.0), ("羊皮", 25, 9.0, 10.0)]),
        (_d(15), b1, 30, 1010.0, "A-061~090", "张志刚", [
            ("白条羊", 30, 385.0, 66.0), ("羊排", 30, 38.0, 74.0), ("羊腿", 30, 45.0, 70.0),
            ("羊蝎子", 30, 26.0, 44.0), ("羊杂", 30, 18.0, 28.0), ("羊皮", 30, 10.0, 10.0)]),
        (_d(18), b2, 25, 930.0, "B-026~050", "张志刚", [
            ("白条羊", 25, 350.0, 68.0), ("羊排", 25, 35.0, 76.0), ("羊腿", 25, 41.0, 72.0),
            ("羊蝎子", 25, 24.0, 45.0), ("羊杂", 25, 17.0, 29.0), ("羊皮", 25, 9.0, 10.0)]),
    ]
    for day, b, in_c, in_w, tag, who, lines in docs:
        doc = conn.insert(T_SLAUGHTER, {
            "doc_no": repo.next_doc_no(conn, day), "date": day, "batch_id": int(b["id"]),
            "category": b["category"], "in_count": in_c, "in_weight": in_w,
            "tag": tag, "operator": who, "remark": "",
        })
        for product, count, weight, price in lines:
            conn.insert(T_YIELD, {
                "slaughter_id": int(doc["id"]), "product": product, "count": count,
                "weight": weight, "price": price, "amount": r2(weight * price), "remark": "",
            })

    # ---------------- 屠宰出库（含调拨门店） ----------------
    sout = [
        # (日期, 批次, 去向, 门店, 商品, 只数, kg, 单价, 客户, 电话, 收款, 业务员)
        (_d(6), b1, "门店调拨", sid, "白条羊", 10, 133.0, 78.0, "", "", "", "李伟"),
        (_d(7), b1, "对外销售", 0, "羊排", 5, 20.0, 88.0, "马老三", "138****6621", "现款", "李伟"),
        (_d(11), b1, "门店调拨", sid, "白条羊", 10, 130.0, 78.0, "", "", "", "李伟"),
        (_d(11), b1, "门店调拨", sid, "羊腿", 6, 14.0, 86.0, "", "", "", "李伟"),
        (_d(11), b1, "对外销售", 0, "羊腿", 6, 14.0, 86.0, "昭通小串烧烤", "139****3308", "银行转账", "李伟"),
        (_d(13), b2, "门店调拨", sid, "白条羊", 8, 113.0, 80.0, "", "", "", "李伟"),
        (_d(16), b1, "门店调拨", sid, "白条羊", 10, 128.0, 78.0, "", "", "", "李伟"),
        (_d(19), b2, "门店调拨", sid, "白条羊", 8, 100.0, 80.0, "", "", "", "李伟"),
        (_d(20), b2, "对外销售", 0, "白条羊", 6, 76.0, 82.0, "昭通马老三", "138****6621", "挂账", "李伟"),
    ]
    for day, b, target, st, product, count, weight, price, cust, phone, pay, who in sout:
        conn.insert(T_SOUT, {
            "date": day, "batch_id": int(b["id"]), "target": target, "store_id": st,
            "product": product, "count": count, "weight": weight, "price": price,
            "customer": cust, "phone": phone, "pay_method": pay, "salesman": who, "remark": "",
        })
    conn.commit()
    # 调拨单 → 门店入库单（幂等）
    repo.sync_store_in_from_out(conn)

    # ---------------- 门店销售 ----------------
    sales = [
        (_d(6), b1, "零售", "白条羊", 3, 40.0, 96.0, 3840.0, 3840.0, "现款", "", ""),
        (_d(7), b1, "零售", "白条羊", 2, 27.0, 96.0, 2592.0, 2592.0, "微信", "", ""),
        (_d(11), b1, "零售", "白条羊", 3, 39.0, 98.0, 3822.0, 3822.0, "现款", "", ""),
        (_d(12), b1, "零售", "羊腿", 4, 6.0, 98.0, 588.0, 588.0, "现款", "", ""),
        (_d(13), b2, "零售", "白条羊", 2, 26.0, 98.0, 2548.0, 2548.0, "微信", "", ""),
        (_d(16), b1, "零售", "白条羊", 3, 38.0, 98.0, 3724.0, 3724.0, "现款", "", ""),
        (_d(19), b2, "批发", "白条羊", 3, 37.0, 100.0, 3700.0, 2000.0, "挂账", "李记羊肉馆", "137****9012"),
    ]
    for day, b, target, product, count, weight, price, due, paid, pay, cust, phone in sales:
        conn.insert(T_SSALE, {
            "date": day, "store_id": sid, "target": target, "batch_id": int(b["id"]),
            "product": product, "count": count, "weight": weight, "price": price,
            "due": due, "paid": paid, "pay_method": pay, "customer": cust, "phone": phone,
            "salesman": "王芳", "remark": "",
        })

    # ---------------- 门店盘点（按账面生成，羊腿留 0.6kg 差异演示校验） ----------------
    for row in repo.build_stocktake_rows(conn, sid, _d(20)):
        if row["product"] == "羊腿":
            row["weight"] = r1(float(row["weight"]) - 0.6)
            row["remark"] = "按账面生成，实盘短少 0.6kg"
        conn.insert(T_SSTOCK, row)

    # ---------------- 应收款项（按销售挂账自动提取 + 出纳照银行流水分笔登记收款） ----------------
    repo.ensure_customer_seed(conn)
    repo.seed_ar_from_sales(conn, AR_BIZ_SLAUGHTER)
    repo.seed_ar_from_sales(conn, AR_BIZ_STORE, sid)

    def _demo_inv(biz: str, cust: str, st: int = 0) -> dict | None:
        for r in conn.rows(T_AR):
            if (str(r.get("biz") or "") == biz and str(r.get("customer") or "") == cust
                    and (not st or int(r.get("store_id") or 0) == int(st))):
                return r
        return None

    # 同一张应收单分两次到账（演示「一对多」：一笔款拆成几笔记）
    for biz, st, cust, day, amount, pay in (
        (AR_BIZ_SLAUGHTER, 0, "昭通马老三", _d(18), 600.0, "银行转账"),
        (AR_BIZ_SLAUGHTER, 0, "昭通马老三", _d(20), 400.0, "银行转账"),
        (AR_BIZ_STORE, sid, "李记羊肉馆", _d(20), 1000.0, "微信"),
    ):
        inv = _demo_inv(biz, cust, st)
        if inv is None:
            continue
        conn.insert(T_ARR, {
            "biz": biz, "store_id": st, "invoice_id": int(inv.get("id") or 0),
            "date": day, "customer": cust, "amount": amount, "pay_method": pay,
            "ref": "", "remark": "示例数据：照银行流水登记",
        })

    # ---------------- 应付款项（按入库批次自动提取 + 出纳照银行流水分笔付款） ----------------
    repo.sync_ap_from_batches(conn)

    def _demo_ap(batch) -> dict | None:
        key = f"batch:{int(batch.get('id') or 0)}"
        for r in conn.rows(T_AP):
            if str(r.get("link_key") or "") == key:
                return r
        return None

    # 第一批 111,300 分两次付 90,000，还欠 21,300（演示「一对多」与未付余额）；
    # 第二批 83,400 一分没付（演示账龄与采购对账单）
    for batch, day, amount, pay in ((b1, _d(3), 60000.0, "银行转账"),
                                    (b1, _d(15), 30000.0, "银行转账")):
        inv = _demo_ap(batch)
        if inv is None:
            continue
        conn.insert(T_APP, {
            "invoice_id": int(inv.get("id") or 0),
            "date": day, "supplier": str(inv.get("supplier") or ""),
            "amount": amount, "pay_method": pay,
            "ref": "", "remark": "示例数据：照银行流水登记",
        })

    conn.set_setting("biz_date", _d(20))
    conn.commit()
