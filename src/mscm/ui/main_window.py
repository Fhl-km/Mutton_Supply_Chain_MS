"""主窗口：侧边导航 + 页签条 + 页面抬头 + 页面容器 + 状态栏。

导航按业务分四块：
    经营分析   概览 / 数据校验
    档案       商品档案 / 门店档案 / 客户名录（档案决定下拉与门店节点）
    活羊采购 & 屠宰  活羊入库&结余 → 暂养出入库 → 养殖 → 屠宰 → 屠宰出库（一条链路）
    门店管理   关一店 → 损益报表 / 进销存台账 / 入库 / 销售 / 结存盘点 / 应收
                （门店节点由档案驱动，加一家店就多一个节点）
"""

from __future__ import annotations

from PySide6.QtCore import QDate, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from mscm import config
from mscm.core import repo
from mscm.core.db import JsonStore
from mscm.core.models import today
from mscm.ui import icons, theme, update_ui
from mscm.ui.context import AppContext
from mscm.ui.nav import (
    NavBrand, NavFooter, NavGroupItem, NavLeafButton, NavSection, NavStoreItem,
)
from mscm.ui.pages.archive import ProductPage, StorePage
from mscm.ui.pages.batches import BatchPage
from mscm.ui.pages.breeding import BreedingPage
from mscm.ui.pages.check import CheckPage
from mscm.ui.pages.customers import CustomerPage
from mscm.ui.pages.dashboard import DashboardPage
from mscm.ui.pages.feed import FeedPage
from mscm.ui.pages.payable import PayablePage
from mscm.ui.pages.receivable import SlaughterReceivablePage, StoreReceivablePage
from mscm.ui.pages.settings import SettingsPage
from mscm.ui.pages.slaughter import SlaughterPage
from mscm.ui.pages.slaughter_out import SlaughterOutPage
from mscm.ui.pages.store_ledgers import StoreInPage, StoreSalePage, StoreStockPage
from mscm.ui.pages.store_reports import StoreLedgerPage, StorePnlPage
from mscm.ui.tabbar import PageTabBar
from mscm.ui.widgets import button, date_edit, help_button, label

NAV_WIDTH = 236
HEAD_HEIGHT = 38
PAGE_HEAD_HEIGHT = 38

HOME_KEY = "dashboard"

# 门店下固定的台账（顺序即导航顺序，也是用户口径）
STORE_REPORTS: tuple[tuple[str, str], ...] = (
    ("pnl", "损益报表"),
    ("ledger", "进销存台账"),
    ("in", "入库台账"),
    ("sale", "销售台账"),
    ("stock", "结存/盘点台账"),
    ("ar", "应收款项"),
)
STORE_CLASSES = {"pnl": StorePnlPage, "ledger": StoreLedgerPage,
                 "in": StoreInPage, "sale": StoreSalePage, "stock": StoreStockPage,
                 "ar": StoreReceivablePage}

# 一级直达页
LEAF_PAGES = {
    "dashboard": (DashboardPage, "经营概览", "暂养结存、门店库存、本月屠宰与销售一屏看完"),
    "check": (CheckPage, "数据校验", "七张台账之间的勾稽逐条核：结存、出栏、出肉率、库存、盘点差异"),

    "products": (ProductPage, "商品档案", "白条 / 分割品 / 副产品：屠宰产出与门店商品的名称底表"),
    "stores": (StorePage, "门店档案",
                  "每加一家门店，左侧「门店管理」下就多一个节点（损益 / 进销存 / 入库 / 销售 / 结存盘点 / 应收）"),
    "customers": (CustomerPage, "客户名录",
                  "客户底表：归属 / 名称 / 信用代码 / 联系人 / 地址 / 结算方式 / 首次供货 / 对接人"),
}

PURCHASE_KEYS = (
    ("batches", "活羊入库&结余"),
    ("feed", "屠宰场暂养出入库台账"),
    ("breeding", "养殖记录"),
    ("slaughter", "屠宰记录"),
    ("slaughter_out", "屠宰出库明细"),
    ("receivable", "应收款项 · 屠宰销售"),
    ("payable", "应付款项 · 活羊采购与付款"),
)
PURCHASE_CLASSES = {
    "batches": BatchPage,
    "feed": FeedPage,
    "breeding": BreedingPage,
    "slaughter": SlaughterPage,
    "slaughter_out": SlaughterOutPage,
    "receivable": SlaughterReceivablePage,
    "payable": PayablePage,
}

EXTRA_PAGES = {
    "settings": (SettingsPage, "系统设置", "数据文件、备份、整套台账导出与账套维护"),
}


def _make_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(theme.NAVY))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(0, 0, 64, 64, 12, 12)
    p.setPen(QColor(theme.GOLD))
    f = QFont("Microsoft YaHei UI")
    f.setPixelSize(32)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "羊")
    p.end()
    return QIcon(pm)


class MainWindow(QMainWindow):
    def __init__(self, conn: JsonStore) -> None:
        super().__init__()
        self.conn = conn
        self.ctx = AppContext(conn, repo.get_setting(conn, "biz_date", today()), host=self)
        self.setWindowTitle(f"{config.APP_NAME}  v{config.APP_VERSION}")
        self.setWindowIcon(_make_icon())
        self.resize(1560, 940)
        self.setMinimumSize(1180, 720)

        self.pages: dict[str, QWidget] = {}
        self.store_items: dict[int, NavStoreItem] = {}
        self.leaf_buttons: dict[str, NavLeafButton] = {}
        self.current_key = ""

        central = QWidget()
        central.setObjectName("Content")
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_sidebar())
        lay.addWidget(self._build_content(), 1)
        self.setCentralWidget(central)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")

        self.ctx.data_changed.connect(self._sync_store_nav)
        self.show_page(HOME_KEY)

    # ---------------------------------------------------------- 侧边栏
    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(NAV_WIDTH)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(NavBrand())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;}")
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 2, 0, 8)
        body_lay.setSpacing(0)

        # 经营分析
        body_lay.addWidget(NavSection("经营分析"))
        self._add_leaf(body_lay, "dashboard")
        self._add_leaf(body_lay, "check")

        # 档案
        body_lay.addWidget(NavSection("档案"))
        self._add_leaf(body_lay, "products")
        self._add_leaf(body_lay, "stores")
        self._add_leaf(body_lay, "customers")

        # 活羊采购 & 屠宰
        body_lay.addWidget(NavSection("业务台账"))
        self.purchase_group = NavGroupItem(
            "活羊采购 & 屠宰", PURCHASE_KEYS,
            on_pick=self.show_page, on_toggle=self._toggle_purchase,
            tip="入库批次 → 暂养出入库 → 养殖 → 屠宰 → 屠宰出库 → 应收（屠宰销售）/ 应付（活羊采购）")
        body_lay.addWidget(self.purchase_group)

        # 门店管理：标题折叠整块门店；门店节点由「门店档案」驱动
        self.store_group = NavGroupItem(
            "门店管理", (), on_pick=self.show_page, on_toggle=self._toggle_store_group,
            tip="每家门店挂六项：损益报表 / 进销存台账 / 入库台账 / 销售台账 / 结存/盘点台账 / 应收款项（含逐笔收款）",
            header_name="NavRoot")
        body_lay.addWidget(self.store_group)
        self.store_box = QWidget()
        self.store_box.setStyleSheet("background:transparent;")
        self.store_box_lay = QVBoxLayout(self.store_box)
        self.store_box_lay.setContentsMargins(0, 0, 0, 0)
        self.store_box_lay.setSpacing(0)
        self.store_group.add_body_widget(self.store_box)
        self._rebuild_store_nav()
        self.store_group.set_open(True)
        self.purchase_group.set_open(True)

        body_lay.addStretch(1)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)
        lay.addWidget(NavFooter())
        return side

    def _add_leaf(self, lay: QVBoxLayout, key: str) -> None:
        title = LEAF_PAGES[key][1]
        btn = NavLeafButton(title)
        btn.setToolTip(LEAF_PAGES[key][2])
        btn.clicked.connect(lambda _c=False, k=key: self.show_page(k))
        lay.addWidget(btn)
        self.leaf_buttons[key] = btn

    # ---------------------------------------------------------- 门店导航
    def _rebuild_store_nav(self) -> None:
        lay = self.store_box_lay
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.store_items.clear()

        reports = STORE_REPORTS
        for st in repo.list_stores(self.conn):
            sid = int(st.get("id") or 0)
            node = NavStoreItem(sid, str(st.get("name") or f"门店{sid}"), reports,
                                on_pick=self.open_store, on_toggle=self._toggle_store)
            lay.addWidget(node)
            self.store_items[sid] = node
        # 默认展开第一家，省得进来还要点一次
        if self.store_items and not any(x.opened for x in self.store_items.values()):
            first = next(iter(self.store_items.values()))
            first.set_open(True)
        self.store_group.header.setToolTip(
            f"门店管理：{len(self.store_items)} 家门店 × "
            f"损益 / 进销存 / 入库 / 销售 / 结存盘点 / 应收（点标题收起 / 展开）")

    def _sync_store_nav(self) -> None:
        """门店增删改后重建节点（名称可能变了）。"""
        wanted = [(int(s.get("id")), str(s.get("name"))) for s in repo.list_stores(self.conn)]
        if wanted == [(sid, item.heading) for sid, item in self.store_items.items()]:
            return
        self._rebuild_store_nav()
        self._prune_store_pages()
        self._sync_nav(self.current_key)

    def _prune_store_pages(self) -> None:
        alive = set(self.store_items)
        dropped = False
        for key in list(self.pages):
            parsed = self._parse_key(key)
            if parsed is None or parsed[0] in alive:
                continue
            page = self.pages.pop(key)
            self.stack.removeWidget(page)
            page.deleteLater()
            pos = self.tabbar.find_key(key)
            if pos >= 0:
                self.tabbar.remove_page(pos)
            dropped = True
        if dropped and self.current_key not in self.pages:
            self.show_page(HOME_KEY)

    def _toggle_store_group(self, item: NavGroupItem) -> None:
        item.set_open(not item.opened)
        self._sync_nav(self.current_key)

    def _toggle_purchase(self, item: NavGroupItem) -> None:
        item.set_open(not item.opened)

    def _toggle_store(self, item: NavStoreItem) -> None:
        """手风琴：展开一家，收起其余。"""
        if item.opened:
            item.set_open(False)
            return
        for other in self.store_items.values():
            other.set_open(other is item)

    # ---------------------------------------------------------- 内容区
    def _build_content(self) -> QWidget:
        wrap = QWidget()
        wrap.setObjectName("Content")
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_topbar())
        lay.addWidget(self._build_page_head())
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        return wrap

    def _build_topbar(self) -> QWidget:
        head = QWidget()
        head.setObjectName("TopBar")
        head.setFixedHeight(HEAD_HEIGHT)
        lay = QHBoxLayout(head)
        lay.setContentsMargins(8, 3, 12, 3)
        lay.setSpacing(8)
        self.tabbar = PageTabBar()
        self.tabbar.pageActivated.connect(self._on_tab_activated)
        self.tabbar.closePageRequested.connect(self._close_tab)
        lay.addWidget(self.tabbar, 1)
        lay.addWidget(button("刷新", "", self._refresh_current, tip="重算当前页（F5）"))
        lay.addWidget(self._more_button())
        # 只给「保存」留快捷键：Ctrl+Z 在单元格里要留给文字撤销，不能抢
        QShortcut(QKeySequence.Save, self).activated.connect(self._save_current)
        return head

    def _quick_button(self, icon, tip: str, slot) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("QuickBtn")
        btn.setIcon(icon)
        btn.setIconSize(QSize(17, 17))
        btn.setFixedSize(26, 26)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(tip)
        btn.clicked.connect(slot)
        return btn

    def _more_button(self) -> QWidget:
        btn = button("更多", "", None)
        btn.setToolTip("系统设置：数据文件、备份、整套台账导出、账套维护")
        menu = QMenu(btn)
        for key, (cls, title, sub) in EXTRA_PAGES.items():
            act = QAction(title, menu)
            act.triggered.connect(lambda _=False, k=key: self.show_page(k))
            menu.addAction(act)
        btn.setMenu(menu)
        return btn

    def _build_page_head(self) -> QWidget:
        head = QWidget()
        head.setObjectName("PageHead")
        head.setFixedHeight(PAGE_HEAD_HEIGHT)
        lay = QHBoxLayout(head)
        lay.setContentsMargins(16, 4, 14, 4)
        lay.setSpacing(8)

        self.head_title = QLabel("经营概览")
        self.head_title.setObjectName("PageHeadTitle")
        lay.addWidget(self.head_title)

        self.head_help = help_button(self._toggle_help)
        self.head_help.setObjectName("PageHelp")
        self.head_help.setFixedHeight(23)
        self.head_help.setMinimumWidth(72)
        self.head_help.setStyleSheet(
            f"QPushButton#PageHelp{{background:#F3F7FD;border:1px solid #CBD9EA;border-radius:11px;"
            f"color:{theme.MUTED};font-size:12px;padding:0 10px;}}"
            f"QPushButton#PageHelp:hover{{background:#E9F1FC;border-color:#A9C2E0;color:{theme.NAVY};}}"
            f"QPushButton#PageHelp:checked{{background:#E3EDFA;border-color:#A9C2E0;color:{theme.NAVY};}}")
        self.head_help.hide()
        lay.addWidget(self.head_help)

        # 当前这张台账的 保存 / 撤消 / 恢复（照 WPS 的小图标）
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedHeight(18)
        sep.setStyleSheet(f"color:#D5DEEC;background:#D5DEEC;max-width:1px;")
        lay.addWidget(sep)
        self.btn_save = self._quick_button(icons.save_icon(),
                                           "保存：把正在编辑的这一行立刻存下来（Ctrl+S）", self._save_current)
        self.btn_undo = self._quick_button(icons.undo_icon(),
                                           "撤消：回到上一步（删除、改行、新增都记着）", self._undo_current)
        self.btn_redo = self._quick_button(icons.redo_icon(),
                                           "恢复：把撤消掉的动作再做一遍", self._redo_current)
        self.quick_group = [sep, self.btn_save, self.btn_undo, self.btn_redo]
        for btn in (self.btn_save, self.btn_undo, self.btn_redo):
            btn.setFixedHeight(24)
            lay.addWidget(btn)
        lay.addStretch(1)

        lay.addWidget(label("业务日期", "Muted"))
        self.date_edit = date_edit(self.ctx.biz_date, width=124)
        self.date_edit.dateChanged.connect(self._on_date_changed)
        lay.addWidget(self.date_edit)
        lay.addWidget(button("今天", "", self._goto_today))
        return head

    def _toggle_help(self) -> None:
        page = self.pages.get(self.current_key)
        on = self.head_help.isChecked()
        if page is None or not hasattr(page, "toggle_help"):
            self.head_help.setChecked(False)
            self.head_help.setText("填写说明")
            return
        page.toggle_help(on)
        self.head_help.setText("收起说明" if on else "填写说明")

    def _sync_head_help(self, prev: QWidget | None, page: QWidget | None) -> None:
        if prev is not None and prev is not page and hasattr(prev, "toggle_help"):
            prev.toggle_help(False)
        self.head_help.setChecked(False)
        self.head_help.setText("填写说明")
        ok = bool(page is not None and getattr(page, "has_help", None) and page.has_help())
        if ok and page is not prev:
            page.toggle_help(False)
        self.head_help.setVisible(ok)

    # ---------------------------------------------------------- 页签
    def _tab_text(self, key: str) -> tuple[str, str]:
        """页签比页面抬头更挤：全角间隔换成半角，省两个字宽。"""
        title, sub = self._page_text(key)
        short = title.replace("　·　", "·")
        return short, f"{title}\n{sub}" if sub else title

    def _sync_tab(self, key: str) -> None:
        if self.tabbar.find_key(key) < 0:
            text, tip = self._tab_text(key)
            self.tabbar.add_page(key, text, closable=key != HOME_KEY)
        self.tabbar.select_page(key)
        pos = self.tabbar.find_key(key)
        if pos >= 0:
            text, tip = self._tab_text(key)
            self.tabbar.set_page_text(pos, text, tip)

    def _on_tab_activated(self, key: str) -> None:
        if key and key != self.current_key and self._known_key(key):
            self.show_page(key)

    def _close_tab(self, key: str) -> None:
        if key == HOME_KEY:
            return
        pos = self.tabbar.find_key(key)
        if pos < 0:
            return
        was_current = key == self.current_key
        self.tabbar.remove_page(pos)
        if was_current:
            nxt = min(pos, self.tabbar.count() - 1)
            self.show_page(self.tabbar.key_at(nxt) if nxt >= 0 else HOME_KEY)

    # ---------------------------------------------------------- 页面工厂
    def _store_key(self, store_id: int, kind: str) -> str:
        return f"store-{int(store_id)}-{kind}"

    def _parse_key(self, key: str) -> tuple[int, str] | None:
        if not key.startswith("store-"):
            return None
        parts = key.split("-", 2)
        if len(parts) != 3:
            return None
        try:
            return int(parts[1]), parts[2]
        except ValueError:
            return None

    def _known_key(self, key: str) -> bool:
        return bool(self._parse_key(key)) or key in LEAF_PAGES or key in PURCHASE_CLASSES \
            or key in EXTRA_PAGES

    def _make_page(self, key: str) -> QWidget:
        parsed = self._parse_key(key)
        if parsed is not None:
            sid, kind = parsed
            cls = STORE_CLASSES.get(kind)
            if cls is None:
                raise KeyError(f"未定义的门店台账：{kind}")
            return cls(self.ctx, store_id=sid)
        if key in PURCHASE_CLASSES:
            return PURCHASE_CLASSES[key](self.ctx)
        if key in LEAF_PAGES:
            return LEAF_PAGES[key][0](self.ctx)
        if key in EXTRA_PAGES:
            return EXTRA_PAGES[key][0](self.ctx)
        raise KeyError(f"未定义的页面：{key}")

    def _page_text(self, key: str) -> tuple[str, str]:
        parsed = self._parse_key(key)
        if parsed is not None:
            sid, kind = parsed
            name = repo.store_name(self.conn, sid) or "门店"
            title = dict(STORE_REPORTS).get(kind, "")
            return f"{name}　·　{title}", self._store_sub(kind)
        if key in PURCHASE_CLASSES:
            return dict(PURCHASE_KEYS)[key], _PURCHASE_SUBS.get(key, "")
        if key in LEAF_PAGES:
            return LEAF_PAGES[key][1], LEAF_PAGES[key][2]
        if key in EXTRA_PAGES:
            return EXTRA_PAGES[key][1], EXTRA_PAGES[key][2]
        return key, ""

    @staticmethod
    def _store_sub(kind: str) -> str:
        return {
            "pnl": "按一级明细：产出 / 投入 / 损益 + 盈利指标（口径同门店日报表的损益报表）",
            "ledger": "上日结余 + 当日采购 − 当日结余 = 出库；销售 − 出库 = 损益",
            "in": "门店收货明细：来源 / 批次 / 商品 / kg / 单价 / 金额",
            "sale": "门店销售台账：应收 − 实收 = 挂账；按批次 × 商品轧差库存",
            "stock": "门店实盘：可按账面库存生成草稿，再改实盘数",
            "ar": "应收款（销售挂账自动提取，收款照银行流水逐笔登记）/ 未收款：未收 = 应收 − 已收",
        }.get(kind, "")

    def _page(self, key: str) -> QWidget:
        if key not in self.pages:
            page = self._make_page(key)
            self.pages[key] = page
            self.stack.addWidget(page)
            if hasattr(page, "history_changed"):
                page.history_changed.connect(self._sync_tool_buttons)
        return self.pages[key]

    def open_store(self, store_id: int, kind: str = "in") -> None:
        self.show_page(self._store_key(store_id, kind))

    def show_page(self, key: str) -> None:
        if not self._known_key(key):
            return
        prev = self.pages.get(self.current_key)
        page = self._page(key)
        self.stack.setCurrentWidget(page)
        self.current_key = key

        self._sync_nav(key)
        title, sub = self._page_text(key)
        self.head_title.setText(title)
        self._sync_head_help(prev, page)
        self._sync_tab(key)
        if sub:
            self.statusBar().showMessage(f"{title}　·　{sub}", 6000)
        if hasattr(page, "on_show"):
            page.on_show()
        self._sync_tool_buttons()

    def _sync_nav(self, key: str) -> None:
        # 直达页
        for k, btn in self.leaf_buttons.items():
            btn.setChecked(k == key)
        # 采购 & 屠宰组
        inside = key in PURCHASE_CLASSES
        self.purchase_group.set_current(inside)
        self.purchase_group.uncheck_all()
        if inside:
            self.purchase_group.set_open(True)
            btn = self.purchase_group.buttons.get(key)
            if btn is not None:
                btn.setChecked(True)
        # 门店组
        parsed = self._parse_key(key)
        self.store_group.set_current(parsed is not None)
        for node in self.store_items.values():
            node.set_current(False)
            node.uncheck_all()
        if parsed is not None:
            sid, kind = parsed
            node = self.store_items.get(sid)
            if node is not None:
                for other in self.store_items.values():
                    other.set_open(other is node)
                node.set_current(True)
                btn = node.buttons.get(kind)
                if btn is not None:
                    btn.setChecked(True)
            self.store_group.set_open(True)

    # ---------------------------------------------------------- 顶栏交互
    def _on_date_changed(self) -> None:
        day = self.date_edit.date().toString("yyyy-MM-dd")
        self.ctx.set_biz_date(day)
        self.statusBar().showMessage(f"业务日期：{day}", 4000)
        self._refresh_current()

    def _goto_today(self) -> None:
        self.date_edit.setDate(QDate.fromString(today(), "yyyy-MM-dd"))

    def _refresh_current(self) -> None:
        page = self.pages.get(self.current_key)
        if page is not None and hasattr(page, "refresh"):
            page.refresh()
        self._sync_tool_buttons()

    # ---------------------------------------------------------- 保存 / 撤消 / 恢复
    def _save_current(self) -> None:
        page = self.pages.get(self.current_key)
        if page is None or not hasattr(page, "save_pending"):
            self.statusBar().showMessage("这一页没有可保存的内容", 4000)
            return
        page.save_pending()
        self._sync_tool_buttons()

    def _undo_current(self) -> None:
        page = self.pages.get(self.current_key)
        if page is None or not getattr(page, "can_undo", lambda: False)():
            self.statusBar().showMessage("这一页没有可撤消的操作", 4000)
            return
        page.undo()
        self._sync_tool_buttons()

    def _redo_current(self) -> None:
        page = self.pages.get(self.current_key)
        if page is None or not getattr(page, "can_redo", lambda: False)():
            self.statusBar().showMessage("这一页没有可恢复的操作", 4000)
            return
        page.redo()
        self._sync_tool_buttons()

    def _sync_tool_buttons(self) -> None:
        page = self.pages.get(self.current_key)
        is_ledger = bool(page is not None and getattr(page, "LEDGER", False))
        for w in getattr(self, "quick_group", []):
            w.setVisible(is_ledger)          # 概览 / 校验页没有账可存，整组收起来
        if not is_ledger:
            return
        self.btn_save.setEnabled(bool(getattr(page, "has_pending", lambda: False)()))
        self.btn_save.setToolTip("保存：把正在编辑的这一行立刻存下来（Ctrl+S）" if self.btn_save.isEnabled()
                                 else "没有待保存的改动——改完点别处就已经自动存了")
        self.btn_undo.setEnabled(bool(getattr(page, "can_undo", lambda: False)()))
        self.btn_redo.setEnabled(bool(getattr(page, "can_redo", lambda: False)()))

    # ---------------------------------------------------------- Notifier
    def notify(self, message: str, level: str = "info") -> None:
        self.statusBar().showMessage(message, 8000)
        if level == "warn":
            self.statusBar().setStyleSheet(f"color:{theme.DANGER};")
            QTimer.singleShot(5000, lambda: self.statusBar().setStyleSheet(""))

    def refresh_all(self) -> None:
        self._refresh_current()
        stats = self.conn.stats()
        self.statusBar().showMessage(
            f"批次 {stats['batch']}　暂养 {stats['feed']} 行　养殖 {stats['breeding']} 行　"
            f"屠宰 {stats['slaughter']} 单　出库 {stats['slaughter_out']} 行　"
            f"门店入库 {stats['store_in']} / 销售 {stats['store_sale']} / 盘点 {stats['store_stock']} 行",
            6000)

    # ---------------------------------------------------------- 关闭
    def closeEvent(self, event) -> None:      # noqa: N802
        try:
            update_ui.stop_all()
            self.conn.commit()
        finally:
            super().closeEvent(event)


_PURCHASE_SUBS = {
    "batches": "采购入库与结余：入库日期在首列，入栏金额 / 当前存栏 / 暂养结存现算，行内直接改",
    "feed": "批次 × 日期：入库行直接取「活羊入库&结余」→ 出库（用途/只数/kg）→ 当日结存",
    "breeding": "期初存栏 − 出栏 = 期末存栏；投料按原材料逐笔登记",
    "slaughter": "一张屠宰单带多条产出明细：出肉率、领用成本、单位成本",
    "slaughter_out": "屠宰场销售与内部调拨；「门店调拨」可一键转成门店入库",
    "receivable": "屠宰场直接对外销售挂的账：按销售挂账自动提取应收，收款逐笔登记，未收自动算",
    "payable": "活羊采购与付款：按入库批次自动提取应付，付款逐笔登记，未付自动算、可出采购对账单",
}
