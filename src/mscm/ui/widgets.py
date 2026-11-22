"""通用界面组件：卡片、指标卡、数据表、筛选控件与格式化工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from PySide6.QtCore import QDate, QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCalendarWidget,
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mscm.ui import theme


# ------------------------------------------------------------------ 格式化
def num(v: float | None, digits: int = 1) -> str:
    if v is None:
        return "—"
    return f"{v:,.{digits}f}"


def money(v: float | None, digits: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:,.{digits}f}"


def pct(v: float | None, digits: int = 1) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.{digits}f}%"


def signed(v: float | None, digits: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:+,.{digits}f}"


def blank(v) -> str:
    """空值显示为「—」，免得表格里一片空白分不清"没有"和"零"。"""
    text = "" if v is None else str(v).strip()
    return text or "—"


# ------------------------------------------------------------------ 卡片
class Card(QFrame):
    """白底圆角卡片：标题 + 说明 + 右侧操作区 + 内容区。"""

    def __init__(self, title: str = "", hint: str = "", parent: QWidget | None = None,
                 padding: int = 14, spacing: int = 8) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(padding, padding, padding, padding)
        self._lay.setSpacing(spacing)

        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("CardHint")
        self.header.addWidget(self.title_label)
        self.header.addWidget(self.hint_label)
        self.header.addStretch(1)
        if title:
            self._lay.addLayout(self.header)
        else:
            self.title_label.hide()
            self.hint_label.hide()
        self._has_header = bool(title)

    def add(self, w: QWidget, stretch: int = 0) -> None:
        self._lay.addWidget(w, stretch)

    def add_layout(self, lay) -> None:
        self._lay.addLayout(lay)

    def add_action(self, w: QWidget) -> None:
        if not self._has_header:
            self._lay.insertLayout(0, self.header)
            self._has_header = True
        self.header.addWidget(w)

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)
        self.title_label.show()

    def set_hint(self, text: str) -> None:
        self.hint_label.setText(text)


class StatCard(QFrame):
    """指标卡：左侧竖色条 + 标签 + 大数字 + 单位 + 辅助说明。"""

    def __init__(self, label: str, unit: str = "元", accent: str = theme.NAVY_2,
                 hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setMinimumHeight(86)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 12, 0)
        lay.setSpacing(0)

        bar = QFrame()
        bar.setFixedWidth(4)
        bar.setStyleSheet(f"background:{accent};border-top-left-radius:10px;"
                          f"border-bottom-left-radius:10px;")
        lay.addWidget(bar)

        body = QVBoxLayout()
        body.setContentsMargins(13, 9, 0, 9)
        body.setSpacing(2)
        self.label = QLabel(label)
        self.label.setObjectName("StatLabel")
        row = QHBoxLayout()
        row.setSpacing(5)
        self.value = QLabel("0")
        self.value.setObjectName("StatValue")
        self.unit = QLabel(unit)
        self.unit.setObjectName("StatUnit")
        self.unit.setAlignment(Qt.AlignBottom)
        row.addWidget(self.value)
        row.addWidget(self.unit)
        row.addStretch(1)
        self.hint = QLabel(hint)
        self.hint.setObjectName("StatHint")
        body.addWidget(self.label)
        body.addLayout(row)
        body.addWidget(self.hint)
        lay.addLayout(body)

    def set_value(self, text: str, hint: str = "", color: str | None = None) -> None:
        self.value.setText(text)
        if color:
            self.value.setStyleSheet(f"color:{color};")
        if hint:
            self.hint.setText(hint)


# ------------------------------------------------------------------ 表格
@dataclass
class Column:
    title: str
    width: int = 100
    align: str = "left"          # left / right / center
    stretch: bool = False


class HeaderBar(QHeaderView):
    """带「排序 / 筛选」下拉的表头，也支持两行式（分组）表头。

    单行时：点每列右侧的小三角，弹「升序 / 降序 / 只显示某个值」。
    两行时：第一行画分组（入库 / 出库 / 结余），第二行画具体列名——
    照客户《账表记录-羊》里那张暂养台账的版式。

    排序、筛选由页面自己执行（页面知道这一列怎么取值、怎么比大小），表头只负责：
    画分组带、画三角、发菜单请求。
    """

    menuRequested = Signal(int, QPoint)
    ARROW_ZONE = 18
    GROUP_H = 24

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Horizontal, parent)
        self._sort_col = -1
        self._sort_desc = False
        self._filtered: set[int] = set()
        self._groups: list[tuple[str, int, int]] = []
        self.setMouseTracking(True)

    # ------------------------------------------------------------ 状态
    def set_state(self, sort_col: int = -1, desc: bool = False,
                  filtered: Iterable[int] = ()) -> None:
        self._sort_col = int(sort_col)
        self._sort_desc = bool(desc)
        self._filtered = set(filtered or ())
        self.viewport().update()

    @property
    def group_height(self) -> int:
        return self.GROUP_H if self._groups else 0

    def set_groups(self, groups: Iterable[tuple[str, int, int]]) -> None:
        self._groups = [(str(t), int(c1), int(c2)) for t, c1, c2 in (groups or [])]
        self.viewport().update()

    def _grouped_columns(self) -> set[int]:
        out: set[int] = set()
        for _title, c1, c2 in self._groups:
            out.update(range(c1, c2 + 1))
        return out

    def _in_arrow_zone(self, index: int, x: int) -> bool:
        """右端 18px 是下拉三角区，但要避开最边上 4px——那是拖列宽的手柄。"""
        right = self.sectionViewportPosition(index) + self.sectionSize(index)
        return right - self.ARROW_ZONE <= x <= right - 4

    # ------------------------------------------------------------ 绘制
    def paintSection(self, painter: QPainter, rect, index: int) -> None:   # noqa: N802
        if self._groups:
            return                          # 分组表头整套自己画，这里不掺和
        super().paintSection(painter, rect, index)
        self._paint_marks(painter, index, rect)

    def paintEvent(self, event) -> None:    # noqa: N802
        if not self._groups:
            super().paintEvent(event)
            return
        p = QPainter(self.viewport())
        vw, h, gh = self.viewport().width(), self.height(), self.GROUP_H
        line = QColor(theme.BORDER)
        p.fillRect(QRect(0, 0, vw, h), QColor("#F1F5FB"))

        # 竖线：分组内只在叶子行画分隔，分组带整段合并（照 Excel 的合并单元格）
        p.setPen(QPen(line, 1))
        grouped = self._grouped_columns()
        ends = {c2 for _t, _c1, c2 in self._groups}
        for i in range(self.count()):
            if self.isSectionHidden(i):
                continue
            x = self.sectionViewportPosition(i) + self.sectionSize(i) - 1
            if not (-1 <= x <= vw):
                continue
            if i in grouped:
                if i in ends:
                    p.drawLine(x, 0, x, gh - 1)
                p.drawLine(x, gh, x, h)
            else:
                p.drawLine(x, 0, x, h)
        # 横线：分组带下沿 + 表头下沿
        p.drawLine(0, gh - 1, vw, gh - 1)
        p.drawLine(0, h - 1, vw, h - 1)

        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(9.0)
        p.setFont(f)
        p.setPen(QColor(theme.NAVY))
        for title, c1, c2 in self._groups:
            if self.isSectionHidden(c1) or self.isSectionHidden(c2):
                continue
            x1 = self.sectionViewportPosition(c1)
            x2 = self.sectionViewportPosition(c2) + self.sectionSize(c2)
            p.drawText(QRect(x1, 0, x2 - x1, gh - 1), Qt.AlignCenter, title)

        for i in range(self.count()):
            if self.isSectionHidden(i):
                continue
            x, cw = self.sectionViewportPosition(i), self.sectionSize(i)
            top = gh if i in grouped else 0
            band = QRect(x, top, cw, h - 1 - top)
            align = (Qt.AlignHCenter if i == 0 else Qt.AlignLeft) | Qt.AlignVCenter
            p.setPen(QColor(theme.NAVY))
            box = band.adjusted(8 if i else 0, 2, -18, -2)
            text = str(self.model().headerData(i, Qt.Horizontal) or "")
            p.drawText(box, align | Qt.TextWordWrap, text)
            self._paint_marks(p, i, band)
        p.end()

    def _paint_marks(self, painter: QPainter, index: int, rect) -> None:
        """列右端的排序三角 / 筛选漏斗 / 下拉提示。"""
        if index <= 0 or self.count() <= 1:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        right = rect.right() - 7
        cy = rect.center().y()
        if index == self._sort_col:
            color = QColor(theme.NAVY_2)
            if self._sort_desc:
                points = [QPointF(right - 4.5, cy - 2.0), QPointF(right + 4.5, cy - 2.0),
                          QPointF(right, cy + 3.0)]
            else:
                points = [QPointF(right - 4.5, cy + 2.0), QPointF(right + 4.5, cy + 2.0),
                          QPointF(right, cy - 3.0)]
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.drawPolygon(points)
        elif index in self._filtered:
            # 漏斗：上宽下窄，提示这一列筛过值
            painter.setBrush(QColor(theme.GOLD))
            painter.setPen(Qt.NoPen)
            painter.drawPolygon([QPointF(right - 4.5, cy - 3.0), QPointF(right + 4.5, cy - 3.0),
                                 QPointF(right + 1.0, cy + 1.5), QPointF(right + 1.0, cy + 3.5),
                                 QPointF(right - 1.0, cy + 3.5), QPointF(right - 1.0, cy + 1.5)])
        else:
            painter.setPen(QPen(QColor("#A9B7C9"), 1.2, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(right - 3.0, cy - 1.5), QPointF(right, cy + 1.2))
            painter.drawLine(QPointF(right, cy + 1.2), QPointF(right + 3.0, cy - 1.5))
        painter.restore()

    # ------------------------------------------------------------ 交互
    def mousePressEvent(self, event) -> None:       # noqa: N802
        pos = event.position().toPoint()
        index = self.logicalIndexAt(pos)
        if index > 0 and self._in_arrow_zone(index, pos.x()):
            self.menuRequested.emit(index, self.viewport().mapToGlobal(pos))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:     # noqa: N802
        # 点在三角上的按下已被吞掉，松手别再当成「点表头」
        pos = event.position().toPoint()
        index = self.logicalIndexAt(pos)
        if index > 0 and self._in_arrow_zone(index, pos.x()):
            event.accept()
            return
        super().mouseReleaseEvent(event)


class DataTable(QTableWidget):
    """只读台账表：斑马纹、整行选中、数值右对齐、列可拖动换位。"""

    def __init__(self, columns: Sequence[Column], parent: QWidget | None = None,
                 row_height: int = 30) -> None:
        super().__init__(0, len(columns), parent)
        self.columns = list(columns)
        self._payloads: list[Any] = []
        self._fitting = False
        self._user_sized = False
        self._auto_shrink = True        # 两行表头的宽台账关掉：列宽照声明值，宁可横向滚
        self.setHorizontalHeaderLabels([c.title for c in self.columns])
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(row_height)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        header = HeaderBar(self)
        self.setHorizontalHeader(header)
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setSectionsMovable(True)
        header.setSectionsClickable(True)
        header.setMinimumSectionSize(36)
        header.setStretchLastSection(False)
        for i, col in enumerate(self.columns):
            header.setSectionResizeMode(i, QHeaderView.Interactive)
            self.setColumnWidth(i, col.width)
        header.sectionResized.connect(self._on_section_resized)

    def set_header_groups(self, groups: Iterable[tuple[str, int, int]],
                          group_height: int = 24) -> None:
        """两行式表头：第一行分组，第二行列名。"""
        self.header_bar.GROUP_H = int(group_height)
        self.header_bar.set_groups(groups)
        self._auto_shrink = not groups       # 两行表头的台账列多，缩了表头就折行
        if groups:
            self.header_bar.setFixedHeight(int(group_height) + 36)
        else:
            self.header_bar.setFixedHeight(35)

    @property
    def header_bar(self) -> HeaderBar:
        return self.horizontalHeader()      # type: ignore[return-value]

    def set_sort_filter(self, sort_col: int = -1, desc: bool = False,
                        filtered: Iterable[int] = ()) -> None:
        self.header_bar.set_state(sort_col, desc, filtered)

    def _fit_columns(self) -> None:
        """列宽调到刚好铺满视口；用户拖过就不再自动调。"""
        viewport = self.viewport().width()
        if viewport < 240:
            return
        n = self.columnCount()
        widths = [self.columns[i].width for i in range(n)]
        if not self._auto_shrink:
            return
        mins = [max(44, self.columns[i].width - (40 if self.columns[i].stretch else 6))
                for i in range(n)]
        gap = viewport - sum(widths)
        if gap >= 0:
            targets = [i for i, c in enumerate(self.columns) if c.stretch] or [n - 1]
            for i in targets:
                widths[i] += gap // len(targets)
        else:
            excess = -gap
            shrinkable = [i for i in range(n) if widths[i] > mins[i]]
            while excess > 0 and shrinkable:
                i = max(shrinkable, key=lambda k: widths[k])
                widths[i] -= 1
                excess -= 1
                if widths[i] <= mins[i]:
                    shrinkable.remove(i)
        self._fitting = True
        try:
            for i, w in enumerate(widths):
                self.setColumnWidth(i, w)
        finally:
            self._fitting = False

    def _on_section_resized(self, *_args) -> None:
        if not self._fitting:
            self._user_sized = True

    def resizeEvent(self, event) -> None:        # noqa: N802
        super().resizeEvent(event)
        if not self._user_sized:
            self._fit_columns()

    def showEvent(self, event) -> None:          # noqa: N802
        super().showEvent(event)
        if not self._user_sized:
            self._fit_columns()

    def set_rows(self, rows: Sequence[Sequence[Any]], payloads: Sequence[Any] | None = None,
                 colors: dict[tuple[int, int], str] | None = None,
                 row_colors: dict[int, str] | None = None,
                 bold_rows: set[int] | None = None,
                 bg_rows: dict[int, str] | None = None,
                 empty_text: str = "暂无数据") -> None:
        self.setUpdatesEnabled(False)
        self.clearSpans()
        self.clearContents()
        if not rows:
            self.setRowCount(1)
            self.setRowHeight(0, 110)
            self.setSpan(0, 0, 1, max(len(self.columns), 1))
            item = QTableWidgetItem(empty_text)
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor(theme.MUTED))
            self.setItem(0, 0, item)
            self._payloads = []
            self.setUpdatesEnabled(True)
            return
        self.setRowCount(len(rows))
        colors = colors or {}
        row_colors = row_colors or {}
        bold_rows = bold_rows or set()
        bg_rows = bg_rows or {}
        for r, row in enumerate(rows):
            for c in range(len(self.columns)):
                value = row[c] if c < len(row) else ""
                item = QTableWidgetItem("" if value is None else str(value))
                if len(str(item.text())) > 8:       # 列窄时悬停能看全，不用去拖列宽
                    item.setToolTip(str(item.text()))
                align = self.columns[c].align
                item.setTextAlignment(
                    (Qt.AlignRight if align == "right" else
                     Qt.AlignHCenter if align == "center" else Qt.AlignLeft) | Qt.AlignVCenter)
                color = colors.get((r, c)) or row_colors.get(r)
                if color:
                    item.setForeground(QColor(color))
                if r in bold_rows:
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                if r in bg_rows:
                    item.setBackground(QColor(bg_rows[r]))
                self.setItem(r, c, item)
        self._payloads = list(payloads or [])
        self.setUpdatesEnabled(True)

    def payload(self, row: int | None = None) -> Any:
        if row is None:
            row = self.currentRow()
        if 0 <= row < len(self._payloads):
            return self._payloads[row]
        return None

    def current_payload(self) -> Any:
        return self.payload(self.currentRow())

    def clear_rows(self) -> None:
        self.set_rows([], [])


# ------------------------------------------------------------------ 下拉箭头
def _draw_chevron(w: QWidget) -> None:
    """自己画一个细箭头：QSS 覆盖 ::drop-down 后 Fusion 不再画箭头，只能补一笔。"""
    p = QPainter(w)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(theme.MUTED), 1.6))
    x = w.width() - 15.0
    y = w.height() / 2.0 - 2.0
    p.drawLine(int(x - 4), int(y), int(x), int(y + 4))
    p.drawLine(int(x), int(y + 4), int(x + 4), int(y))
    p.end()


class Combo(QComboBox):
    def paintEvent(self, event) -> None:      # noqa: N802
        super().paintEvent(event)
        _draw_chevron(self)


# 下拉日历自己的样式：它是弹窗，不跟着 app 级 QSS 走（系统深色模式下会整块变黑，
# 日期看不见），只能直接挂到日历控件上。浅色、白底、深蓝选中，跟表格一个调子。
CAL_QSS = """
QWidget { background: #FFFFFF; }
QWidget#qt_calendar_navigationbar { background: #F1F5FB; border-bottom: 1px solid #E4E9F2; }
QToolButton { background: transparent; border: none; color: #112A46;
              font-size: 12.5px; font-weight: bold; padding: 3px 7px; border-radius: 4px; }
QToolButton:hover { background: #E3ECF8; }
QToolButton:pressed { background: #D6E4F6; }
QToolButton::menu-indicator { width: 0px; image: none; }
QMenu { background: #FFFFFF; color: #1F2937; border: 1px solid #E4E9F2; }
QSpinBox { background: #FFFFFF; color: #1F2937; border: 1px solid #E4E9F2;
           border-radius: 4px; padding: 1px 4px; }
QHeaderView::section { background: #FFFFFF; color: #6B7A90; border: none;
                       padding: 3px 0px; font-size: 11.5px; font-weight: normal; }
QAbstractItemView { background: #FFFFFF; outline: 0; alternate-background-color: #F7F9FC;
                    selection-background-color: #1E4E79; selection-color: #FFFFFF; }
QAbstractItemView:disabled { color: #A8B3C4; }
"""


class DateEdit(QDateEdit):
    """带小箭头、日历弹窗尺寸适中的日期框。

    下拉日历最小 272×208：默认那一小块只露出三周，点日期容易点错；
    顺便把左边那列周号去掉、周一起头，跟中文日历的习惯一致。
    """

    def paintEvent(self, event) -> None:      # noqa: N802
        super().paintEvent(event)
        _draw_chevron(self)

    def setCalendarPopup(self, enable: bool) -> None:     # noqa: N802
        super().setCalendarPopup(enable)
        if not enable:
            return
        cal = self.calendarWidget()
        if cal is None:
            return
        cal.setMinimumSize(272, 208)
        cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        cal.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
        cal.setGridVisible(False)
        cal.setFirstDayOfWeek(Qt.Monday)
        cal.setStyleSheet(CAL_QSS)          # 弹窗不认 app 级 QSS，只能单独挂


# ------------------------------------------------------------------ 小控件
def label(text: str, name: str = "Muted", parent: QWidget | None = None) -> QLabel:
    lb = QLabel(text, parent)
    lb.setObjectName(name)
    return lb


def button(text: str, kind: str = "", slot: Callable | None = None,
           tip: str = "") -> QPushButton:
    btn = QPushButton(text)
    if kind:
        btn.setObjectName(kind)
    btn.setCursor(Qt.PointingHandCursor)
    if tip:
        btn.setToolTip(tip)
    if slot is not None:
        btn.clicked.connect(slot)
    return btn


def search_input(placeholder: str = "搜索…", width: int = 190) -> QLineEdit:
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    edit.setClearButtonEnabled(True)
    edit.setFixedWidth(width)
    return edit


def set_combo_items(cb: QComboBox, items: Sequence[str], keep: bool = True) -> None:
    """重置下拉项；keep=True 时尽量保留当前选择。"""
    current = cb.currentText() if keep else ""
    cb.blockSignals(True)
    cb.clear()
    cb.addItems([str(i) for i in items])
    if current:
        idx = cb.findText(current)
        if idx >= 0:
            cb.setCurrentIndex(idx)
    cb.blockSignals(False)


def combo(items: Sequence[str] = (), width: int = 140, editable: bool = False) -> QComboBox:
    cb = Combo()
    cb.setFixedWidth(width)
    cb.setEditable(editable)
    if editable:
        cb.setInsertPolicy(QComboBox.NoInsert)
    set_combo_items(cb, items)
    return cb


def date_edit(value: str = "", width: int = 128) -> QDateEdit:
    de = DateEdit()
    de.setCalendarPopup(True)
    de.setDisplayFormat("yyyy-MM-dd")
    de.setFixedWidth(width)
    d = QDate.fromString(value, "yyyy-MM-dd")
    de.setDate(d if d.isValid() else QDate.currentDate())
    return de


def hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet(f"color:{theme.BORDER};background:{theme.BORDER};max-height:1px;")
    return line


def badge(text: str, kind: str = "Badge") -> QLabel:
    lb = QLabel(text)
    lb.setObjectName(kind)
    return lb


# ------------------------------------------------------------------ 布局助手
def hbox(*widgets, spacing: int = 8, margins: tuple[int, int, int, int] = (0, 0, 0, 0)) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    return lay


def vbox(*widgets, spacing: int = 10, margins: tuple[int, int, int, int] = (0, 0, 0, 0)) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    return lay


class PageBase(QWidget):
    """所有功能页的基类：统一处理上下文、刷新时机与页内提示。

    还留了几个「界面级 保存 / 撤消 / 恢复」要问的接口：能撤消吗、有没有没存的编辑。
    默认都没实现，只有行内台账页真的答得上来。
    """

    changed = Signal()
    history_changed = Signal()      # 撤消栈变了：工具栏按钮要跟着亮/灰
    LEDGER = False                  # 是不是行内台账页（只有台账页才需要 保存/撤消/恢复）

    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._built = False

    def refresh(self) -> None:
        pass

    # ------ 界面级 保存 / 撤消 / 恢复（子类按需覆写）
    def has_pending(self) -> bool:
        return False

    def save_pending(self) -> None:
        return None

    def can_undo(self) -> bool:
        return False

    def can_redo(self) -> bool:
        return False

    def undo(self) -> None:
        return None

    def redo(self) -> None:
        return None

    def on_show(self) -> None:
        self.refresh()

    def notify(self, message: str, level: str = "info") -> None:
        self.ctx.notify(message, level)

    def has_help(self) -> bool:
        return getattr(self, "help", None) is not None

    def toggle_help(self, on: bool | None = None) -> None:
        panel = getattr(self, "help", None)
        if panel is None:
            return
        if on is None:
            on = not panel.isVisible()
        panel.setVisible(bool(on))
        btn = getattr(self, "help_btn", None)
        if btn is not None:
            btn.setChecked(bool(on))
            btn.setText("收起说明" if on else "填写说明")


class HelpPanel(QLabel):
    """「填写说明」展开后的说明块：浅底圆角，默认收起。"""

    def __init__(self, html: str, parent: QWidget | None = None) -> None:
        super().__init__(html, parent)
        self.setObjectName("HelpPanel")
        self.setTextFormat(Qt.RichText)
        self.setWordWrap(True)
        self.setStyleSheet(
            f"QLabel#HelpPanel{{background:#F7FAFE;border:1px solid #DCE6F2;border-radius:8px;"
            f"color:{theme.TEXT};font-size:12px;padding:9px 12px;margin:2px 0px 6px 0px;}}")
        self.hide()


def help_button(slot: Callable | None = None) -> QPushButton:
    btn = button("填写说明", "", slot, tip="本页口径说明：每列、每个数是怎么算出来的")
    btn.setCheckable(True)
    btn.setFixedHeight(22)
    btn.setMinimumWidth(78)
    btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    btn.setStyleSheet("padding:0px 10px;font-size:12px;")
    return btn


class FilterStrip(QFrame):
    """筛选条：一行放标签与控件，右边留伸缩位放按钮。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FilterStrip")
        self.setStyleSheet("QFrame#FilterStrip{background:transparent;}")
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(2, 4, 2, 6)
        self._lay.setSpacing(7)

    def add(self, w: QWidget) -> None:
        self._lay.addWidget(w)

    def add_label(self, text: str) -> None:
        self._lay.addWidget(label(text, "Muted"))

    def add_stretch(self) -> None:
        self._lay.addStretch(1)


class SumBar(QFrame):
    """页脚合计行：分列显示数量 / 金额合计。"""

    def __init__(self, table: DataTable, label_span: int = 1, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SumBar")
        self.setStyleSheet("QFrame#SumBar{background:#FBFCFE;border:1px solid "
                           f"{theme.BORDER};border-radius:8px;}}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(16)
        self._table = table
        self._label_span = label_span
        self.left = QLabel("")
        self.left.setStyleSheet(f"color:{theme.MUTED};font-size:12px;")
        lay.addWidget(self.left)
        lay.addStretch(1)
        self.right = QLabel("")
        self.right.setStyleSheet(f"color:{theme.NAVY};font-size:12.5px;font-weight:bold;")
        lay.addWidget(self.right)

    def set_text(self, left: str = "", right: str = "") -> None:
        self.left.setText(left)
        self.right.setText(right)
