"""核心逻辑冒烟测试（无界面）：建账、勾稽、出表。

用法：.venv/Scripts/python.exe scripts/smoke_core.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TMP = Path(tempfile.mkdtemp(prefix="mscm_smoke_"))
os.environ["MSCM_DATA_DIR"] = str(TMP / "data")

from mscm.core import bootstrap, calc  # noqa: E402
from mscm.core.db import open_database  # noqa: E402
from mscm.core.services import export  # noqa: E402

conn = open_database(TMP / "data" / "test.mscm.json")
res = bootstrap.ensure_seed_data(conn)
print("[seed]", res.seeded, res.message)
print("[stats]", conn.stats())

balances = calc.batch_balances(conn)
for b in balances:
    print(f"[batch] {b.batch_code} {b.category} 结存 {b.count:.1f} 只 / {b.weight:.1f} kg / "
          f"{b.amount:,.2f} 元 @ {b.avg_price:.2f}")

docs = calc.slaughter_docs(conn)
for d in docs:
    print(f"[slaughter] {d['doc_no']} 领入 {d['in_count']} 只 {d['in_weight']:.1f}kg → "
          f"产出 {d['_out_weight']:.1f}kg 出肉率 {d['_yield_rate'] * 100:.1f}% "
          f"成本 {d['_in_cost']:,.2f} 产值 {d['_out_amount']:,.2f}")

print("[store stock]")
for r in calc.store_book_stock(conn):
    print(f"  {r.store_name} {r.batch_code} {r.product}: {r.count:.1f} 只 / {r.weight:.1f} kg / "
          f"{r.amount:,.2f} 元")

print("[checks]")
for c in calc.checks(conn):
    print(f"  [{c.label}] {c.item} | 应有 {c.expect} 实有 {c.actual}")

out = export.export_workbook(TMP / "整套台账.xlsx", conn, "2026-11-01", "2026-11-30", 
                             store_id=int(conn.rows("store")[0]["id"]))
print("[export]", out, out.stat().st_size, "bytes")
print("[stats d20]", calc.dashboard_stats(conn, "2026-11-20"))
conn.close()
print("OK", TMP)
