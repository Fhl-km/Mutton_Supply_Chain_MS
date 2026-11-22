"""应用装配：数据文件、样式、主窗口。"""

from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from mscm import config
from mscm.core.bootstrap import ensure_seed_data
from mscm.core.db import open_database
from mscm.ui import theme, update_ui
from mscm.ui.main_window import MainWindow


def _log(message: str) -> None:
    """启动日志。

    打包成窗口程序（无控制台）后 ``sys.stdout`` 可能是 None，直接 print 会
    抛 AttributeError 把程序带崩在启动阶段，所以这里一律吞掉写失败。
    """
    try:
        if sys.stdout is not None:
            print(f"[init] {message}", flush=True)
    except (OSError, ValueError):
        pass


def _backup_before_upgrade(conn) -> str:
    """版本变了（刚装新版 / 刚自动更新）就先留一份快照，写坏了好回退。

    只在「账套里记着的版本」与「当前 exe 版本」不一致、且已有数据文件时才做。
    备份失败不挡启动 —— 它是兜底，不是必经流程。

    返回一句给状态栏看的话（没什么可说的就返回空串）。
    """
    prev = str(conn.data.get("app_version") or "").strip()
    if not prev or prev == config.APP_VERSION:
        return ""
    try:
        target = conn.backup("upgrade", keep=5)
    except Exception as exc:  # noqa: BLE001 - 备份失败不能影响开账
        _log(f"升级前备份失败（不影响使用）：{exc}")
        return ""
    if not target:
        return ""
    # 立刻把新版本号落盘（原子写）：否则用户这次启动什么都没改，下回启动又会备份一遍
    try:
        conn.data["app_version"] = config.APP_VERSION
        conn.touch()
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        _log(f"写入版本标记失败（不影响使用）：{exc}")
    _log(f"版本 {prev} → {config.APP_VERSION}，账套已备份：{target.name}")
    return f"已升级到 v{config.APP_VERSION}，升级前账套已备份到 data\\backup\\{target.name}"


def run(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    config.ensure_dirs()

    app = QApplication(argv)
    app.setApplicationName(config.APP_NAME)
    app.setApplicationVersion(config.APP_VERSION)
    app.setOrganizationName(config.COMPANY)

    theme.apply_theme(app)

    conn = open_database()
    upgrade_note = _backup_before_upgrade(conn)
    result = ensure_seed_data(conn)
    if result.message:
        _log(result.message)

    win = MainWindow(conn)
    win.showMaximized()
    if result.seeded:
        win.statusBar().showMessage(f"首次建账：{result.message}", 15000)
    elif upgrade_note:
        win.statusBar().showMessage(upgrade_note, 15000)
    else:
        win.statusBar().showMessage("就绪", 3000)

    # 启动自动检查：延迟 1.5 秒避开建账 / 恢复提示；失败或已是最新都静默。
    QTimer.singleShot(1500, lambda: update_ui.start_auto_check(win, conn))

    code = app.exec()
    conn.close()
    return code
