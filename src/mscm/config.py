"""全局配置：路径、常量、数值格式。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "羊供应链管理系统"
APP_SUBTITLE = "活羊采购 · 屠宰 · 门店 一体化台账"
APP_VERSION = "1.6.0"
COMPANY = "富民锐泽农业科技有限公司"

# 数据文件扩展名：mscm = Mutton Supply Chain Management
DATA_SUFFIX = ".mscm.json"


def _project_root() -> Path:
    if getattr(sys, "frozen", False):          # PyInstaller / Nuitka 打包后
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


ROOT = _project_root()
DATA_DIR = Path(os.environ.get("MSCM_DATA_DIR", ROOT / "data"))
EXPORT_DIR = ROOT / "导出报表"
BACKUP_DIR = DATA_DIR / "backup"
DATA_PATH = DATA_DIR / f"mscm{DATA_SUFFIX}"

# 账表模板（同目录下用户提供的空账表，仅作口径参照，程序不写它）
TEMPLATE_NAME = "账表记录-羊.xlsx"

# 数值格式：kg 精确 0.1、金额 2 位、单价 2 位、百分比 2 位
QTY_FMT = "#,##0.0"
MONEY_FMT = "#,##0.00"
PRICE_FMT = "#,##0.00"
INT_FMT = "#,##0"
PCT_FMT = "0.00%"


def ensure_dirs() -> None:
    for p in (DATA_DIR, EXPORT_DIR, BACKUP_DIR):
        p.mkdir(parents=True, exist_ok=True)


def template_workbook() -> Path | None:
    """用户提供的空账表模板（存在则返回路径）。"""
    p = ROOT / TEMPLATE_NAME
    return p if p.exists() else None
