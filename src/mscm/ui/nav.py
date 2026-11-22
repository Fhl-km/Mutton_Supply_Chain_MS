"""侧边导航：品牌区、分组、门店节点、页脚。

层级（与用户口径一致）::

    经营分析     概览 / 数据校验
    档案         商品档案 / 门店档案 / 客户名录
    活羊采购 & 屠宰   活羊入库&结余 / 暂养出入库台账 / 养殖记录 / 屠宰记录 / 屠宰出库明细 /
                     应收款项·屠宰销售 / 应付款项·活羊采购与付款
    门店管理     关一店 → 损益报表 / 进销存台账 / 入库台账 / 销售台账 /
                 结存/盘点台账 / 应收款项
                 （门店节点由「门店档案」驱动，加一家店就多一个节点）

展开/收起用回调而不是信号，省掉主窗口里再套一层 connect。
门店之间是手风琴：展开一家自动收起其它。
"""

from __future__ import annotations

from typing import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mscm import config


def btn_text(text: str) -> str:
    """按钮文字里的「&」是助记符，要显示成字面的 & 必须写成 &&（否则那个字会被吞掉）。"""
    return str(text).replace("&", "&&")


class NavBrand(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 18, 16, 14)
        lay.setSpacing(10)

        mark = QLabel("羊")
        mark.setObjectName("BrandMark")
        mark.setFixedWidth(30)

        text = QVBoxLayout()
        text.setSpacing(1)
        title = QLabel("羊供应链管理")
        title.setObjectName("BrandTitle")
        sub = QLabel("采购 · 屠宰 · 门店台账")
        sub.setObjectName("BrandSub")
        text.addWidget(title)
        text.addWidget(sub)

        lay.addWidget(mark)
        lay.addLayout(text)
        lay.addStretch(1)


class NavRootButton(QPushButton):
    """一级入口 / 分组标题。"""

    def __init__(self, text: str, parent: QWidget | None = None,
                 name: str = "NavRoot") -> None:
        super().__init__(btn_text(text), parent)
        self.setObjectName(name)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


class NavSubButton(QPushButton):
    """组内页 / 门店下的台账。"""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(btn_text(text), parent)
        self.setObjectName("NavSub")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


class NavLeafButton(QPushButton):
    """一级直达页（概览 / 数据校验 / 档案）：可选中，选中态=深蓝底+金边。"""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(btn_text(text), parent)
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


class NavSection(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("NavSection")


class NavGroupItem(QWidget):
    """可展开节点：一行标题 + 若干子页（或子块）。"""

    def __init__(self, heading: str, items: Sequence[tuple[str, str]],
                 on_pick: Callable[[str], None],
                 on_toggle: Callable[["NavGroupItem"], None] | None = None,
                 tip: str = "", header_name: str = "NavRoot",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.heading = heading
        self.buttons: dict[str, NavSubButton] = {}
        self._open = False
        self._on_toggle = on_toggle

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.header = QPushButton(f"▸  {btn_text(heading)}")
        self.header.setObjectName(header_name)
        self.header.setCursor(Qt.PointingHandCursor)
        if tip:
            self.header.setToolTip(tip)
        self.header.clicked.connect(self.toggle)
        lay.addWidget(self.header)

        self.body = QWidget()
        body_lay = QVBoxLayout(self.body)
        body_lay.setContentsMargins(0, 0, 0, 2)
        body_lay.setSpacing(0)
        for key, title in items:
            btn = NavSubButton(title)
            btn.clicked.connect(lambda _=False, k=key: on_pick(k))
            body_lay.addWidget(btn)
            self.buttons[key] = btn
        lay.addWidget(self.body)

        self.set_open(False)

    @property
    def opened(self) -> bool:
        return self._open

    def set_open(self, opened: bool) -> None:
        self._open = opened
        self.body.setVisible(opened)
        self.header.setText(("▾  " if opened else "▸  ") + btn_text(self.heading))

    def toggle(self) -> None:
        if self._on_toggle is not None:
            self._on_toggle(self)
        else:
            self.set_open(not self._open)

    def add_body_widget(self, widget: QWidget) -> None:
        lay = self.body.layout()
        if lay is not None:
            lay.addWidget(widget)

    def set_current(self, on: bool) -> None:
        """当前页属于本组时标题标金（组收起时这是唯一的位置提示）。"""
        self.header.setProperty("cur", "1" if on else "0")
        self.header.style().unpolish(self.header)
        self.header.style().polish(self.header)

    def uncheck_all(self) -> None:
        for btn in self.buttons.values():
            btn.setChecked(False)


class NavStoreItem(NavGroupItem):
    """门店节点：一行店名 + 损益 / 进销存 / 三张台账 / 应收款项。"""

    def __init__(self, store_id: int, heading: str,
                 reports: Sequence[tuple[str, str]],
                 on_pick: Callable[[int, str], None],
                 on_toggle: Callable[["NavStoreItem"], None] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(
            heading, reports,
            on_pick=lambda kind: on_pick(self.store_id, kind),
            on_toggle=on_toggle,
            tip=f"{heading}：损益报表 / 进销存台账 / 入库台账 / 销售台账 / 结存/盘点台账 / 应收款项",
            header_name="NavStore", parent=parent)
        self.store_id = int(store_id)


class NavFooter(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SidebarFooter")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 10, 16, 12)
        lay.setSpacing(2)
        company = QLabel(config.COMPANY)
        company.setObjectName("SidebarHint")
        company.setWordWrap(True)
        version = QLabel(f"v{config.APP_VERSION} · 本地账套")
        version.setObjectName("SidebarHint")
        lay.addWidget(company)
        lay.addWidget(version)
