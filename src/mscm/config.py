"""全局配置：路径、常量、数值格式。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "羊供应链管理系统"
APP_SUBTITLE = "活羊采购 · 屠宰 · 门店 一体化台账"
APP_VERSION = "1.6.0"
COMPANY = "富民锐泽农业科技有限公司"

# 自动更新：版本信息文件地址。文件内容一行三段：版本号 安装包直链 [sha256]。
# 留空时不检查更新（不会联网、不弹任何提示）；发布时填真实网址即可。
UPDATE_CHECK_URL = "https://fhlwebsite.pages.dev/Mutton_Supply_Chain_MS_check_update.txt"

# 数据文件扩展名：mscm = Mutton Supply Chain Management
DATA_SUFFIX = ".mscm.json"


def _frozen() -> bool:
    """是否跑在打包产物里。

    Nuitka 会在编译后的模块里放 ``__compiled__``；``sys.frozen`` 是 PyInstaller
    的口径，Nuitka 不一定设。两个都认，免得打包后 ROOT 算到临时目录去，
    账套文件就找不到 / 存到奇怪的地方。
    """
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def _project_root() -> Path:
    if _frozen():                              # PyInstaller / Nuitka 打包后
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
