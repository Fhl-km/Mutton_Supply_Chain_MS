"""行内小图标：全部用 QPainter 现画，不依赖任何图片资源。

风格对齐 WPS：细线、圆角、深蓝主色；铅笔尖用金色、垃圾桶用红色。
按 32×32 坐标系绘制，输出 3 倍图，16px 显示时边缘依然清楚。
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

NAVY = "#1E4E79"
NAVY_LIGHT = "#2A6094"
GOLD = "#C8A44B"
RED = "#C0392B"

_UNIT = 32
_SCALE = 2      # 位图 64×64，缩到 16px 显示；QIcon 不吃 devicePixelRatio，只能靠多给像素


def _canvas() -> tuple[QPixmap, QPainter]:
    pm = QPixmap(_UNIT * _SCALE, _UNIT * _SCALE)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(_SCALE, _SCALE)
    return pm, p


@lru_cache(maxsize=None)
def save_icon() -> QIcon:
    """保存：软盘（盘体 + 上滑片 + 下标签），WPS 快速访问栏的样子。"""
    pm, p = _canvas()
    color = QColor(NAVY_LIGHT)
    p.setPen(QPen(color, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(6.0, 6.0, 20.0, 20.0), 2.6, 2.6)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawRect(QRectF(12.4, 6.2, 7.6, 5.4))        # 上滑片
    p.setBrush(QColor(GOLD))
    p.drawRoundedRect(QRectF(9.6, 17.4, 12.8, 8.4), 1.2, 1.2)   # 下标签
    p.end()
    return QIcon(pm)


@lru_cache(maxsize=None)
def edit_icon() -> QIcon:
    """编辑：一支斜放的铅笔（深蓝笔身 + 金色笔尖）。"""
    pm, p = _canvas()
    p.setPen(Qt.NoPen)
    body = QPainterPath()
    body.moveTo(9.6, 20.4)
    body.lineTo(20.2, 9.8)
    body.lineTo(24.2, 13.8)
    body.lineTo(13.6, 24.4)
    body.closeSubpath()
    p.fillPath(body, QColor(NAVY_LIGHT))
    tip = QPainterPath()
    tip.moveTo(8.9, 21.1)
    tip.lineTo(12.9, 25.1)
    tip.lineTo(5.4, 27.6)
    tip.closeSubpath()
    p.fillPath(tip, QColor(GOLD))
    p.end()
    return QIcon(pm)


@lru_cache(maxsize=None)
def more_icon() -> QIcon:
    """多功能集：四宫格（深蓝四块小圆角方块），同 WPS「更多功能」的观感。"""
    pm, p = _canvas()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(NAVY_LIGHT))
    for x, y in ((5.6, 5.6), (17.6, 5.6), (5.6, 17.6), (17.6, 17.6)):
        p.drawRoundedRect(QRectF(x, y, 8.8, 8.8), 2.2, 2.2)
    p.end()
    return QIcon(pm)


@lru_cache(maxsize=None)
def trash_icon() -> QIcon:
    """删除：小垃圾桶（红桶身 + 桶盖 + 两道竖纹）。"""
    pm, p = _canvas()
    color = QColor(RED)
    p.setPen(QPen(color, 2.3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(12.6, 4.6, 6.8, 3.8), 1.5, 1.5)      # 提手
    p.drawLine(QPointF(5.8, 9.9), QPointF(26.2, 9.9))             # 桶盖
    body = QPainterPath()
    body.moveTo(8.6, 12.4)
    body.lineTo(10.0, 27.2)
    body.lineTo(22.0, 27.2)
    body.lineTo(23.4, 12.4)
    p.drawPath(body)
    p.drawLine(QPointF(13.6, 15.8), QPointF(14.2, 24.2))
    p.drawLine(QPointF(18.4, 15.8), QPointF(17.8, 24.2))
    p.end()
    return QIcon(pm)


def _turn_arrow(mirror: bool) -> QIcon:
    """回转箭头：半圆 + 实心箭头，WPS 撤消 / 恢复的样式；mirror=True 得右转。"""
    pm, p = _canvas()
    if mirror:
        p.translate(_UNIT, 0)
        p.scale(-1, 1)
    color = QColor(NAVY)
    p.setPen(QPen(color, 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    rect = QRectF(8.0, 9.4, 16.0, 16.0)                            # 圆心 (16,17.4)
    path = QPainterPath()
    path.arcMoveTo(rect, 0)
    path.arcTo(rect, 0, 180)                                       # 从右端经顶部转到左端
    p.drawPath(path)
    p.setPen(Qt.NoPen)
    head = QPainterPath()
    head.moveTo(8.0, 24.2)
    head.lineTo(3.4, 16.0)
    head.lineTo(12.6, 16.0)
    head.closeSubpath()
    p.fillPath(head, color)
    p.end()
    return QIcon(pm)


@lru_cache(maxsize=None)
def undo_icon() -> QIcon:
    """撤消：向左回转。"""
    return _turn_arrow(False)


@lru_cache(maxsize=None)
def redo_icon() -> QIcon:
    """恢复：向右回转。"""
    return _turn_arrow(True)
