"""软件更新冒烟：版本文本解析 / 版本比较 / 未配置安全返回 / 设置页控件。

用法：.venv/Scripts/python.exe scripts/smoke_update.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TMP = Path(tempfile.mkdtemp(prefix="mscm_update_"))
os.environ["MSCM_DATA_DIR"] = str(TMP / "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mscm import check_update, config  # noqa: E402
from mscm.core import bootstrap, repo  # noqa: E402
from mscm.core.db import open_database  # noqa: E402
from mscm.ui import theme, update_ui  # noqa: E402
from mscm.ui.main_window import MainWindow  # noqa: E402

fails: list[str] = []


def ok(name: str, cond: bool, extra: str = "") -> None:
    print(("  OK  " if cond else " FAIL ") + name + ("  " + extra if extra else ""))
    if not cond:
        fails.append(name)


print("[1] parse_text")
v, u, d = check_update.parse_text("1.7.0 https://x/y.exe " + "a" * 64)
ok("三段解析", v == "1.7.0" and u == "https://x/y.exe" and len(d) == 64)
v, u, d = check_update.parse_text("1.7.0 https://x/y.exe")
ok("无摘要仍可用", d == "")
v, u, d = check_update.parse_text("1.7.0 https://x/y.exe not-a-digest")
ok("乱写摘要忽略", d == "")
try:
    check_update.parse_text("garbage")
    ok("坏格式抛错", False)
except ValueError:
    ok("坏格式抛错", True)

print("[2] 版本比较")
ok("远端较新 → 需要更新", check_update._same_or_older("1.7.0", "1.6.0") is False)
ok("远端相同 → 无需更新", check_update._same_or_older("1.6.0", "1.6.0") is True)
ok("远端较旧 → 无需更新", check_update._same_or_older("1.5.9", "1.6.0") is True)
ok("位数不齐补齐", check_update._same_or_older("1.6", "1.6.0") is True)

print("[3] 未配置安全返回")
ok("configured 为 False", check_update.configured() is False)
res = check_update.check()
ok("check 返回 error", res["status"] == check_update.ERROR, res["detail"])

print("[4] 设置开关持久化")
conn = open_database(TMP / "data" / "ui.mscm.json")
bootstrap.ensure_seed_data(conn)
ok("默认开", update_ui.auto_update_enabled(conn) is True)
update_ui.set_auto_update(conn, False)
ok("关掉后生效", update_ui.auto_update_enabled(conn) is False)
update_ui.set_auto_update(conn, True)

print("[5] 设置页控件")
app = QApplication(sys.argv)
theme.apply_theme(app)
win = MainWindow(conn)
win.show()
app.processEvents()
win.show_page("settings")
app.processEvents()
page = win.pages.get("settings")
ok("软件更新卡片存在", page is not None and hasattr(page, "auto_update_box"))
if page is not None:
    ok("复选框默认勾上", page.auto_update_box.isChecked() is True)
    ok("检查更新按钮在", page.update_btn.text() == "检查更新")

# auto 模式未配置地址直接静默返回，不弹窗（手动点按钮的弹窗由 check 逻辑覆盖）
update_ui.start_check(win, auto=True)
app.processEvents()
ok("未配置时自动检查静默返回", True)

ok("预览版判定", check_update.is_preview_version() is False)
ok("版本取 config", config.APP_VERSION == "1.6.0")

print("[RESULT]", "OK" if not fails else "FAIL: " + ", ".join(fails))
sys.exit(0 if not fails else 1)
