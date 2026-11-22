"""对话框：通用表单、确认框，以及屠宰单（主表 + 产出明细）录入窗口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QDoubleValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mscm.core.models import r1, r2
from mscm.ui import theme
from mscm.ui.widgets import Combo, DateEdit, button, label


@dataclass
class Field:
    key: str
    label: str
    kind: str = "text"            # text / number / int / combo / date / date_opt / multiline / readonly
    required: bool = False
    options: Sequence[str] = field(default_factory=tuple)
    editable: bool = False
    decimals: int = 2
    suffix: str = ""
    placeholder: str = ""
    width: int = 240
    enabled: bool = True
    hint: str = ""
    span: bool = False            # 独占一行


class FormDialog(QDialog):
    """一条记录的新增/编辑表单。

    ``calc`` 用于联动计算（数量 × 单价 = 金额）：任一字段变化时调用
    ``calc(values) -> dict``，把结果回填到对应控件。
    """

    def __init__(self, title: str, fields: Sequence[Field], values: dict | None = None,
                 parent: QWidget | None = None, hint: str = "",
                 calc: Callable[[dict], dict] | None = None, width: int = 580) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        self._fields = list(fields)
        self._widgets: dict[str, QWidget] = {}
        self._calc = calc
        self._title = title
        self._values = dict(values or {})

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        head = QLabel(title)
        head.setStyleSheet(f"color:{theme.NAVY};font-size:16px;font-weight:bold;")
        root.addWidget(head)
        if hint:
            sub = QLabel(hint)
            sub.setObjectName("CardHint")
            sub.setWordWrap(True)
            root.addWidget(sub)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(9)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        root.addLayout(grid)

        row = col = 0
        for f in self._fields:
            w = self._make_widget(f, self._values.get(f.key))
            self._widgets[f.key] = w
            lab = QLabel(f.label + ("  *" if f.required else ""))
            lab.setStyleSheet(f"color:{theme.TEXT};font-size:12.5px;")
            lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if f.span:
                if col:
                    row += 1
                    col = 0
                grid.addWidget(lab, row, 0)
                grid.addWidget(w, row, 1, 1, 3)
                row += 1
            else:
                grid.addWidget(lab, row, col * 2)
                grid.addWidget(w, row, col * 2 + 1)
                col += 1
                if col >= 2:
                    col = 0
                    row += 1

        self.error = QLabel("")
        self.error.setStyleSheet(f"color:{theme.DANGER};font-size:12px;")
        self.error.setWordWrap(True)
        root.addWidget(self.error)

        root.addStretch(1)
        line = QHBoxLayout()
        line.addStretch(1)
        line.addWidget(button("取消", "", self.reject))
        ok = button("确定", "Primary", self._on_ok)
        ok.setDefault(True)
        line.addWidget(ok)
        root.addLayout(line)

        if calc:
            self._hook_calc()
        self._refresh_calc()
        # 两列表单按最小宽度兜底：只给 580 时右列控件会被裁掉（字段 240px × 2 列放不下）
        self.setMinimumWidth(max(width, self.layout().minimumSize().width()))

    # ---------------------------------------------------------- 控件
    def _make_widget(self, f: Field, value: Any) -> QWidget:
        if f.kind in ("text", "readonly"):
            w = QLineEdit()
            w.setText("" if value is None else str(value))
            w.setPlaceholderText(f.placeholder)
            w.setReadOnly(f.kind == "readonly")
            if f.kind == "readonly":
                w.setStyleSheet(f"background:#F6F8FC;color:{theme.MUTED};")
        elif f.kind in ("number", "int"):
            w = QDoubleSpinBox()
            w.setDecimals(0 if f.kind == "int" else f.decimals)
            w.setRange(0, 99_999_999)
            w.setSingleStep(1 if f.kind == "int" else 0.1)
            w.setSuffix(f.suffix)
            w.setValue(float(value or 0))
        elif f.kind == "combo":
            w = Combo()
            w.setEditable(f.editable)
            w.addItems([str(o) for o in f.options])
            if f.editable:
                w.setInsertPolicy(QComboBox.NoInsert)
            if value not in (None, ""):
                idx = w.findText(str(value))
                if idx >= 0:
                    w.setCurrentIndex(idx)
                elif f.editable:
                    w.setEditText(str(value))
                else:
                    # 历史值不在选项里：补进下拉再选中，否则保存会被静默改成第一项
                    w.addItem(str(value))
                    w.setCurrentIndex(w.count() - 1)
        elif f.kind in ("date", "date_opt"):
            w = DateEdit()
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd")
            d = QDate.fromString(str(value or ""), "yyyy-MM-dd")
            if f.kind == "date_opt":
                # 可留空的日期（如「首次供货时间」）：最小值当空值，显示「（未填）」
                w.setMinimumDate(QDate(2000, 1, 1))
                w.setSpecialValueText("（未填）")
                w.setDate(d if d.isValid() else QDate(2000, 1, 1))
            else:
                w.setDate(d if d.isValid() else QDate.currentDate())
        elif f.kind == "multiline":
            w = QPlainTextEdit()
            w.setPlainText("" if value is None else str(value))
            w.setFixedHeight(62)
        else:
            w = QLineEdit(str(value or ""))
        w.setEnabled(f.enabled)
        if f.kind != "multiline":
            w.setMinimumWidth(f.width)
        if f.hint:
            w.setToolTip(f.hint)
        return w

    # ---------------------------------------------------------- 取值
    def widget(self, key: str) -> QWidget | None:
        return self._widgets.get(key)

    def value(self, key: str) -> Any:
        w = self._widgets.get(key)
        if isinstance(w, QLineEdit):
            return w.text().strip()
        if isinstance(w, QDoubleSpinBox):
            return w.value()
        if isinstance(w, QComboBox):
            return w.currentText().strip()
        if isinstance(w, QDateEdit):
            text = w.date().toString("yyyy-MM-dd")
            return "" if text == "2000-01-01" else text
        if isinstance(w, QPlainTextEdit):
            return w.toPlainText().strip()
        return None

    def values(self) -> dict:
        out = {f.key: self.value(f.key) for f in self._fields}
        out.update(getattr(self, "_extra", {}))
        return out

    def set_value(self, key: str, value: Any) -> None:
        w = self._widgets.get(key)
        if isinstance(w, QLineEdit):
            w.setText("" if value is None else str(value))
        elif isinstance(w, QDoubleSpinBox):
            w.blockSignals(True)
            w.setValue(float(value or 0))
            w.blockSignals(False)
        elif isinstance(w, QComboBox):
            idx = w.findText(str(value))
            if idx >= 0:
                w.setCurrentIndex(idx)
            elif w.isEditable():
                # 下拉里没有就写进编辑框，别把人工输入吞掉
                w.setEditText(str(value))
        elif isinstance(w, QDateEdit):
            d = QDate.fromString(str(value or ""), "yyyy-MM-dd")
            if d.isValid():
                w.setDate(d)
            elif w.minimumDate() == QDate(2000, 1, 1):
                w.setDate(w.minimumDate())          # date_opt：空值回「（未填）」
        elif isinstance(w, QPlainTextEdit):
            w.setPlainText("" if value is None else str(value))

    # ---------------------------------------------------------- 联动
    def _hook_calc(self) -> None:
        for w in self._widgets.values():
            if isinstance(w, QDoubleSpinBox):
                w.valueChanged.connect(self._refresh_calc)
            elif isinstance(w, QLineEdit):
                w.textChanged.connect(self._refresh_calc)
            elif isinstance(w, QComboBox):
                w.currentTextChanged.connect(self._refresh_calc)
            elif isinstance(w, QDateEdit):
                w.dateChanged.connect(self._refresh_calc)

    def _refresh_calc(self, *_args) -> None:
        if not self._calc:
            return
        try:
            patch = self._calc(self.values()) or {}
        except Exception:                       # 计算容错，不让表单崩掉
            return
        for key, val in patch.items():
            if key in self._widgets and val is not None:
                self.set_value(key, val)

    # ---------------------------------------------------------- 提交
    def _on_ok(self) -> None:
        for f in self._fields:
            if f.required and self.value(f.key) in ("", None):
                self.error.setText(f"「{f.label}」不能为空")
                return
        self.error.setText("")
        self.accept()


# ---------------------------------------------------------------- 屠宰单
class SlaughterDialog(QDialog):
    """屠宰记录：一张单 = 领入（只数/毛重）+ 若干行屠宰产出。

    产出按商品分行登记（白条、分割品、副产品），金额 = kg × 单价现算；
    出肉率与领用成本在底部实时显示，保存前就能看出这头羊宰得对不对。
    """

    HEAD = ["产出类别", "数量(只)", "数量(kg)", "单价(元/kg)", "金额"]

    def __init__(self, ctx, conn, values: dict | None = None,
                 lines: list[dict] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("屠宰记录")
        self.setModal(True)
        self.resize(880, 640)
        self._values = dict(values or {})
        self._lines = [dict(x) for x in (lines or [])]

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(10)

        head = QLabel("屠宰记录　·　领入与产出")
        head.setStyleSheet(f"color:{theme.NAVY};font-size:16px;font-weight:bold;")
        root.addWidget(head)

        # ---------------- 表头字段 ----------------
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        for i in range(6):
            grid.setColumnStretch(i, 1)
        self.f_date = DateEdit()
        self.f_date.setCalendarPopup(True)
        self.f_date.setDisplayFormat("yyyy-MM-dd")
        d = QDate.fromString(str(self._values.get("date") or ""), "yyyy-MM-dd")
        self.f_date.setDate(d if d.isValid() else QDate.currentDate())

        self.f_doc = QLineEdit(str(self._values.get("doc_no") or ""))
        self.f_doc.setReadOnly(True)
        self.f_doc.setStyleSheet(f"background:#F6F8FC;color:{theme.MUTED};")

        self.f_batch = Combo()
        self._batch_rows: list[dict] = []
        for b in ctx.batch_options(include_blank=False):
            self._batch_rows.append({"id": b[1], "label": b[0]})
            self.f_batch.addItem(b[0], b[1])
        cur = int(self._values.get("batch_id") or 0)
        idx = self.f_batch.findData(cur)
        self.f_batch.setCurrentIndex(idx if idx >= 0 else 0)

        self.f_category = QLineEdit(str(self._values.get("category") or ""))
        self.f_category.setReadOnly(True)
        self.f_category.setStyleSheet(f"background:#F6F8FC;color:{theme.MUTED};")

        self._num = {}
        for key, text in (("in_count", "领入数量(只)"), ("in_weight", "领入毛重(kg)")):
            edit = QLineEdit(f"{float(self._values.get(key) or 0):.2f}"
                             if key == "in_weight" else
                             f"{float(self._values.get(key) or 0):.1f}")
            edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            edit.setValidator(QDoubleValidator(0, 99_999_999, 2, edit))
            self._num[key] = edit
        grid.addWidget(_field_label("日期"), 0, 0)
        grid.addWidget(self.f_date, 0, 1)
        grid.addWidget(_field_label("屠宰单号"), 0, 2)
        grid.addWidget(self.f_doc, 0, 3)
        grid.addWidget(_field_label("羊群批次"), 0, 4)
        grid.addWidget(self.f_batch, 0, 5)

        grid.addWidget(_field_label("品类"), 1, 0)
        grid.addWidget(self.f_category, 1, 1)
        grid.addWidget(_field_label("领入数量(只)"), 1, 2)
        grid.addWidget(self._num["in_count"], 1, 3)
        grid.addWidget(_field_label("领入毛重(kg)"), 1, 4)
        grid.addWidget(self._num["in_weight"], 1, 5)

        grid.addWidget(_field_label("标识"), 2, 0)
        self.f_tag = QLineEdit(str(self._values.get("tag") or ""))
        grid.addWidget(self.f_tag, 2, 1)
        grid.addWidget(_field_label("屠宰人"), 2, 2)
        self.f_operator = QLineEdit(str(self._values.get("operator") or ""))
        grid.addWidget(self.f_operator, 2, 3)
        root.addLayout(grid)

        # ---------------- 产出明细 ----------------
        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(label("屠宰产出明细（按商品分行）", "Strong"))
        bar.addStretch(1)
        bar.addWidget(button("＋ 加一行", "", self._add_line))
        bar.addWidget(button("删除行", "Danger", self._del_line))
        root.addLayout(bar)

        self.table = QTableWidget(0, len(self.HEAD))
        self.table.setHorizontalHeaderLabels(self.HEAD)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, len(self.HEAD)):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.Interactive)
            self.table.setColumnWidth(i, 108 if i < 4 else 128)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.itemChanged.connect(self._on_item_changed)
        root.addWidget(self.table, 1)

        self.sum = QLabel("")
        self.sum.setStyleSheet(f"color:{theme.NAVY};font-size:12.5px;font-weight:bold;")
        root.addWidget(self.sum)

        self.error = QLabel("")
        self.error.setStyleSheet(f"color:{theme.DANGER};font-size:12px;")
        root.addWidget(self.error)

        tail = QHBoxLayout()
        tail.addStretch(1)
        tail.addWidget(button("取消", "", self.reject))
        ok = button("保存屠宰单", "Primary", self._on_ok)
        ok.setDefault(True)
        tail.addWidget(ok)
        root.addLayout(tail)

        self.f_batch.currentIndexChanged.connect(self._on_batch)
        for e in self._num.values():
            e.textChanged.connect(self._refresh_sum)
        self._on_batch()
        self._fill_lines()
        self._refresh_sum()

    # ---------------------------------------------------------- 明细
    def _fill_lines(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for ln in self._lines:
            self._append_row(ln)
        if not self._lines:
            self._append_row({})
        self.table.blockSignals(False)

    def _append_row(self, ln: dict) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        vals = [ln.get("product") or "",
                _fmt(ln.get("count"), 1) if ln.get("count") else "",
                _fmt(ln.get("weight"), 2) if ln.get("weight") else "",
                _fmt(ln.get("price"), 2) if ln.get("price") else "",
                _fmt(ln.get("amount"), 2) if ln.get("amount") else ""]
        for c, v in enumerate(vals):
            item = QTableWidgetItem(str(v))
            if c == 0:
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            else:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if c == 4:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setForeground(QColor(theme.MUTED))
            self.table.setItem(r, c, item)

    def _add_line(self) -> None:
        self.table.blockSignals(True)
        self._append_row({})
        self.table.blockSignals(False)
        self.table.setCurrentCell(self.table.rowCount() - 1, 0)

    def _del_line(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            return
        self.table.removeRow(r)
        self._refresh_sum()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 4:
            return
        self._refresh_sum()

    def _read_lines(self) -> list[dict]:
        out = []
        for r in range(self.table.rowCount()):
            def txt(c: int) -> str:
                it = self.table.item(r, c)
                return it.text().strip() if it else ""
            product = txt(0)
            if not product and not txt(2):
                continue
            count = _to_float(txt(1))
            weight = _to_float(txt(2))
            price = _to_float(txt(3))
            out.append({"product": product, "count": count, "weight": weight,
                        "price": price, "amount": r2(weight * price)})
        return out

    def _refresh_sum(self, *_args) -> None:
        lines = self._read_lines()
        total_kg = r1(sum(x["weight"] for x in lines))
        total_amt = r2(sum(x["amount"] for x in lines))
        in_w = _to_float(self._num["in_weight"].text())
        rate = (total_kg / in_w) if in_w else 0.0
        self.sum.setText(
            f"产出合计：{len(lines)} 个类别　{total_kg:,.1f} kg　金额 {total_amt:,.2f} 元　"
            f"出肉率 {rate * 100:,.1f}%　（领入毛重 {in_w:,.1f} kg）")
        self.sum.setStyleSheet(
            f"color:{theme.WARN if rate and not (0.30 <= rate <= 0.65) else theme.NAVY};"
            "font-size:12.5px;font-weight:bold;")
        # 金额列回填（不触发 itemChanged 递归）
        self.table.blockSignals(True)
        for r, ln in enumerate(lines):
            item = self.table.item(r, 4)
            if item is not None:
                item.setText(_fmt(ln["amount"], 2))
        self.table.blockSignals(False)

    def _on_batch(self) -> None:
        bid = int(self.f_batch.currentData() or 0)
        code = str((self.conn.get("batch", bid) or {}).get("category") or "")
        self.f_category.setText(code)

    # ---------------------------------------------------------- 提交
    def _on_ok(self) -> None:
        bid = int(self.f_batch.currentData() or 0)
        if not bid:
            self.error.setText("先选一个羊群批次")
            return
        in_count = _to_float(self._num["in_count"].text())
        in_weight = _to_float(self._num["in_weight"].text())
        if in_count <= 0:
            self.error.setText("领入数量要大于 0 只")
            return
        lines = self._read_lines()
        if not lines:
            self.error.setText("屠宰产出至少登记一行")
            return
        bad = [x for x in lines if not x["product"] or x["weight"] <= 0]
        if bad:
            self.error.setText("产出明细里「产出类别」和「数量(kg)」都要填")
            return
        self.result_values = {
            "date": self.f_date.date().toString("yyyy-MM-dd"),
            "doc_no": self.f_doc.text().strip(),
            "batch_id": bid,
            "category": self.f_category.text().strip(),
            "in_count": in_count,
            "in_weight": in_weight,
            "tag": self.f_tag.text().strip(),
            "operator": self.f_operator.text().strip(),
            "remark": str(self._values.get("remark") or ""),
        }
        self.result_lines = lines
        self.accept()


# ---------------------------------------------------------------- 小工具
def _field_label(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setStyleSheet(f"color:{theme.TEXT};font-size:12.5px;")
    lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return lb


def _fmt(value, decimals: int) -> str:
    return f"{float(value or 0):.{decimals}f}"


def _to_float(text: str) -> float:
    try:
        return float(str(text or "0").replace(",", "").strip())
    except ValueError:
        return 0.0


def confirm(parent: QWidget | None, title: str, text: str, danger: bool = False) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Warning if danger else QMessageBox.Question)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.button(QMessageBox.Yes).setText("确定")
    box.button(QMessageBox.No).setText("取消")
    if danger:
        box.button(QMessageBox.Yes).setStyleSheet(f"color:{theme.DANGER};font-weight:bold;")
    return box.exec() == QMessageBox.Yes


def info(parent: QWidget | None, title: str, text: str) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Information)
    box.exec()
