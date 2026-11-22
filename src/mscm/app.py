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


def run(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    config.ensure_dirs()

    app = QApplication(argv)
    app.setApplicationName(config.APP_NAME)
    app.setApplicationVersion(config.APP_VERSION)
    app.setOrganizationName(config.COMPANY)

    theme.apply_theme(app)

    conn = open_database()
    result = ensure_seed_data(conn)
    if result.message:
        _log(result.message)

    win = MainWindow(conn)
    win.showMaximized()
    if result.seeded:
        win.statusBar().showMessage(f"首次建账：{result.message}", 15000)
    else:
        win.statusBar().showMessage("就绪", 3000)

    # 启动自动检查：延迟 1.5 秒避开建账 / 恢复提示；失败或已是最新都静默。
    QTimer.singleShot(1500, lambda: update_ui.start_auto_check(win, conn))

    code = app.exec()
    conn.close()
    return code
