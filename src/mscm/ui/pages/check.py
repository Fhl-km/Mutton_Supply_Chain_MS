"""数据校验：把七张台账之间的勾稽逐条核一遍。"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from mscm import config
from mscm.core import calc
from mscm.core.services import xl_style as X
from mscm.ui import theme
from mscm.ui.dialogs import info
from mscm.ui.widgets import (
    Card, Column, DataTable, FilterStrip, PageBase, button, label,
)

COLS = [
    Column("结论", 78, "center"),
    Column("校验项", 250),
    Column("说明 / 处理建议", 520, stretch=True),
    Column("应有", 170, "right"),
    Column("实有", 190, "right"),
]

LEVEL_COLOR = {"ok": theme.SUCCESS, "warn": theme.WARN, "bad": theme.DANGER}


class CheckPage(PageBase):
    def __init__(self, ctx, parent=None) -> None:
        super().__init__(ctx, parent)
        self._rows: list[dict] = []

        from PySide6.QtWidgets import QVBoxLayout
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 6, 14, 4)
        root.setSpacing(0)

        strip = FilterStrip()
        strip.add(label("校验范围：全部台账（不按期间过滤，避免把跨期结存切碎）", "Muted"))
        strip.add_stretch()
        strip.add(button("重新校验", "Primary", self.refresh))
        strip.add(button("导出校验表", "", self.on_export))
        root.addWidget(strip)

        self.card = Card("勾稽校验结果", "")
        self.table = DataTable(COLS, row_height=34)
        self.card.add(self.table, 1)
        root.addWidget(self.card, 1)

        self.foot = label("", "Muted")
        self.foot.setStyleSheet(f"color:{theme.MUTED};font-size:12px;padding:4px 2px;")
        root.addWidget(self.foot)

    def refresh(self) -> None:
        checks = calc.checks(self.ctx.conn)
        self._rows = [{
            "level": c.level, "label": c.label, "item": c.item, "detail": c.detail,
            "expect": c.expect, "actual": c.actual,
        } for c in checks]
        body = [[r["label"], r["item"], r["detail"], r["expect"], r["actual"]]
                for r in self._rows]
        colors = {(i, 0): LEVEL_COLOR.get(r["level"], theme.TEXT)
                  for i, r in enumerate(self._rows)}
        self.table.set_rows(body, self._rows, colors=colors,
                            empty_text="没有校验结果")
        for i in range(len(body)):
            self.table.setRowHeight(i, 34)
        ok = sum(1 for r in self._rows if r["level"] == "ok")
        warn = sum(1 for r in self._rows if r["level"] == "warn")
        bad = sum(1 for r in self._rows if r["level"] == "bad")
        self.card.set_hint(f"通过 {ok} · 注意 {warn} · 异常 {bad}")
        self.foot.setText(
            f"共 {len(self._rows)} 项　·　异常 {bad} 项（必须处理）　·　注意 {warn} 项（核对后确认）　·　"
            "校验口径：暂养入−出=结存、养殖期初−出栏=期末、屠宰领入↔产出↔出库、门店入库−销售=账面、盘点↔账面")

    def on_export(self) -> None:
        if not self._rows:
            self.notify("先点「重新校验」", "warn")
            return
        config.ensure_dirs()
        path = Path(config.EXPORT_DIR) / f"数据校验-{self.ctx.biz_date}.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "校验结果"
        n = X.write_title(ws, 1, "数据校验结果", 5, sub=f"校验日期：{self.ctx.biz_date}　"
                                                        "系统：羊供应链管理系统")
        start = X.write_flat_header(ws, n + 1, ["结论", "校验项", "说明 / 处理建议", "应有", "实有"])
        rows = [[r["label"], r["item"], r["detail"], r["expect"], r["actual"]]
                for r in self._rows]
        X.write_rows(ws, start, rows, [None, None, None, None, None],
                     ["center", "left", "left", "right", "right"])
        X.set_widths(ws, [8, 34, 70, 22, 24])
        X.setup_page(ws)
        path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(path)
        wb.close()
        self.notify(f"已导出：{path.name}")
        info(self, "导出完成", f"已导出到：\n{path}")
