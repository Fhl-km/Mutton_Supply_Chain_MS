"""数据文件（.mscm.json）读写：纯 JSON 存储，运行时不依赖数据库引擎。

文件结构（UTF-8 JSON，缩进 1 格便于人读与版本比对）::

    {
      "format": "mscm", "schema": 1, "app": "…", "saved_at": "…",
      "seq": {"batch": 2, "product": 10, "store": 1, "feed": 0, …},
      "batch":   [{id, code, category, pen, supplier, entry_date, count, weight, price, amount, status, remark}],
      "product": [{id, name, cat, spec, is_active, remark}],
      "store":   [{id, code, name, short, contact, phone, address, is_active}],
      "feed":    [{id, date, batch_id, category, in_supplier, in_tag, in_count, in_weight, in_price,
                   out_use, out_count, out_weight, remark}],
      "breeding":[{id, date, batch_id, category, tag, out_count, out_use, mat_name, mat_unit,
                   mat_qty, mat_price, recorder, remark}],
      "slaughter":[{id, doc_no, date, batch_id, category, in_count, in_weight, tag, operator, remark}],
      "yield_line":[{id, slaughter_id, product, count, weight, price, remark}],
      "slaughter_out":[{id, date, batch_id, target, store_id, product, count, weight, price,
                        customer, phone, pay_method, salesman, remark}],
      "store_in":[{id, store_id, date, source, batch_id, product, count, weight, price, remark, link_id}],
      "store_sale":[{id, store_id, date, target, batch_id, product, count, weight, price,
                     due, paid, pay_method, customer, phone, salesman, remark}],
      "store_stock":[{id, store_id, date, batch_id, location, product, count, weight, price, remark}],
      "ar_invoice":[{id, biz, store_id, date, sale_batch, customer, phone, summary, amount,
                     settle, due_date, salesman, source, ref, link_key, remark}],
      "ar_receipt":[{id, biz, store_id, invoice_id, date, customer, amount, waiver,
                     pay_method, ref, remark}],
      "ap_invoice":[{id, date, batch_id, batch_code, supplier, phone, item, amount,
                     source, ref, link_key, remark}],
      "ap_payment":[{id, invoice_id, date, supplier, amount, pay_method, ref, remark}],
      "customer":[{id, org, name, credit_code, contact, phone, address, settle,
                   first_date, owner, remark}],
      "setting": {"key": "value"}
    }

派生字段（金额、结存、出肉率、账面库存）一律不进库，由 core/calc.py 现算，
避免「存了一份、算了一份」两套数打架。

写入策略：commit() 即整份快照落盘（先写 .tmp 再 os.replace，保证不写坏原文件）。
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from mscm import config
from mscm.core.models import TABLES

FORMAT = "mscm"
SCHEMA_VERSION = 1


def _blank() -> dict[str, Any]:
    data: dict[str, Any] = {
        "format": FORMAT,
        "schema": SCHEMA_VERSION,
        "app": config.APP_NAME,
        "app_version": config.APP_VERSION,
        "saved_at": "",
        "seq": {k: 0 for k in TABLES},
        "setting": {},
    }
    for k in TABLES:
        data[k] = []
    return data


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class JsonStore:
    """内存字典 + 整份 JSON 落盘。对外按「表」的粒度提供增删改查。"""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else config.DATA_PATH
        self._data: dict[str, Any] = _blank()
        self._dirty = False
        self.load()

    # ------------------------------------------------------------ 载入 / 落盘
    def load(self) -> None:
        if not self.path.exists():
            self._data = _blank()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:      # 文件损坏：留证据、起新账
            self._data = _blank()
            bad = self.path.with_suffix(self.path.suffix + ".broken")
            try:
                shutil.copy2(self.path, bad)
            except OSError:
                pass
            print(f"[db] 数据文件读取失败（{exc}），已另存为 {bad.name} 并重新起账")
            return

        base = _blank()
        base.update({k: v for k, v in raw.items() if k in base or k in TABLES})
        for k in TABLES:                                    # 表必须是 list
            if not isinstance(base.get(k), list):
                base[k] = []
        seq = raw.get("seq") if isinstance(raw.get("seq"), dict) else {}
        for k in TABLES:
            base["seq"][k] = int(seq.get(k) or 0)
        if not isinstance(base.get("setting"), dict):
            base["setting"] = {}
        self._data = base
        self._dirty = False

    def commit(self) -> None:
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data["saved_at"] = _now()
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = json.dumps(self._data, ensure_ascii=False, indent=1)
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.path)                          # 原子替换：绝不先删后写
        self._dirty = False

    def close(self) -> None:
        self.commit()

    # ------------------------------------------------------------ 表访问
    @property
    def data(self) -> dict[str, Any]:
        return self._data

    def rows(self, table: str) -> list[dict]:
        if table not in TABLES:
            raise KeyError(f"未知数据表：{table}")
        return self._data[table]

    def get(self, table: str, oid: int | str | None) -> dict | None:
        try:
            oid = int(oid or 0)
        except (TypeError, ValueError):
            return None
        for row in self.rows(table):
            if int(row.get("id") or 0) == oid:
                return row
        return None

    def insert(self, table: str, row: dict) -> dict:
        if table not in TABLES:
            raise KeyError(f"未知数据表：{table}")
        seq = int(self._data["seq"].get(table) or 0) + 1
        self._data["seq"][table] = seq
        row = dict(row)
        row["id"] = seq
        row.setdefault("created_at", _now())
        row["updated_at"] = _now()
        self._data[table].append(row)
        self._dirty = True
        return row

    def update(self, table: str, oid: int, patch: dict) -> dict | None:
        row = self.get(table, oid)
        if row is None:
            return None
        row.update(patch)
        row["updated_at"] = _now()
        self._dirty = True
        return row

    def delete(self, table: str, oid: int) -> bool:
        rows = self.rows(table)
        for i, row in enumerate(rows):
            if int(row.get("id") or 0) == int(oid or 0):
                rows.pop(i)
                self._dirty = True
                return True
        return False

    def touch(self) -> None:
        """就地批量改过字段后打脏标记，下一次 commit() 统一落盘。"""
        self._dirty = True

    def bulk_insert(self, table: str, items: Iterable[dict]) -> int:
        n = 0
        for item in items:
            self.insert(table, item)
            n += 1
        return n

    def clear(self, *tables: str) -> None:
        for t in tables:
            if t in TABLES:
                self._data[t] = []
                self._data["seq"][t] = 0
        self._dirty = True

    # ------------------------------------------------------------ 设置
    def setting(self, key: str, default: str = "") -> str:
        val = self._data["setting"].get(key)
        return default if val is None else str(val)

    def set_setting(self, key: str, value: Any) -> None:
        self._data["setting"][key] = "" if value is None else str(value)
        self._dirty = True

    # ------------------------------------------------------------ 备份
    def backup(self, tag: str = "auto", keep: int = 5) -> Path | None:
        """整份快照备份到 data/backup，只保留最近 keep 份。"""
        if not self.path.exists():
            return None
        config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = config.BACKUP_DIR / f"mscm_{tag}_{stamp}.json"
        shutil.copy2(self.path, target)
        olds = sorted(config.BACKUP_DIR.glob(f"mscm_{tag}_*.json"))
        for old in olds[:-keep] if len(olds) > keep else []:
            try:
                old.unlink()
            except OSError:
                pass
        return target

    # ------------------------------------------------------------ 统计
    def stats(self) -> dict[str, int]:
        return {k: len(self._data[k]) for k in TABLES}


def open_database(path: Path | str | None = None) -> JsonStore:
    config.ensure_dirs()
    return JsonStore(path)
