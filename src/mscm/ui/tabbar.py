"""页面标签栏：WPS / Excel 多页签风格，可切换、可关闭。

标签的 key 存在 tabData 里（QTabBar 原生支持），不另建映射表，
省得页签增删时两处状态对不上。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTabBar

MAX_TAB_CHARS = 14


def _esc(text: str) -> str:
    """页签文字里的「&」是助记符（会被吞掉），要显示成字面的 & 得写成 &&。"""
    return str(text).replace("&", "&&")


def _clip(text: str) -> str:
    return text if len(text) <= MAX_TAB_CHARS else text[: MAX_TAB_CHARS - 1] + "…"


class PageTabBar(QTabBar):
    pageActivated = Signal(str)
    closePageRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("PageTabs")
        self.setExpanding(False)
        self.setMovable(True)
        self.setTabsClosable(True)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.ElideRight)
        self.currentChanged.connect(self._on_current)
        self.tabCloseRequested.connect(self._on_close)

    # ---------------------------------------------------------- 读写
    def add_page(self, key: str, text: str, closable: bool = True) -> int:
        idx = self.addTab(_esc(_clip(text)))
        self.setTabData(idx, key)
        if not closable:
            self.setTabButton(idx, QTabBar.RightSide, None)
        return idx

    def find_key(self, key: str) -> int:
        for i in range(self.count()):
            if self.tabData(i) == key:
                return i
        return -1

    def key_at(self, index: int) -> str:
        data = self.tabData(index)
        return str(data) if data is not None else ""

    def select_page(self, key: str) -> None:
        idx = self.find_key(key)
        if idx >= 0 and idx != self.currentIndex():
            self.blockSignals(False)
            self.setCurrentIndex(idx)

    def set_page_text(self, index: int, text: str, tip: str = "") -> None:
        if 0 <= index < self.count():
            self.setTabText(index, _esc(_clip(text)))
            self.setTabToolTip(index, (tip or text).replace("&&", "&"))

    def remove_page(self, index: int) -> None:
        if 0 <= index < self.count():
            self.blockSignals(True)
            self.removeTab(index)
            self.blockSignals(False)

    # ---------------------------------------------------------- 事件
    def _on_current(self, index: int) -> None:
        if index >= 0:
            self.pageActivated.emit(self.key_at(index))

    def _on_close(self, index: int) -> None:
        key = self.key_at(index)
        if key:
            self.closePageRequested.emit(key)
