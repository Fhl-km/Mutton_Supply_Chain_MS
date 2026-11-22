"""应用装配：数据文件、样式、主窗口。"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from mscm import config
from mscm.core.bootstrap import ensure_seed_data
from mscm.core.db import open_database
from mscm.ui import theme
from mscm.ui.main_window import MainWindow


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
        print(f"[init] {result.message}")

    win = MainWindow(conn)
    win.showMaximized()
    if result.seeded:
        win.statusBar().showMessage(f"首次建账：{result.message}", 15000)
    else:
        win.statusBar().showMessage("就绪", 3000)

    code = app.exec()
    conn.close()
    return code
