"""页面上下文：数据文件句柄、业务日期、跨页刷新与提示。"""

from __future__ import annotations

from typing import Callable, Protocol

from PySide6.QtCore import QObject, Signal

from mscm.core import repo
from mscm.core.db import JsonStore
from mscm.core.models import norm_date


class Notifier(Protocol):
    def notify(self, message: str, level: str = "info") -> None: ...

    def refresh_all(self) -> None: ...


class AppContext(QObject):
    """页面共享的运行时上下文。"""

    data_changed = Signal()
    biz_date_changed = Signal(str)

    def __init__(self, conn: JsonStore, biz_date: str, host: Notifier | None = None) -> None:
        super().__init__()
        self.conn = conn
        self._biz_date = norm_date(biz_date)
        self.host = host

    # ---------------------------------------------------------- 业务日期
    @property
    def biz_date(self) -> str:
        return self._biz_date

    def set_biz_date(self, day: str) -> None:
        day = norm_date(day)
        if day == self._biz_date:
            return
        self._biz_date = day
        repo.set_setting(self.conn, "biz_date", day)
        self.biz_date_changed.emit(day)

    # ---------------------------------------------------------- 提示与刷新
    def notify(self, message: str, level: str = "info") -> None:
        if self.host is not None:
            self.host.notify(message, level)

    def changed(self) -> None:
        """数据变更后先落盘，再广播刷新。"""
        self.conn.commit()
        self.data_changed.emit()
        if self.host is not None:
            self.host.refresh_all()

    def on_change(self, fn: Callable[[], None]) -> None:
        self.data_changed.connect(fn)

    # ---------------------------------------------------------- 下拉数据源
    def store_options(self) -> list[tuple[str, int]]:
        return [(str(s.get("name")), int(s.get("id") or 0))
                for s in repo.list_stores(self.conn)]

    def batch_options(self, include_blank: bool = False) -> list[tuple[str, int]]:
        return repo.batch_options(self.conn, include_blank)

    def product_names(self) -> list[str]:
        return repo.product_names(self.conn)
