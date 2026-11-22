"""行内录入台账的公共骨架。

六张平铺台账（暂养出入库、养殖、屠宰出库、门店入库、门店销售、门店盘点）共用这一套：
筛选条 + 表格（序号 / 数据列 / 操作）+ 页脚合计 + 导出。

交互按 WPS 表格的习惯来：
    序号列      鼠标移到行号上，右下角冒出一个「＋」，点它就在本行下面插入一行
    操作列      只放一枚「多功能集」（删除 / 撤消 / 恢复）；编辑靠双击一行或单元格，不再占图标
    保存        不留保存按钮——改完点别处（换行、换页、点空白）即自动保存；
                填得不合法就先提示，本行保持编辑态，数据不丢
    撤消 / 恢复  记在页面自己的历史栈里，删错了可以原样捡回来

子类只声明三件事：
    FIELDS      列与录入控件的规格（FieldSpec）
    fetch()     取数（口径在 core/calc.py 里算好，页面只负责显示）
    save/delete 落库

设计取舍：**就地编辑，不弹窗口**。台账一行就是一条账，弹窗会把「看上下文」这件事
打断；就地改能一边对着上下行、一边改。例外是屠宰记录——一张单带多条产出明细，
头行 + 明细的结构用对话框更清楚，见 ui/dialogs.SlaughterDialog。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from PySide6.QtCore import QDate, QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDoubleValidator, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QCompleter,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mscm import config
from mscm.core import repo
from mscm.core.models import month_start
from mscm.core.services import export as xl_export
from mscm.ui import icons, theme
from mscm.ui.dialogs import confirm, info
from mscm.ui.widgets import (
    Card,
    Column,
    Combo,
    DataTable,
    DateEdit,
    FilterStrip,
    HelpPanel,
    PageBase,
    SumBar,
    button,
    money,
    num,
    search_input,
)

DRAFT_BG = "#FFFBEA"        # 新增草稿行底色（浅琥珀）
SEQ_COL_W = 46              # 序号列：留得下两位数 + 那个「＋」
OPS_COL_W = 46              # 操作列：只放一枚「多功能集」图标
HISTORY_MAX = 50            # 撤消栈深度

EDIT_QSS = (
    "QComboBox,QLineEdit,QDateEdit{background:#FFFFFF;color:#1F2937;"
    "border:1px solid #A9C0DA;border-radius:4px;padding:1px 4px;font-size:12px;"
    "min-height:18px;max-height:24px;}"
    # 日期框：右端留 18px 作「点开日历」的点击区（收成 0 就点不开了），
    # 文字区靠右 padding 让出来，日期才不会被箭头压掉
    "QDateEdit{padding:1px 2px 1px 4px;}"
    "QDateEdit::drop-down{subcontrol-origin:padding;subcontrol-position:center right;"
    "width:18px;border:none;background:transparent;}"
    "QComboBox:focus,QLineEdit:focus,QDateEdit:focus{border:1px solid #2A6094;}"
)
RO_QSS = (
    "QLineEdit{background:#EFF3F9;color:#5B6B80;border:1px solid #DCE3ED;"
    "border-radius:4px;padding:1px 4px;font-size:12px;min-height:18px;max-height:24px;}"
)
ICON_BTN_QSS = """
QPushButton { background: transparent; border: 1px solid transparent;
              border-radius: 5px; padding: 0px; }
QPushButton:hover { background: #E2EDF9; border-color: #CBE0F4; }
QPushButton:pressed { background: #D2E3F5; }
QPushButton:disabled { background: transparent; border-color: transparent; }
"""
# 文字型行尾按钮的样式：屠宰记录页（单据 + 明细用对话框）还在用
ROW_BTN_QSS = """
QPushButton { background: transparent; border: none; color: #2A6094;
              padding: 1px 4px; font-size: 12px; border-radius: 4px; }
QPushButton:hover { background: #DCE8F6; }
QPushButton:disabled { color: #B6C2D2; }
QPushButton#RowDel { color: #C0392B; }
QPushButton#RowDel:hover { background: #FCECEA; }
QPushButton#RowSave { color: #0F8A5F; font-weight: bold; }
QPushButton#RowSave:hover { background: #E8F6F0; }
QPushButton#RowCancel { color: #8A6D3B; }
QPushButton#RowCancel:hover { background: #FBF3E4; }
"""

ALL_BATCH = "全部批次"


@dataclass
class FieldSpec:
    """一列的显示与录入规格。"""

    key: str
    label: str
    kind: str = "text"      # text / date / date_opt / num / money / int / combo / batch / store / product / computed
    width: int = 100
    align: str = "left"
    decimals: int = 1
    options: Sequence[str] | Callable[[], Sequence[str]] = field(default_factory=tuple)
    required: bool = False
    hint: str = ""
    stretch: bool = False
    placeholder: str = ""
    editable: bool = False


def _fmt_num(value: Any, decimals: int) -> str:
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return ""
    if not v:
        return ""
    return f"{v:,.{decimals}f}"


def _to_float(text: str) -> float:
    try:
        return float(str(text or "0").replace(",", "").strip())
    except ValueError:
        return 0.0


def _icon_button(icon, tip: str, slot: Callable | None = None) -> QPushButton:
    """操作列的图标按钮：透明底、悬停浅蓝，22×22 里放 16px 图标。"""
    btn = QPushButton()
    btn.setIcon(icon)
    btn.setIconSize(QSize(17, 17))
    btn.setFixedSize(26, 26)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(ICON_BTN_QSS)
    btn.setToolTip(tip)
    if slot is not None:
        btn.clicked.connect(slot)
    return btn


class SeqCell(QWidget):
    """序号格：显示行号；鼠标移上来时左下角冒出一个「＋」，点它在**本行下面**插一行。

    画在自己身上而不是塞子控件，原因是整格都要能感应悬停，
    子控件会和单元格的选中底色、斑马纹打架。
    """

    insertRequested = Signal()

    def __init__(self, number: str, editable_row: bool = True,
                 draft: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._number = number
        self._editable = editable_row
        self._draft = draft
        self._hover = False
        self.setMouseTracking(True)
        self.setToolTip("插入行" if editable_row else "")
        self.setCursor(Qt.ArrowCursor)

    # ------------------------------------------------------------ 绘制
    def _plus_rect(self) -> QRectF:
        d = 14.0
        return QRectF(1.5, float(self.height()) - d - 2.0, d, d)

    def paintEvent(self, event) -> None:        # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        f = QFont(self.font())
        f.setPointSizeF(9.0)
        p.setFont(f)
        p.setPen(QColor(theme.GOLD if self._draft else theme.MUTED))
        p.drawText(self.rect().adjusted(0, 0, -6, 0),
                   Qt.AlignRight | Qt.AlignVCenter, self._number)

        if self._hover and self._editable:
            r = self._plus_rect()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.NAVY_LIGHT))
            p.drawEllipse(r)
            c = r.center()
            p.setPen(QPen(QColor("#FFFFFF"), 1.4, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPoint(int(c.x() - 3), int(c.y())), QPoint(int(c.x() + 3), int(c.y())))
            p.drawLine(QPoint(int(c.x()), int(c.y() - 3)), QPoint(int(c.x()), int(c.y() + 3)))
        p.end()

    # ------------------------------------------------------------ 悬停 / 点击
    def enterEvent(self, event) -> None:        # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:        # noqa: N802
        self._hover = False
        self.setCursor(Qt.ArrowCursor)
        self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event) -> None:    # noqa: N802
        on_plus = self._editable and self._plus_rect().contains(event.position())
        self.setCursor(Qt.PointingHandCursor if on_plus else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:   # noqa: N802
        if (self._editable and event.button() == Qt.LeftButton
                and self._plus_rect().contains(event.position())):
            event.accept()
            self.insertRequested.emit()
            return
        super().mousePressEvent(event)


class OpsStrip(QWidget):
    """冻结在表格右边缘的「操作」列。

    为什么不直接把「操作」做成表格的一列：暂养台账 17 列，窗口根本放不下，
    操作列会滑到屏幕外，删一行还得先横向拖到底。这里把它画成盖在右边缘的一层：
    竖着跟行走、横着不动，行底色与选中态跟表格保持一致，看着还是同一张表。
    """

    def __init__(self, table: DataTable, spec: list[dict], width: int = OPS_COL_W) -> None:
        """spec 是这一列要摆的图标：
        [{icon: () -> QIcon, tip: str, run: (row, anchor) -> None, enabled: (item) -> bool}]
        """
        super().__init__(None)
        self._table = table
        self._spec = list(spec or [])
        self._width = width
        self.setFixedWidth(width)
        self._items: list[dict] = []
        self._btns: dict[int, QWidget] = {}
        table.verticalScrollBar().valueChanged.connect(self._relayout)
        table.viewport().installEventFilter(self)
        self.raise_()

    # ------------------------------------------------------------ 数据
    def set_items(self, items: list[dict]) -> None:
        """items 与表格行一一对应：{rec, draft, editing}。"""
        self._items = items
        for box in self._btns.values():
            box.setParent(None)
            box.deleteLater()
        self._btns = {}
        self._relayout()

    # ------------------------------------------------------------ 布局
    def eventFilter(self, obj, event) -> bool:      # noqa: N802
        try:
            if obj is self._table.viewport() and event.type() in (QEvent.Resize, QEvent.Show):
                self._relayout()
        except RuntimeError:        # 关窗时表格先被销毁，别再碰它
            return False
        return super().eventFilter(obj, event)

    def _relayout(self, *_args) -> None:
        self._place_buttons()
        self.update()

    def resizeEvent(self, event) -> None:       # noqa: N802
        super().resizeEvent(event)
        self._place_buttons()

    def showEvent(self, event) -> None:         # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._place_buttons)

    def _top(self) -> int:
        """表格视口顶端在本列里的 y。

        表格与本列并排、同高同起点，直接取视口在表格里的 y（表头高 + 边框）即可；
        mapTo 在布局尚未落定时会给出离谱的值，不能用。
        """
        return self._table.viewport().geometry().top()

    def _place_buttons(self) -> None:
        top = self._top()
        for box in self._btns.values():
            box.hide()
        for i, _item in enumerate(self._items):
            y = top + self._table.rowViewportPosition(i)
            h = self._table.rowHeight(i)
            if y + h <= top or y >= self.height():
                continue
            box = self._btns.get(i) or self._make_row(i)
            self._btns[i] = box
            box.setGeometry(0, y, self.width(), min(h, self.height() - y))
            box.show()

    def _make_row(self, row: int) -> QWidget:
        item = self._items[row] if row < len(self._items) else {}
        box = QWidget(self)
        box.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addStretch(1)
        for act in self._spec:
            btn = _icon_button(act["icon"](), act["tip"])
            btn.clicked.connect(lambda _c=False, r=row, b=btn, a=act: a["run"](r, b))
            check = act.get("enabled")
            btn.setEnabled(bool(check(item)) if check else True)
            lay.addWidget(btn)
        lay.addStretch(1)
        return box

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:            # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.CARD))
        top = self._top()

        # 行底色：草稿浅黄、当前行浅蓝、奇数行斑马纹——跟表格对得上，看不出接缝
        for i, item in enumerate(self._items):
            y = top + self._table.rowViewportPosition(i)
            h = self._table.rowHeight(i)
            if y >= self.height() or y + h <= top:
                continue
            if item.get("draft"):
                bg = DRAFT_BG
            elif item.get("bg"):
                bg = str(item.get("bg"))
            elif self._table.currentRow() == i:
                bg = "#E3ECF8"
            elif i % 2:
                bg = "#FAFBFD"
            else:
                bg = theme.CARD
            p.fillRect(QRect(1, y, self.width() - 1, h), QColor(bg))

        # 表头带：和表格表头同色同字重，接上去像一列
        p.fillRect(QRect(1, 0, self.width() - 1, top - 1), QColor("#F1F5FB"))
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(9.0)
        p.setFont(f)
        p.setPen(QColor(theme.NAVY))
        gh = self._table.header_bar.group_height     # 两行表头时，文字跟叶子行齐平
        p.drawText(QRect(1, gh, self.width() - 1, top - 1 - gh), Qt.AlignCenter, "操作")

        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.drawLine(0, 0, 0, self.height())
        p.drawLine(1, top - 1, self.width(), top - 1)
        p.end()


class InlineLedgerPage(PageBase):
    """行内录入台账基类。"""

    TITLE = "台账"
    MODULE = ""
    LEDGER = True
    FIELDS: list[FieldSpec] = []
    HELP_HTML = ""
    DATE_FILTER = True
    BATCH_FILTER = True
    BATCH_OPTIONAL = True          # 编辑时批次下拉是否允许「不指定批次」
    SUM_KEYS: tuple[tuple[str, str], ...] = ()      # (字段, 口径 qty/money/int)
    HEADER_GROUPS: tuple[tuple[str, int, int], ...] = ()   # 两行表头：(组名, 起始列, 结束列)
    ROW_NAME = "记录"
    EXPORT_STEM = "台账"
    KEYWORD_TIP = "批次 / 商品 / 客户…"
    NEW_TIP = "在首行插入一行空白单据；填完点别处自动保存"

    def __init__(self, ctx, parent: QWidget | None = None, store_id: int = 0) -> None:
        super().__init__(ctx, parent)
        self.store_id = int(store_id or 0)
        self._rows: list[dict] = []
        self._view: list[dict | None] = []
        self._draft: dict | None = None
        self._draft_pos = 0
        self._edit_id: int | None = None
        self._editors: dict[str, QWidget] = {}
        self._base: dict = {}
        self._saving = False
        self._edit_token = 0
        self._pending_flag = False          # 上一轮“有没有没存的编辑”，用来通知顶部按钮
        self._history: list[dict] = []      # 撤消栈
        self._future: list[dict] = []       # 恢复栈
        self._draft_open = False            # 草稿是否还开着编辑（False = 搁在那儿等双击继续）
        self._app_hooked = False            # 是否装了全局鼠标监看
        self._sort_col: int | None = None   # 列头排序：列号（1 起，0 是序号）
        self._sort_desc = False
        self._col_filters: dict[int, set[str]] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 6, 14, 4)
        root.setSpacing(0)

        # ---------------- 筛选条 ----------------
        strip = FilterStrip()
        self.d_from = DateEdit()
        self.d_to = DateEdit()
        for w in (self.d_from, self.d_to):
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd")
            w.setFixedWidth(128)
            d = QDate.fromString(ctx.biz_date, "yyyy-MM-dd")
            w.setDate(d if d.isValid() else QDate.currentDate())
        # 默认看「本月 1 日 → 业务日期」：台账是按月结的，进来就落在当月，不用先调日期
        first = QDate.fromString(month_start(ctx.biz_date), "yyyy-MM-dd")
        if first.isValid():
            self.d_from.setDate(first)
        self.f_batch = Combo()
        self.f_batch.setFixedWidth(180)
        self.f_kw = search_input(self.KEYWORD_TIP, 168)

        if self.DATE_FILTER:
            strip.add_label("业务期间")
            strip.add(self.d_from)
            strip.add_label("至")
            strip.add(self.d_to)
            strip.add(button("当日", "", self.range_today, tip="日期范围设为业务日期当天"))
            strip.add(button("本月", "", self.range_month, tip="本月 1 日至业务日期"))
        if self.BATCH_FILTER:
            strip.add(self.f_batch)
        strip.add(self.f_kw)
        strip.add(button("重置", "", self.reset))
        strip.add_stretch()
        for w in self.extra_buttons():
            strip.add(w)
        strip.add(button("导出", "", self.on_export, tip="按当前筛选导出 Excel（版式同《账表记录-羊》）"))
        self.btn_new = button("＋ 新增", "Primary", self.on_new, tip=self.NEW_TIP)
        strip.add(self.btn_new)
        root.addWidget(strip)

        self.help = HelpPanel(self.HELP_HTML) if self.HELP_HTML else None
        if self.help is not None:
            root.addWidget(self.help)

        # ---------------- 表格 ----------------
        cols = [Column("序号", SEQ_COL_W, "center")]
        cols += [Column(f.label, f.width, f.align, f.stretch) for f in self.FIELDS]
        self.table = DataTable(cols, row_height=30)
        self.table.doubleClicked.connect(lambda *_: self.on_edit_row())
        # 列多的台账（暂养 17 列）操作列会滑出屏幕，右键也给一条入口
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._row_menu)
        self.table.header_bar.menuRequested.connect(self._column_menu)
        if self.HEADER_GROUPS:
            self.table.set_header_groups(self.HEADER_GROUPS)
        # 表格 + 冻结的「操作」列并排：数据列按剩余宽度自适应，操作列永远在最右边
        self.ops = OpsStrip(self.table, [
            {"icon": icons.more_icon, "tip": "多功能集：删除本行",
             "run": lambda r, a: self._more_menu(r, a),
             "enabled": lambda it: bool((it.get("rec") or {}).get("id")) and not it.get("draft")},
        ])
        table_row = QWidget()
        table_row.setStyleSheet("background:transparent;")
        table_lay = QHBoxLayout(table_row)
        table_lay.setContentsMargins(0, 0, 0, 0)
        table_lay.setSpacing(0)
        table_lay.addWidget(self.table, 1)
        table_lay.addWidget(self.ops, 0)
        self.card = Card("台账明细", "")
        self.card.add(table_row, 1)
        self.sums = SumBar(self.table)
        self.card.add(self.sums)
        root.addWidget(self.card, 1)

        # ---------------- 事件 ----------------
        self.d_from.dateChanged.connect(self.refresh)
        self.d_to.dateChanged.connect(self._on_to_changed)
        self.f_batch.currentIndexChanged.connect(self.refresh)
        self.f_kw.textChanged.connect(self.refresh)
        ctx.biz_date_changed.connect(self._on_biz_date)

        self._fill_filters()
        self.refresh()

    # ---------------------------------------------------------- 子类接口
    def fetch(self) -> list[dict]:
        raise NotImplementedError

    def blank(self) -> dict:
        return {"date": self.ctx.biz_date}

    def save_record(self, data: dict, rid: int | None) -> dict:
        raise NotImplementedError

    def delete_record(self, rid: int) -> None:
        raise NotImplementedError

    def recalc(self, values: dict, base: dict | None) -> dict:
        """字段联动：返回需要回填的计算列。"""
        return {}

    def validate(self, values: dict) -> str:
        return ""

    def page_title(self) -> str:
        return self.TITLE

    def export_module_key(self) -> str:
        return self.MODULE

    def locked_keys(self, rec: dict) -> set[str]:
        """编辑时哪几列只读（暂养台账的入库行直接取批次数据，就是这个钩子挡的）。"""
        return set()

    def editable_keys(self, rec: dict) -> set[str] | None:
        """编辑这一行时只给哪几列开录入框；None = 全部字段都能改。

        应收款页拿它来区分「应收单行」和「收款子行」：收款行只让改收款日期 / 金额。
        """
        return None

    def row_bg(self, rec: dict) -> str:
        """这一行的固定底色（空 = 走斑马纹）。收款子行浅蓝一点，看得出它是挂在哪张单下面。"""
        return ""

    def cell_color(self, rec: dict, spec) -> str:
        """某一格的文字颜色（空 = 正常）。「小计」这类说明字用得上。"""
        return ""

    def row_label(self, rec: dict) -> str:
        """删除确认里那一行文字，子类可以换成更贴切的说法。"""
        return str(rec.get("product") or rec.get("_batch_code") or rec.get("date") or "")

    def blank_at(self, view_row: int) -> tuple[dict, int]:
        """插入行用哪个空白模板、插在第几行（默认：紧跟本行下面来一张新单）。"""
        return self.blank(), max(0, min(view_row + 1, len(self._rows)))

    def record_id(self, saved: dict, data: dict) -> int:
        """历史栈里记的行 id。

        默认就是落库返回的主键；一页里混着两张表时子类可以编码一下
        （应收页的收款行存负数，免和应收单 id 撞车）。
        """
        return int((saved or {}).get("id") or 0)

    def extra_buttons(self) -> list[QWidget]:
        """子类要往筛选条加的专用按钮（转门店入库、按账面生成盘点…）。"""
        return []

    # ---------------------------------------------------------- 筛选
    def _fill_filters(self) -> None:
        keep = self.f_batch.currentData() if self.f_batch.count() else 0
        self.f_batch.blockSignals(True)
        self.f_batch.clear()
        self.f_batch.addItem(ALL_BATCH, 0)
        for text, bid in repo.batch_options(self.ctx.conn):
            self.f_batch.addItem(text, bid)
        idx = self.f_batch.findData(keep or 0)
        self.f_batch.setCurrentIndex(idx if idx >= 0 else 0)
        self.f_batch.blockSignals(False)

    @property
    def d1(self) -> str:
        return self.d_from.date().toString("yyyy-MM-dd")

    @property
    def d2(self) -> str:
        return self.d_to.date().toString("yyyy-MM-dd")

    @property
    def batch_id(self) -> int:
        return int(self.f_batch.currentData() or 0)

    @property
    def keyword(self) -> str:
        return self.f_kw.text().strip()

    def range_today(self) -> None:
        self._set_range(self.ctx.biz_date, self.ctx.biz_date)

    def range_month(self) -> None:
        d = QDate.fromString(self.ctx.biz_date, "yyyy-MM-dd")
        if not d.isValid():
            return
        self._set_range(d.toString("yyyy-MM-01"), self.ctx.biz_date)

    def _set_range(self, start: str, end: str) -> None:
        for widget, value in ((self.d_from, start), (self.d_to, end)):
            d = QDate.fromString(value, "yyyy-MM-dd")
            if d.isValid():
                widget.blockSignals(True)
                widget.setDate(d)
                widget.blockSignals(False)
        self.refresh()

    def reset(self) -> None:
        d = QDate.fromString(self.ctx.biz_date, "yyyy-MM-dd")
        for w in (self.d_from, self.d_to):
            w.blockSignals(True)
            if d.isValid():
                w.setDate(d)
            w.blockSignals(False)
        self.f_kw.blockSignals(True)
        self.f_kw.clear()
        self.f_kw.blockSignals(False)
        self.f_batch.blockSignals(True)
        self.f_batch.setCurrentIndex(0)
        self.f_batch.blockSignals(False)
        self._sort_col = None
        self._sort_desc = False
        self._col_filters.clear()
        self.refresh()

    def _on_biz_date(self, day: str) -> None:
        """抬头改了业务日期：筛选区间跟着跳到「该月 1 日 → 该日」。

        不能把起始日也设成同一天——那样区间会塌成一天，台账看着像空了。
        """
        d = QDate.fromString(day, "yyyy-MM-dd")
        if not d.isValid():
            return
        first = QDate(d.year(), d.month(), 1)
        for w, value in ((self.d_from, first), (self.d_to, d)):
            w.blockSignals(True)
            w.setDate(value)
            w.blockSignals(False)
        self.refresh()

    def _on_to_changed(self) -> None:
        """筛选截止日即业务日期，反过来也同步（顶栏日期跟着走）。"""
        self.refresh()
        self.ctx.set_biz_date(self.d2)

    # ---------------------------------------------------------- 渲染
    def refresh(self) -> None:
        # 刷新会重建整张表：正在编辑的行先收掉——能存就存，存不了就搁着/还原，绝不拦着刷新
        if self._editors and not self._saving:
            self._settle_edit()
        self._rows = self._prepare(self.fetch())
        self._render()

    def _clear_widgets(self) -> None:
        for r in range(self.table.rowCount()):
            for c in range(self.table.columnCount()):
                w = self.table.cellWidget(r, c)
                if w is None:
                    continue
                self.table.removeCellWidget(r, c)
                w.setParent(None)
                w.deleteLater()

    def _cell(self, rec: dict, spec: FieldSpec) -> str:
        """一行一列的显示值。"""
        key = spec.key
        if spec.kind == "batch":
            return str(rec.get("_batch_code") or repo.batch_code(self.ctx.conn,
                                                                 int(rec.get("batch_id") or 0)) or "—")
        if spec.kind == "store":
            return str(rec.get("_store_name") or repo.store_name(self.ctx.conn,
                                                                 int(rec.get("store_id") or 0)) or "—")
        if spec.kind == "date_opt":
            value = str(rec.get(key) or "").strip()
            return value or "—"
        val = rec.get(key)
        if spec.kind in ("num",):
            return _fmt_num(val, 1)
        if spec.kind in ("money",):
            return _fmt_num(val, 2)
        if spec.kind in ("int",):
            return _fmt_num(val, 0)
        if spec.kind == "computed":
            decimals = spec.decimals
            return _fmt_num(val, decimals)
        return "" if val is None else str(val)

    def _render(self) -> None:
        self._clear_widgets()
        view: list[dict | None] = list(self._rows)
        draft_index: int | None = None
        if self._draft is not None:
            draft_index = max(0, min(self._draft_pos, len(view)))
            view.insert(draft_index, self._draft)
        self._view = view
        body = [[""] + [self._cell(r, f) for f in self.FIELDS] for r in view]
        bg: dict[int, str] = {}
        for i, rec in enumerate(view):
            color = self.row_bg(rec)
            if color:
                bg[i] = color
        if draft_index is not None:
            bg[draft_index] = DRAFT_BG
        colors: dict[tuple[int, int], str] = {}
        for i, rec in enumerate(view):
            for c, spec in enumerate(self.FIELDS):
                tone = self.cell_color(rec, spec)
                if tone:
                    colors[(i, c + 1)] = tone
        self.table.set_rows(body, view, bg_rows=bg, colors=colors,
                            empty_text="暂无数据：点右上「＋ 新增」，或把鼠标移到序号上点「＋」插入一行")
        for i in range(len(view)):
            self.table.setRowHeight(i, 30)
            self._set_seq(i, draft=(i == draft_index))
        editing = self._editing_row()
        if editing is not None:
            self.table.setRowHeight(editing, 34)
            self._fill_editors(editing, view[editing])
        self.ops.set_items([
            {"rec": rec, "draft": (i == draft_index), "editing": (i == editing),
             "bg": self.row_bg(rec)}
            for i, rec in enumerate(view)
        ])
        self.table.set_sort_filter(self._sort_col or -1, self._sort_desc,
                                   self._col_filters.keys())
        self._hook_app(editing is not None)
        self._update_sums()
        self.card_hint()
        pending = bool(self._editors)
        if pending != self._pending_flag:       # 「保存」按钮亮不亮，看这里
            self._pending_flag = pending
            self.history_changed.emit()

    def card_hint(self) -> None:
        extra = ""
        spec = self._sort_spec()
        if spec is not None:
            extra += (f"　·　按「{spec.label}」{'降' if self._sort_desc else '升'}序"
                      f"（结存仍按逐日累计）")
        if self._col_filters:
            extra += f"　·　已筛 {len(self._col_filters)} 列"
        self.card.set_hint(f"{self.d1} 至 {self.d2}　·　双击一行就地编辑，改完点别处即存"
                           f"　·　序号「＋」插一行{extra}")

    def _update_sums(self) -> None:
        if not self.SUM_KEYS:
            self.sums.set_text(f"共 {len(self._rows)} 行", "")
            return
        parts = []
        for spec in self.SUM_KEYS:
            key, kind = spec[0], spec[1]
            total = sum(_to_float(r.get(key)) for r in self._rows)
            text = money(total) if kind == "money" else num(total, 0 if kind == "int" else 1)
            label_text = (spec[2] if len(spec) > 2 else
                          next((f.label for f in self.FIELDS if f.key == key), key))
            parts.append(f"{label_text} {text}")
        self.sums.set_text(f"共 {len(self._rows)} 行", "　·　".join(parts))

    def _editing_row(self) -> int | None:
        if self._draft is not None:
            if not self._draft_open:
                return None
            return max(0, min(self._draft_pos, max(len(self._view) - 1, 0)))
        if self._edit_id is None:
            return None
        for i, rec in enumerate(self._view):
            if rec is not None and int(rec.get("id") or 0) == int(self._edit_id):
                return i
        return None

    # ---------------------------------------------------------- 序号列 / 操作列
    def _set_seq(self, row: int, draft: bool = False) -> None:
        cell = SeqCell(str(row + 1), editable_row=not draft, draft=draft)
        cell.insertRequested.connect(lambda r=row: self.on_insert_at(r))
        self.table.setCellWidget(row, 0, cell)

    def _more_menu(self, row: int, anchor: QWidget) -> None:
        menu = QMenu(self)
        act_del = menu.addAction(icons.trash_icon(), "删除本行")
        act_del.triggered.connect(lambda: self.delete_row(row))
        # 菜单开着的时候焦点是离开编辑框的，别再触发「离开即存」，否则按钮会被重建掉
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height() + 2)))

    # ---------------------------------------------------------- 编辑器
    def _options(self, spec: FieldSpec) -> list[str]:
        opts = spec.options
        return list(opts() if callable(opts) else opts)

    def _num_edit(self, value: Any, decimals: int, readonly: bool = False) -> QLineEdit:
        text = f"{float(value or 0):.{decimals}f}" if value not in (None, "") else ""
        edit = QLineEdit(text)
        edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if readonly:
            edit.setReadOnly(True)
            edit.setFocusPolicy(Qt.NoFocus)
            edit.setStyleSheet(RO_QSS)
        else:
            validator = QDoubleValidator(0.0, 99_999_999.0, decimals, edit)
            validator.setNotation(QDoubleValidator.StandardNotation)
            edit.setValidator(validator)
            edit.setStyleSheet(EDIT_QSS)
        return edit

    def _make_editor(self, spec: FieldSpec, rec: dict) -> QWidget:
        kind = spec.kind
        if kind in ("date", "date_opt"):
            w = DateEdit()
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd")
            if kind == "date_opt":
                # 可选日期（如「约定收款日」）：把最小日期当空值，显示「（未约定）」
                w.setMinimumDate(QDate(2000, 1, 1))
                w.setSpecialValueText("（未约定）")
                d = QDate.fromString(str(rec.get(spec.key) or ""), "yyyy-MM-dd")
                w.setDate(d if d.isValid() else QDate(2000, 1, 1))
            else:
                # 一页里可能有两列日期（收款日期 / 出库日期…），先认自己的字段，再退回 date
                raw = str(rec.get(spec.key) or rec.get("date") or self.ctx.biz_date)
                d = QDate.fromString(raw, "yyyy-MM-dd")
                w.setDate(d if d.isValid() else QDate.currentDate())
            w.setStyleSheet(EDIT_QSS)
            return w
        if kind in ("num", "money", "int"):
            return self._num_edit(rec.get(spec.key), 0 if kind == "int" else
                                  (1 if kind == "num" else 2))
        if kind == "computed":
            return self._num_edit(rec.get(spec.key), spec.decimals, readonly=True)
        if kind == "ro_text":
            edit = QLineEdit(str(rec.get(spec.key) or ""))
            edit.setReadOnly(True)
            edit.setFocusPolicy(Qt.NoFocus)
            edit.setStyleSheet(RO_QSS)
            return edit
        if kind == "batch":
            cb = Combo()
            for text, bid in repo.batch_options(self.ctx.conn, include_blank=self.BATCH_OPTIONAL):
                cb.addItem(text, bid)
            idx = cb.findData(int(rec.get("batch_id") or 0))
            cb.setCurrentIndex(idx if idx >= 0 else 0)
            cb.setStyleSheet(EDIT_QSS)
            return cb
        if kind == "store":
            cb = Combo()
            for name, sid in self.ctx.store_options():
                cb.addItem(name, sid)
            idx = cb.findData(int(rec.get("store_id") or 0))
            cb.setCurrentIndex(idx if idx >= 0 else 0)
            cb.setStyleSheet(EDIT_QSS)
            return cb
        if kind == "product":
            cb = Combo()
            cb.setEditable(True)
            cb.setInsertPolicy(QComboBox.NoInsert)
            for name in self.ctx.product_names():
                cb.addItem(name)
            cb.setCurrentText(str(rec.get(spec.key) or ""))
            comp = cb.completer()
            if comp is not None:
                comp.setFilterMode(Qt.MatchContains)
                comp.setCompletionMode(QCompleter.PopupCompletion)
            cb.setStyleSheet(EDIT_QSS)
            return cb
        if kind == "combo":
            cb = Combo()
            cb.setEditable(bool(spec.editable))
            if spec.editable:
                cb.setInsertPolicy(QComboBox.NoInsert)
            options = [str(name) for name in self._options(spec)]
            cur = str(rec.get(spec.key) or "").strip()
            if cur and cur not in options:
                options.insert(0, cur)      # 老词（下拉里已经没有这一项了）也别弄丢
            if not cur and not spec.editable:
                options.insert(0, "")       # 空值就一路空着，别悄悄替人挑成第一个选项
            for name in options:
                cb.addItem(name)
            cb.setCurrentText(cur)
            cb.setStyleSheet(EDIT_QSS)
            return cb
        edit = QLineEdit(str(rec.get(spec.key) or ""))
        if spec.placeholder:
            edit.setPlaceholderText(spec.placeholder)
        edit.setStyleSheet(EDIT_QSS)
        return edit

    def _fill_editors(self, row: int, rec: dict | None) -> None:
        rec = rec or {}
        self._editors = {}
        self._edit_token += 1
        locks = self.locked_keys(rec)
        only = self.editable_keys(rec)          # 只给这几列开录入框（收款子行就两列）
        for spec in self.FIELDS:
            if only is not None and spec.key not in only:
                continue
            w = self._make_editor(spec, rec)
            if spec.key in locks:
                if isinstance(w, QLineEdit):
                    w.setReadOnly(True)
                    w.setFocusPolicy(Qt.NoFocus)
                    w.setStyleSheet(RO_QSS)
                elif isinstance(w, DateEdit):
                    w.setReadOnly(True)
                    w.setButtonSymbols(QAbstractSpinBox.NoButtons)
                    w.setFocusPolicy(Qt.NoFocus)
                    w.setStyleSheet(RO_QSS)
            self.table.setCellWidget(row, self._col_index(spec.key), w)
            self._editors[spec.key] = w
            w.installEventFilter(self)              # 盯着「焦点离开」：
            if isinstance(w, QLineEdit) and not w.isReadOnly():
                w.textChanged.connect(self._on_edit_changed)
            elif isinstance(w, QComboBox):
                w.currentTextChanged.connect(self._on_edit_changed)
            elif isinstance(w, DateEdit):
                w.dateChanged.connect(self._on_edit_changed)
        self._base = dict(rec)
        self._on_edit_changed()

    def _col_index(self, key: str) -> int:
        """字段在表格里的列号（0 是序号列）。"""
        for i, spec in enumerate(self.FIELDS):
            if spec.key == key:
                return i + 1
        return 1

    def _collect(self) -> dict:
        """从行内控件读一份值（批次 / 门店带出 id）。"""
        values: dict[str, Any] = {}
        for spec in self.FIELDS:
            w = self._editors.get(spec.key)
            if w is None:
                continue
            kind = spec.kind
            if kind in ("date", "date_opt"):
                if isinstance(w, DateEdit):
                    text = w.date().toString("yyyy-MM-dd")
                    values[spec.key] = ("" if kind == "date_opt" and text == "2000-01-01"
                                        else text)
                else:
                    values[spec.key] = w.text().strip()
            elif isinstance(w, QComboBox):
                if kind == "batch":
                    values["batch_id"] = int(w.currentData() or 0)
                    values[spec.key] = w.currentText()
                elif kind == "store":
                    values["store_id"] = int(w.currentData() or 0)
                else:
                    values[spec.key] = w.currentText().strip()
            elif isinstance(w, QLineEdit):
                if kind in ("num", "money", "int", "computed"):
                    values[spec.key] = _to_float(w.text())
                else:
                    values[spec.key] = w.text().strip()
        return values

    def _on_edit_changed(self, *_args) -> None:
        """字段一改就把计算列刷出来（金额 = kg × 单价、结存 = 期初 − 出栏 …）。"""
        if not self._editors:
            return
        values = self._collect()
        patch = self.recalc(values, getattr(self, "_base", None)) or {}
        for key, val in patch.items():
            w = self._editors.get(key)
            spec = next((f for f in self.FIELDS if f.key == key), None)
            if w is None or spec is None:
                continue
            if isinstance(w, QLineEdit) and not isinstance(w, QComboBox):
                w.blockSignals(True)
                if spec.kind in ("num", "money", "int", "computed"):
                    decimals = 0 if spec.kind == "int" else spec.decimals
                    w.setText(f"{float(val or 0):.{decimals}f}")
                else:
                    w.setText("" if val is None else str(val))
                w.blockSignals(False)
            elif isinstance(w, DateEdit):
                # 日期列也要能自动带（约定收款日 = 销售日期 + 账期）
                d = QDate.fromString(str(val or ""), "yyyy-MM-dd")
                w.blockSignals(True)
                if d.isValid():
                    w.setDate(d)
                elif spec.kind == "date_opt":
                    w.setDate(QDate(2000, 1, 1))
                w.blockSignals(False)
            elif isinstance(w, QComboBox) and spec.kind == "combo":
                # 下拉列也能被带出来（客户一选，结算方式跟名录走）
                text = "" if val is None else str(val)
                if w.currentText() != text:
                    w.blockSignals(True)
                    w.setCurrentText(text)
                    w.blockSignals(False)

    # ---------------------------------------------------------- 离开即存
    def eventFilter(self, obj, event) -> bool:      # noqa: N802
        et = event.type()
        if et == QEvent.MouseButtonPress and self._editors and self._app_hooked:
            # 点在任何“不是本行编辑框”的地方——别的行、序号、操作列、卡片空白、工具栏——
            # 都算离开本行。只盯焦点不够：序号/操作列这些控件不吃焦点，点了也不会触发 FocusOut。
            w = obj if isinstance(obj, QWidget) else None
            if w is not None and not self._inside_editors(w):
                token = self._edit_token
                QTimer.singleShot(0, lambda t=token: self._on_focus_left(t))
        elif et == QEvent.FocusOut:
            if obj in self._editors.values():
                token = self._edit_token
                QTimer.singleShot(0, lambda t=token: self._on_focus_left(t))
        elif et == QEvent.KeyPress and self._editors and obj in self._editors.values():
            key = event.key()
            if (key in (Qt.Key_Return, Qt.Key_Enter)
                    and isinstance(obj, QLineEdit) and not isinstance(obj, QComboBox)):
                # 纯文本 / 数字框里回车 = 收工；下拉框的回车留给它自己选词
                QTimer.singleShot(0, self._commit_edit)
                return True
            if key == Qt.Key_Escape:
                QTimer.singleShot(0, self.cancel_edit)
                return True
        return super().eventFilter(obj, event)

    def _on_focus_left(self, token: int, tries: int = 0) -> None:
        """离开本行 → 落库。点其他任何位置（换行、换页、空白、工具栏）都走这里。"""
        if token != self._edit_token or not self._editors or self._saving:
            return
        if QApplication.activePopupWidget() is not None:     # 下拉 / 日历还开着，等它关
            if tries < 25:
                QTimer.singleShot(150, lambda: self._on_focus_left(token, tries + 1))
            return
        fw = QApplication.focusWidget()
        if fw is not None and any(fw is w or w.isAncestorOf(fw) for w in self._editors.values()):
            return                                          # 焦点还在本行，别急着存
        self._settle_edit()

    def _inside_editors(self, w: QWidget) -> bool:
        return any(w is e or e.isAncestorOf(w) for e in self._editors.values())

    def _is_blank_draft(self) -> bool:
        if self._draft is None:
            return False
        cur = self._collect()
        blank = self._draft or {}
        for spec in self.FIELDS:
            if spec.kind in ("computed", "ro_text", "batch", "store", "date", "date_opt"):
                continue
            val = cur.get(spec.key)
            if spec.kind in ("num", "money", "int"):
                if abs(float(val or 0)) > 1e-9:
                    return False
            else:
                text = str(val or "").strip()
                if text and text != str(blank.get(spec.key) or "").strip():
                    return False
        return True

    def _drop_draft(self) -> None:
        self._draft = None
        self._draft_open = False
        self._edit_id = None
        self._editors = {}
        self._edit_token += 1
        self._render()

    def _park_draft(self, reason: str) -> None:
        """没填完的草稿：把已填的值留在黄行里，退出编辑态，好让别的操作照常做。"""
        values = self._collect()
        merged = dict(self._draft or {})
        merged.update(values)
        self._draft = merged
        self._draft_open = False
        self._editors = {}
        self._edit_token += 1
        self._render()
        self.notify(f"这行还没填完（{reason}），已原样放着——双击它可以接着填", "warn")

    def _revert_edit(self, reason: str) -> None:
        """老行改出了不合法内容：还原成库里的样子，别拦着后面的操作。"""
        self._edit_id = None
        self._editors = {}
        self._edit_token += 1
        self._render()
        self.notify(f"改动没存（{reason}），已还原成原来的内容", "warn")

    def _settle_edit(self) -> bool:
        """离开本行前把编辑收掉：能存就存，存不了就搁着（草稿）或还原（老行），绝不卡住后面的操作。"""
        if not self._editors or self._saving:
            return True
        if self._draft is not None and self._is_blank_draft():
            self._drop_draft()
            return True
        if self._commit_edit(silent=True, warn=False):
            return True
        err = self.validate(self._collect()) or "本行还没填完"
        if self._draft is not None:
            self._park_draft(err)
        else:
            self._revert_edit(err)
        return True

    # ---------------------------------------------------------- 交互
    def _begin_edit(self, row: int) -> None:
        rec = self._view[row] if 0 <= row < len(self._view) else None
        if rec is None:
            return
        if rec is self._draft:                      # 搁着的草稿：双击接着填
            self._settle_edit()
            self._draft_open = True
            self._edit_id = None
            self._render()
            pos = self._editing_row()
            if pos is not None:
                self.table.selectRow(pos)
            self._focus_first()
            return
        if not rec.get("id"):
            return
        rid = int(rec.get("id") or 0)
        if self._editors:
            if self._editing_row() == row:
                return
            self._settle_edit()
            row = next((i for i, r in enumerate(self._view)
                        if r and int(r.get("id") or 0) == rid), row)
        self._edit_id = rid
        self._render()
        self.table.selectRow(row)

    def on_edit_row(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self._begin_edit(row)

    def on_new(self) -> None:
        """筛选条上的「＋ 新增」：插在最上面。"""
        self.on_insert_at(-1)

    def on_insert_at(self, view_row: int) -> None:
        """序号列的「＋」：在点中的这一行**下面**插一行空白。"""
        self._settle_edit()
        if self._draft is not None:
            # 同一时间只开一张新单：手上那张没填完的草稿接着填，别悄悄丢掉
            self._draft_open = True
            self._edit_id = None
            self._editors = {}
            self._render()
            pos = self._editing_row()
            if pos is not None:
                self.table.selectRow(pos)
            self._focus_first()
            self.notify("先把手上这张没保存的单据填完（同一时间只开一张）")
            return
        feed_row = view_row
        self._draft, self._draft_pos = self.blank_at(feed_row)
        self._draft_open = True
        self._edit_id = None
        self._editors = {}
        self._render()
        row = self._editing_row()
        if row is not None:
            self.table.selectRow(row)
            anchor = self.table.item(row, 1)
            if anchor is not None:
                self.table.scrollToItem(anchor)
        self._focus_first()

    def _focus_first(self) -> None:
        """新开的草稿把光标放到最该先填的那一格。"""
        w = (self._editors.get("date") or self._editors.get("receipt_date")
             or next(iter(self._editors.values()), None))
        if isinstance(w, QWidget):
            w.setFocus()

    def cancel_edit(self) -> None:
        # 草稿被搁成黄行时已经没有编辑框了（_editing_row 为 None），但它仍然是一条没落库的草稿：
        # 按 Esc / 点「放弃」就该连它一起丢掉，不能只认编辑态。
        if self._editing_row() is None and self._draft is None:
            return
        was_new = self._draft is not None
        self._draft = None
        self._draft_open = False
        self._edit_id = None
        self._editors = {}
        self._edit_token += 1
        self._render()
        self.notify("已丢弃这张未保存的单据" if was_new else "已放弃本次改动，恢复成编辑前的内容")

    def save_row(self) -> None:
        """显式保存（回车 / 外部调用）；平时靠离开本行自动落库。"""
        self._commit_edit(silent=False)

    def _commit_edit(self, silent: bool = False, warn: bool = True) -> bool:
        if not self._editors or self._saving:
            return True
        if self._draft is not None and self._is_blank_draft():
            self._drop_draft()                      # 空白草稿：直接收掉，不弹校验
            return True
        values = self._collect()
        err = self.validate(values)
        if err:
            if warn:
                self.notify(err, "warn")
            return False
        rid = self._edit_id if self._draft is None else None
        data = dict(values)
        data.pop("computed", None)
        before = dict(self._base) if rid else None
        self._saving = True
        try:
            saved = self.save_record(data, rid)
        except Exception as exc:                    # 落库失败别把行锁死
            self.notify(f"保存失败：{exc}", "warn")
            return False
        finally:
            self._saving = False
        if rid:
            self._push({"kind": "update", "id": int(rid), "before": before or {},
                        "after": dict(data), "label": "修改本行"})
        else:
            self._push({"kind": "insert", "id": self.record_id(saved, data),
                        "before": None, "after": dict(data), "label": "新增本行"})
        self._draft = None
        self._draft_open = False
        self._edit_id = None
        self._editors = {}
        self._edit_token += 1
        self._fill_filters()
        self.refresh()
        self.ctx.changed()
        self.history_changed.emit()
        # 没有「保存」按钮，所以每次落库都要给一句回执，不然不知道自己存上了没有
        self.notify("已新增 1 行" if rid is None else
                    ("已保存（离开本行自动存）" if silent else "已保存"))
        return True

    def delete_row(self, row: int) -> None:
        rec = self._view[row] if 0 <= row < len(self._view) else None
        if rec is None:
            return
        if rec is self._draft:                      # 草稿行（不管开没开着编辑）
            self._drop_draft()
            self.notify("已丢弃未保存的单据")
            return
        rid = int(rec.get("id") or 0)
        if not rid:
            return
        if self._editors:                           # 手上还有没存的：先收掉（可能换行号）
            self._settle_edit()
            row = next((i for i, r in enumerate(self._view)
                        if r and int(r.get("id") or 0) == rid), -1)
            if row < 0:
                return
            rec = self._view[row]
        name = self.row_label(rec)
        if not confirm(self, "删除确认", f"确定删除这条{self.ROW_NAME}吗？\n{name}"):
            return
        self._apply_delete(rec)

    def _apply_delete(self, rec: dict, push: bool = True) -> None:
        rid = int(rec.get("id") or 0)
        self.delete_record(rid)
        if push:
            self._push({"kind": "delete", "id": rid, "before": dict(rec),
                        "after": None, "label": "删除本行"})
        self._edit_id = None
        self._editors = {}
        self._edit_token += 1
        self.refresh()
        self.ctx.changed()
        self.history_changed.emit()
        self.notify("已删除，点顶部「撤消」可以捡回来")

    def _row_menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= len(self._view) or self._view[row] is None:
            return
        rec = self._view[row]
        rid = int(rec.get("id") or 0) if rec is not self._draft else 0
        self._settle_edit()
        row = next((i for i, r in enumerate(self._view)
                    if r and int(r.get("id") or 0) == rid), row) if rid else row
        if not (0 <= row < len(self._view)) or self._view[row] is None:
            return
        self.table.selectRow(row)
        menu = QMenu(self)
        act_edit = menu.addAction(icons.edit_icon(), "编辑本行")
        act_del = menu.addAction(icons.trash_icon(), "删除本行")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is act_edit:
            self._begin_edit(row)
        elif chosen is act_del:
            self.delete_row(row)

    # ---------------------------------------------------------- 撤消 / 恢复
    def _push(self, cmd: dict) -> None:
        self._history.append(cmd)
        del self._history[:-HISTORY_MAX]
        self._future.clear()

    def undo(self) -> None:
        if not self._history:
            self.notify("没有可撤消的操作", "warn")
            return
        self._settle_edit()
        cmd = self._history.pop()
        try:
            self._replay(cmd, forward=False)
        except Exception as exc:
            self._history.append(cmd)
            self.notify(f"撤消失败：{exc}", "warn")
            return
        self._future.append(cmd)
        self._after_history(f"已撤消：{cmd['label']}")

    def redo(self) -> None:
        if not self._future:
            self.notify("没有可恢复的操作", "warn")
            return
        self._settle_edit()
        cmd = self._future.pop()
        try:
            self._replay(cmd, forward=True)
        except Exception as exc:
            self._future.append(cmd)
            self.notify(f"恢复失败：{exc}", "warn")
            return
        self._history.append(cmd)
        self._after_history(f"已恢复：{cmd['label']}")

    def _replay(self, cmd: dict, forward: bool) -> None:
        """把一条历史命令正向重放或反向回放。"""
        kind = cmd.get("kind")
        if kind == "update":
            self.save_record(dict(cmd["after"] if forward else cmd["before"]), int(cmd["id"]))
        elif kind == "insert":
            if forward:
                saved = self.save_record(dict(cmd["after"]), None)
                cmd["id"] = self.record_id(saved, cmd["after"])
            else:
                self.delete_record(int(cmd["id"]))
        elif kind == "delete":
            if forward:
                self.delete_record(int(cmd["id"]))
            else:
                saved = self.save_record(dict(cmd["before"]), None)
                cmd["id"] = self.record_id(saved, cmd["before"])

    def _after_history(self, message: str) -> None:
        self._edit_id = None
        self._editors = {}
        self._edit_token += 1
        self._fill_filters()
        self.refresh()
        self.ctx.changed()
        self.history_changed.emit()
        self.notify(message)

    # ---------------------------------------------------------- 排序 / 筛选 / 界面级按钮
    def _sort_spec(self) -> FieldSpec | None:
        if self._sort_col is None:
            return None
        idx = int(self._sort_col) - 1
        return self.FIELDS[idx] if 0 <= idx < len(self.FIELDS) else None

    def _row_passes(self, rec: dict) -> bool:
        for col, allowed in self._col_filters.items():
            idx = int(col) - 1
            if not (0 <= idx < len(self.FIELDS)) or not allowed:
                continue
            if self._cell(rec, self.FIELDS[idx]) not in allowed:
                return False
        return True

    def _prepare(self, rows: list[dict]) -> list[dict]:
        """列筛选 + 列排序：只影响“怎么显示”，不动库里的数。"""
        out = [r for r in rows if self._row_passes(r)]
        spec = self._sort_spec()
        if spec is not None:
            numeric = spec.kind in ("num", "money", "int", "computed")
            if numeric:
                out.sort(key=lambda r: _to_float(r.get(spec.key)), reverse=self._sort_desc)
            else:
                out.sort(key=lambda r: self._cell(r, spec), reverse=self._sort_desc)
        return out

    def _column_menu(self, section: int, pos) -> None:
        """表头小三角：排序 + 只看某个值（日期、批次最常用）。"""
        self._settle_edit()                 # 重排会重建表格，先把编辑收掉
        idx = int(section) - 1
        if not (0 <= idx < len(self.FIELDS)):
            return
        spec = self.FIELDS[idx]
        menu = QMenu(self)
        name = spec.label.replace("\n", "")
        act_asc = menu.addAction(f"按「{name}」升序")
        act_desc = menu.addAction(f"按「{name}」降序")
        act_clear = menu.addAction("取消排序")
        act_clear.setEnabled(self._sort_col == section)
        menu.addSeparator()
        sub = menu.addMenu("只显示一个值")
        values = sorted({self._cell(r, spec) for r in self._rows})
        picked: dict = {}
        if len(values) > 60:
            a = sub.addAction(f"值太多（{len(values)} 个），请先用上方期间 / 批次筛选")
            a.setEnabled(False)
        else:
            current = self._col_filters.get(section)
            for v in values:
                a = sub.addAction(v or "（空）")
                a.setCheckable(True)
                a.setChecked(bool(current) and v in current)
                picked[a] = v
        sub.addSeparator()
        act_all = sub.addAction("全部显示")
        act_all.setEnabled(section in self._col_filters)

        chosen = menu.exec(pos)
        if chosen is None:
            return
        if chosen is act_asc:
            self._sort_col, self._sort_desc = int(section), False
        elif chosen is act_desc:
            self._sort_col, self._sort_desc = int(section), True
        elif chosen is act_clear:
            self._sort_col, self._sort_desc = None, False
        elif chosen is act_all:
            self._col_filters.pop(section, None)
        elif chosen in picked:
            val = picked[chosen]
            if self._col_filters.get(section) == {val}:
                self._col_filters.pop(section, None)      # 再点一次＝取消这一列的筛选
            else:
                self._col_filters[section] = {val}
        else:
            return
        self._rows = self._prepare(self.fetch())
        self._render()

    # ---------------------------------------------------------- 界面级 保存 / 撤消 / 恢复
    def _hook_app(self, on: bool) -> None:
        """编辑期间盯全应用（而不只是本页）的鼠标按下：点哪儿算“离开本行”都抓得住。"""
        app = QApplication.instance()
        if app is None:
            return
        if on and not self._app_hooked:
            app.installEventFilter(self)
            self._app_hooked = True
        elif not on and self._app_hooked:
            app.removeEventFilter(self)
            self._app_hooked = False

    def has_pending(self) -> bool:
        return bool(self._editors)

    def save_pending(self) -> None:
        if not self._editors:
            self.notify("没有待保存的改动（改完点别处就已经存了）")
            return
        if self._commit_edit(silent=False):
            self.history_changed.emit()

    def can_undo(self) -> bool:
        return bool(self._history)

    def can_redo(self) -> bool:
        return bool(self._future)

    # ---------------------------------------------------------- 导出
    def on_export(self) -> None:
        self._settle_edit()
        if not self._rows:
            self.notify("当前筛选没有可导出的数据", "warn")
            return
        config.ensure_dirs()
        stem = f"{self.EXPORT_STEM}-{self.d1}_{self.d2}"
        path = Path(config.EXPORT_DIR) / f"{stem}.xlsx"
        xl_export.export_module(path, self.export_module_key(), self.ctx.conn,
                                self.d1, self.d2, store_id=self.store_id,
                                batch_id=self.batch_id)
        self.notify(f"已导出：{path.name}")
        info(self, "导出完成", f"已导出到：\n{path}")
