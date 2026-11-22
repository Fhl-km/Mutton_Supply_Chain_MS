"""系统设置：数据文件、备份、整套台账导出、示例数据、软件更新与清空。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QVBoxLayout

from mscm import config
from mscm.core import bootstrap, repo
from mscm.core.services import export as xl_export
from mscm.ui import update_ui
from mscm.ui.dialogs import confirm, info
from mscm.ui.widgets import Card, Combo, DateEdit, PageBase, button, label

from PySide6.QtCore import QDate


class SettingsPage(PageBase):
    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 8, 14, 8)
        root.setSpacing(10)

        # ---------------- 数据文件 ----------------
        card = Card("数据文件", "整份账套就是一个 JSON 文件，拷走即备份")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(label("存放位置", "Muted"), 0, 0)
        self.path_label = label("", "Strong")
        self.path_label.setWordWrap(True)
        grid.addWidget(self.path_label, 0, 1, 1, 3)
        grid.addWidget(label("数据目录", "Muted"), 1, 0)
        self.dir_label = label("", "Muted")
        grid.addWidget(self.dir_label, 1, 1, 1, 3)
        grid.addWidget(label("导出目录", "Muted"), 2, 0)
        self.exp_label = label(str(config.EXPORT_DIR), "Muted")
        grid.addWidget(self.exp_label, 2, 1, 1, 3)
        card.add_layout(grid)
        row = QHBoxLayout()
        row.addWidget(button("立即备份", "Primary", self.on_backup, tip="另存一份快照到 data/backup"))
        row.addWidget(button("打开数据目录", "", lambda: self._open(config.DATA_DIR)))
        row.addWidget(button("打开导出目录", "", lambda: self._open(config.EXPORT_DIR)))
        row.addStretch(1)
        card.add_layout(row)
        root.addWidget(card)

        # ---------------- 整套台账导出 ----------------
        card2 = Card("整套台账导出",
                     "七张主台账一个工作簿；应收款项、应付款项在各自页面的「导出」单独出")
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(label("期间", "Muted"))
        d = QDate.fromString(ctx.biz_date, "yyyy-MM-dd")
        self.d_from = DateEdit()
        self.d_to = DateEdit()
        for w in (self.d_from, self.d_to):
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd")
            w.setFixedWidth(134)
            w.setDate(d if d.isValid() else QDate.currentDate())
        self.d_from.setDate(QDate(d.year(), d.month(), 1) if d.isValid() else QDate.currentDate())
        row2.addWidget(self.d_from)
        row2.addWidget(label("至", "Muted"))
        row2.addWidget(self.d_to)
        row2.addSpacing(8)
        row2.addWidget(label("门店", "Muted"))
        self.store_combo = Combo()
        self.store_combo.setFixedWidth(150)
        row2.addWidget(self.store_combo)
        row2.addWidget(button("导出整套台账", "Gold", self.on_export_all))
        row2.addStretch(1)
        card2.add_layout(row2)
        root.addWidget(card2)

        # ---------------- 账套维护 ----------------
        card3 = Card("账套维护", "示例数据用于熟悉界面；正式使用前请清空")
        row3 = QHBoxLayout()
        row3.setSpacing(8)
        row3.addWidget(button("重建示例账套", "", self.on_seed,
                              tip="清掉现有台账，重新灌一套示例（2 批次 / 5 张屠宰单 / 关一店）"))
        row3.addWidget(button("清空全部台账", "Danger", self.on_clear,
                              tip="只清台账，保留门店与商品档案"))
        row3.addStretch(1)
        card3.add_layout(row3)
        note = label("清空与重建都会先弹确认框；清掉的数据不可撤销，建议先点「立即备份」。", "Muted")
        note.setWordWrap(True)
        card3.add(note)
        root.addWidget(card3)

        # ---------------- 软件更新 ----------------
        card_up = Card("软件更新", f"当前版本 v{config.APP_VERSION}")
        row_up = QHBoxLayout()
        row_up.setSpacing(10)
        self.auto_update_box = QCheckBox("自动更新")
        self.auto_update_box.setChecked(update_ui.auto_update_enabled(ctx.conn))
        self.auto_update_box.setToolTip("勾选后每次启动都会在后台检查新版本，发现后提示下载安装")
        self.auto_update_box.toggled.connect(self._on_auto_update)
        self.update_btn = button("检查更新", "", self._on_check_update,
                                 tip="联网检查是否有新版本")
        row_up.addWidget(self.auto_update_box)
        row_up.addWidget(self.update_btn)
        row_up.addStretch(1)
        card_up.add_layout(row_up)
        if not config.UPDATE_CHECK_URL.strip():
            hint = label("尚未配置更新地址，配置后即可使用自动更新。", "Muted")
            hint.setWordWrap(True)
            card_up.add(hint)
        root.addWidget(card_up)

        # ---------------- 关于 ----------------
        card4 = Card("关于", "")
        about = label(
            f"{config.APP_NAME}　v{config.APP_VERSION}　·　{config.COMPANY}<br>"
            "模块：活羊采购 &amp; 屠宰（活羊入库&amp;结余 / 暂养出入库 / 养殖 / 屠宰 / 屠宰出库 / "
            "应收款项·屠宰销售 / 应付款项·活羊采购与付款）　"
            "·　门店管理（入库盘点 / 销售 / 库存盘点 / 应收款项）　"
            "·　档案（商品 / 门店 / 客户名录）<br>"
            "口径：暂养结存 = 入 − 出；出库按批次加权平均；屠宰出肉率 = 产出 kg ÷ 领入毛重；"
            "门店账面库存 = 入库 − 销售；未收款 = 应收 − 已收；未付款 = 应付 − 已付"
            "（收款 / 付款都逐笔挂在单据下面）", "Muted")
        about.setWordWrap(True)
        card4.add(about)
        root.addWidget(card4)
        root.addStretch(1)

    # ---------------------------------------------------------- 刷新
    def refresh(self) -> None:
        self.path_label.setText(str(self.ctx.conn.path))
        self.dir_label.setText(str(config.DATA_DIR))
        keep = self.store_combo.currentData() if self.store_combo.count() else 0
        self.store_combo.blockSignals(True)
        self.store_combo.clear()
        self.store_combo.addItem("全部门店", 0)
        for st in repo.list_stores(self.ctx.conn):
            self.store_combo.addItem(str(st.get("name")), int(st.get("id") or 0))
        idx = self.store_combo.findData(keep or 0)
        self.store_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.store_combo.blockSignals(False)

    # ---------------------------------------------------------- 软件更新
    def _on_auto_update(self, checked: bool) -> None:
        update_ui.set_auto_update(self.ctx.conn, checked)

    def _on_check_update(self) -> None:
        update_ui.start_check(self, self.update_btn)

    # ---------------------------------------------------------- 动作
    @staticmethod
    def _open(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(path))          # noqa: S606 - Windows 打开资源管理器
        except Exception:
            subprocess.Popen(["explorer", str(path)])

    def on_backup(self) -> None:
        target = self.ctx.conn.backup("manual")
        if target is None:
            self.notify("还没有数据文件可备份", "warn")
            return
        info(self, "备份完成", f"已备份到：\n{target}")
        self.notify(f"已备份：{target.name}")

    def on_export_all(self) -> None:
        d1 = self.d_from.date().toString("yyyy-MM-dd")
        d2 = self.d_to.date().toString("yyyy-MM-dd")
        sid = int(self.store_combo.currentData() or 0)
        config.ensure_dirs()
        path = Path(config.EXPORT_DIR) / f"羊供应链整套台账-{d1}_{d2}.xlsx"
        xl_export.export_workbook(path, self.ctx.conn, d1, d2, store_id=sid)
        info(self, "导出完成", f"七张台账已导出到：\n{path}")
        self.notify(f"已导出：{path.name}")

    def on_seed(self) -> None:
        if not confirm(self, "重建示例账套",
                       "会先清空现有全部台账，再灌入一套示例数据。\n"
                       "确定继续吗？（建议先备份）", danger=True):
            return
        bootstrap.seed_demo(self.ctx.conn)
        self.ctx.changed()
        self.notify("已重建示例账套")

    def on_clear(self) -> None:
        if not confirm(self, "清空全部台账",
                       "暂养、养殖、屠宰、出库、门店入库 / 销售 / 盘点、应收 / 应付全部清空。\n"
                       "门店与商品档案保留。这个操作不可撤销，确定吗？", danger=True):
            return
        if not confirm(self, "再确认一次",
                       "真的清空吗？清完只能从备份恢复。", danger=True):
            return
        bootstrap.clear_all(self.ctx.conn)
        self.ctx.changed()
        self.notify("已清空全部台账，档案保留")
