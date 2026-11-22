"""界面主题：浅色商务风，深蓝侧边栏 + 金色点缀。

性能提示：字体**不要**写进 QSS 通配规则（``* { font-family }``），否则每个控件
polish 时都要走一遍字体回退链，页面一多就是十几秒。字体统一走 ``app.setFont()``。
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette

NAVY = "#112A46"
NAVY_2 = "#1E4E79"
NAVY_LIGHT = "#2A6094"
GOLD = "#C8A44B"
BG = "#F4F6FA"
CARD = "#FFFFFF"
BORDER = "#E4E9F2"
TEXT = "#1F2937"
MUTED = "#6B7A90"
SUCCESS = "#0F8A5F"
DANGER = "#C0392B"
WARN = "#B7791F"
POSITIVE = "#C0392B"      # 会计习惯：收益红、亏损绿
NEGATIVE = "#0F8A5F"

ACCENTS = ("#1F3864", "#2A6094", "#C8A44B", "#0F8A5F", "#8A5A2B", "#6B7A90")

QSS = f"""
QMainWindow, QWidget#Content, QStackedWidget {{
    background: {BG};
}}

/* ---------- 侧边栏 ---------- */
QWidget#Sidebar {{ background: {NAVY}; }}
QLabel#BrandTitle {{ color: #FFFFFF; font-size: 16px; font-weight: bold; letter-spacing: 1px; }}
QLabel#BrandSub {{ color: #8FA7C2; font-size: 11px; }}
QLabel#BrandMark {{ color: {GOLD}; font-size: 19px; font-weight: bold; }}
QPushButton#NavButton {{
    background: transparent; border: none; border-left: 3px solid transparent;
    color: #C3D2E4; text-align: left; padding: 9px 16px 9px 18px; font-size: 13.5px;
}}
QPushButton#NavButton:hover {{ background: #17395C; color: #FFFFFF; }}
QPushButton#NavButton:checked {{
    background: {NAVY_2}; color: #FFFFFF; font-weight: bold; border-left: 3px solid {GOLD};
}}
QPushButton#NavRoot {{
    background: transparent; border: none; border-left: 3px solid {GOLD};
    color: #FFFFFF; text-align: left; padding: 11px 16px 8px 15px;
    font-size: 13.5px; font-weight: bold; letter-spacing: 1px;
}}
QPushButton#NavRoot:hover {{ background: #17395C; }}
QPushButton#NavRoot[cur="1"] {{ background: #0E2942; color: {GOLD}; }}
QPushButton#NavStore {{
    background: transparent; border: none; border-left: 3px solid transparent;
    color: #D3DFEE; text-align: left; padding: 7px 10px 7px 24px; font-size: 13px;
}}
QPushButton#NavStore:hover {{ background: #17395C; color: #FFFFFF; }}
QPushButton#NavStore[cur="1"] {{ color: {GOLD}; font-weight: bold; background: #10243D; }}
QPushButton#NavSub {{
    background: transparent; border: none; border-left: 3px solid transparent;
    color: #A6B8CE; text-align: left; padding: 6px 10px 6px 44px; font-size: 12.5px;
}}
QPushButton#NavSub:hover {{ background: #17395C; color: #FFFFFF; }}
QPushButton#NavSub:checked {{
    background: {NAVY_2}; color: #FFFFFF; font-weight: bold; border-left: 3px solid {GOLD};
}}
QLabel#NavSection {{ color: #5F7695; font-size: 10.5px; padding: 12px 18px 4px 18px; letter-spacing: 1px; }}
QWidget#SidebarFooter {{ background: #0D2138; }}
QLabel#SidebarHint {{ color: #7E95B2; font-size: 11px; }}

/* ---------- 顶栏 / 页头 ---------- */
QWidget#TopBar {{ background: #E9EEF6; border-bottom: 1px solid #D3DDEA; }}
QWidget#PageHead {{ background: {BG}; border-bottom: 1px solid #E1E8F2; }}
QWidget#PageHead QLabel#PageHeadTitle {{
    color: {NAVY}; font-size: 15.5px; font-weight: bold; letter-spacing: 0.3px;
}}
QWidget#PageHead QLabel {{ color: {MUTED}; font-size: 12px; }}

/* ---------- 页签 ---------- */
QTabBar#PageTabs {{ background: transparent; }}
QTabBar#PageTabs::tab {{
    background: #D8E1EE; color: #4C5F78; border: 1px solid #C9D4E4; border-bottom: none;
    border-top-left-radius: 7px; border-top-right-radius: 7px;
    padding: 3px 6px 3px 12px; margin: 2px 2px 0px 0px; min-width: 78px; font-size: 12.5px;
}}
QTabBar#PageTabs::tab:hover {{ background: #EDF2F9; color: {NAVY}; }}
QTabBar#PageTabs::tab:selected {{
    background: {CARD}; color: {NAVY}; border-color: #CBD5E1; font-weight: bold;
}}
QTabBar#PageTabs::scroller {{ width: 40px; }}
QTabBar#PageTabs QToolButton {{
    background: #D5DFEC; border: 1px solid #C4D1E1; border-radius: 5px;
    min-width: 16px; min-height: 16px; margin: 6px 2px 3px 2px; padding: 0px;
}}
QPushButton#TabClose {{
    background: transparent; border: none; color: #8FA0B5; font-size: 13px;
    padding: 0px; margin: 0px; min-height: 0px;
}}
QPushButton#TabClose:hover {{ background: #DFE7F1; color: {DANGER}; border-radius: 7px; }}

/* ---------- 卡片 ---------- */
QFrame#Card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; }}
QLabel#CardTitle {{ color: {NAVY}; font-size: 14px; font-weight: bold; }}
QLabel#CardHint {{ color: {MUTED}; font-size: 11.5px; }}
QFrame#StatCard {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; }}
QLabel#StatLabel {{ color: {MUTED}; font-size: 12px; }}
QLabel#StatValue {{ color: {NAVY}; font-size: 23px; font-weight: bold; }}
QLabel#StatUnit {{ color: {MUTED}; font-size: 11.5px; }}
QLabel#StatHint {{ color: {MUTED}; font-size: 11px; }}

/* ---------- 按钮 ---------- */
QPushButton {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 6px 14px; color: {TEXT}; font-size: 12.5px;
}}
QPushButton:hover {{ border-color: {NAVY_LIGHT}; color: {NAVY_2}; }}
QPushButton:pressed {{ background: #EDF1F8; }}
QPushButton:disabled {{ color: #A8B3C4; border-color: #EDF0F5; }}
QPushButton#Primary {{ background: {NAVY_2}; border: 1px solid {NAVY_2}; color: #FFFFFF; font-weight: bold; }}
QPushButton#Primary:hover {{ background: {NAVY_LIGHT}; border-color: {NAVY_LIGHT}; }}
QPushButton#Gold {{ background: {GOLD}; border: 1px solid {GOLD}; color: #FFFFFF; font-weight: bold; }}
QPushButton#Gold:hover {{ background: #D4B45F; border-color: #D4B45F; }}
QPushButton#Danger {{ color: {DANGER}; border-color: #F0CFCA; }}
QPushButton#QuickBtn {{
    background: transparent; border: 1px solid transparent; border-radius: 5px; padding: 0px;
}}
QPushButton#QuickBtn:hover {{ background: #DCE6F2; border-color: #C9D8EA; }}
QPushButton#QuickBtn:pressed {{ background: #CBDCEF; }}
QPushButton#QuickBtn:disabled {{ background: transparent; border-color: transparent; }}
QPushButton#Danger:hover {{ background: #FDF3F1; border-color: {DANGER}; }}

/* ---------- 输入 ---------- */
QLineEdit, QComboBox, QDateEdit, QDoubleSpinBox, QSpinBox {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 5px 24px 5px 8px; min-height: 22px; color: {TEXT}; font-size: 12.5px;
    selection-background-color: {NAVY_2};
}}
QLineEdit {{ padding-right: 8px; }}
QDateEdit {{ padding-right: 22px; }}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QDoubleSpinBox:focus {{ border-color: {NAVY_LIGHT}; }}
QComboBox::drop-down, QDateEdit::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 18px; border: none; background: transparent;
}}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QSpinBox::up-button, QSpinBox::down-button {{ width: 0px; border: none; background: transparent; }}
QComboBox QAbstractItemView {{
    border: 1px solid {BORDER}; background: {CARD};
    selection-background-color: #E8EEF8; selection-color: {NAVY}; outline: 0;
}}
QTextEdit {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px; font-size: 12.5px; }}

/* ---------- 表格 ---------- */
QTableWidget {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px;
    gridline-color: #EDF1F7; font-size: 12.5px;
    selection-background-color: #E3ECF8; selection-color: {NAVY};
    alternate-background-color: #FAFBFD;
}}
QTableWidget::item {{ padding: 4px 6px; }}
QHeaderView::section {{
    background: #F1F5FB; color: {NAVY}; border: none; border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER}; padding: 7px 6px; font-size: 12px; font-weight: bold;
}}
QTableCornerButton::section {{ background: #F1F5FB; border: none; }}

/* ---------- 其它 ---------- */
QLabel#Muted {{ color: {MUTED}; font-size: 11.5px; }}
QLabel#Strong {{ color: {TEXT}; font-weight: bold; }}
QLabel#Badge {{ background: #EEF3FB; color: {NAVY_2}; border-radius: 8px; padding: 1px 8px; font-size: 11px; }}
QLabel#BadgeWarn {{ background: #FDF3E2; color: {WARN}; border-radius: 8px; padding: 1px 8px; font-size: 11px; }}
QLabel#BadgeOk {{ background: #E8F6F0; color: {SUCCESS}; border-radius: 8px; padding: 1px 8px; font-size: 11px; }}
QLabel#BadgeBad {{ background: #FCECEA; color: {DANGER}; border-radius: 8px; padding: 1px 8px; font-size: 11px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #CBD6E6; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #A9BCD5; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: #CBD6E6; border-radius: 5px; min-width: 30px; }}
QToolTip {{ background: {NAVY}; color: #FFFFFF; border: none; padding: 4px 8px; }}
QStatusBar {{ background: {CARD}; color: {MUTED}; border-top: 1px solid {BORDER}; font-size: 12px; }}
QSplitter::handle {{ background: #E9EEF6; }}

"""


def apply_theme(app) -> None:
    """app 级字体、调色板与 QSS。"""
    app.setStyle("Fusion")

    # 系统深色模式下，Qt 6.8+ 会让 Fusion 跟着变深（日历、菜单这类自绘弹窗最明显）。
    # 这本账是浅色商务风，直接钉成浅色，免得两套配色打架。
    try:
        from PySide6.QtCore import Qt
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except (AttributeError, ImportError):
        pass

    font = QFont("Microsoft YaHei UI", 9)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BG))
    palette.setColor(QPalette.WindowText, QColor(TEXT))
    palette.setColor(QPalette.Base, QColor(CARD))
    palette.setColor(QPalette.AlternateBase, QColor("#FAFBFD"))
    palette.setColor(QPalette.Text, QColor(TEXT))
    palette.setColor(QPalette.Button, QColor(CARD))
    palette.setColor(QPalette.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.Highlight, QColor("#E3ECF8"))
    palette.setColor(QPalette.HighlightedText, QColor(NAVY))
    palette.setColor(QPalette.ToolTipBase, QColor(NAVY))
    palette.setColor(QPalette.ToolTipText, QColor("#FFFFFF"))
    app.setPalette(palette)

    app.setStyleSheet(QSS)


def money_color(value: float) -> str:
    """中国会计习惯：正数（收益）红色、负数（亏损）绿色。"""
    if value > 0:
        return POSITIVE
    if value < 0:
        return NEGATIVE
    return TEXT
