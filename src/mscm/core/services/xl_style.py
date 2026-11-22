"""Excel 出表样式：深蓝表头 + 白字微软雅黑 + 细边框 + 千分位。

口径与项目里其它台账一致：抬头有标题与口径副标题、表头深蓝、数值右对齐、
金额/单价两位、kg 一位；不在出表文件里写公式（公式在程序里算，出表给快照）。
"""

from __future__ import annotations

from pathlib import Path

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

NAVY = "1F3864"
NAVY_LIGHT = "D9E2F3"
GOLD = "BF9000"
GREY = "F2F2F2"
NOTE_COLOR = "595959"

FONT_NAME = "微软雅黑"

TITLE_FONT = Font(name=FONT_NAME, size=14, bold=True, color=NAVY)
SUB_FONT = Font(name=FONT_NAME, size=9, color=NOTE_COLOR)
HEAD_FONT = Font(name=FONT_NAME, size=9.5, bold=True, color="FFFFFF")
BODY_FONT = Font(name=FONT_NAME, size=9.5)
TOTAL_FONT = Font(name=FONT_NAME, size=9.5, bold=True)
BATCH_FONT = Font(name=FONT_NAME, size=10.5, bold=True, color=NAVY)

HEAD_FILL = PatternFill("solid", fgColor=NAVY)
SUBHEAD_FILL = PatternFill("solid", fgColor="2E5490")
TOTAL_FILL = PatternFill("solid", fgColor=NAVY_LIGHT)
ZEBRA_FILL = PatternFill("solid", fgColor="FAFBFD")

_thin = Side(style="thin", color="D0D7E5")
BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)


def write_title(ws: Worksheet, row: int, text: str, ncols: int, sub: str = "") -> int:
    ws.cell(row=row, column=1, value=text).font = TITLE_FONT
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(ncols, 2))
    ws.cell(row=row, column=1).alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[row].height = 28
    if sub:
        ws.cell(row=row + 1, column=1, value=sub).font = SUB_FONT
        ws.merge_cells(start_row=row + 1, start_column=1, end_row=row + 1, end_column=max(ncols, 2))
        ws.cell(row=row + 1, column=1).alignment = Alignment(horizontal="left", vertical="center")
        return row + 2
    return row + 1


def write_header(ws: Worksheet, start_row: int, groups: list[tuple[str, int]],
                 leaves: list[str]) -> int:
    """两层表头：上层分组（跨列合并），下层明细列。

    groups = [("日期", 1), ("入库", 6), …]，宽度合计须等于 len(leaves)。
    宽度为 1 的组纵向合并两行（如「日期」占 A3:A4）。
    """
    row = start_row
    # 先写下层明细列，再写上层分组名，最后做合并：
    # 顺序反了的话，合并后的 MergedCell 是只读的，再往里写值会直接抛错。
    for i, name in enumerate(leaves, start=1):
        cell = ws.cell(row=row + 1, column=i, value=name)
        cell.font = HEAD_FONT
        cell.fill = SUBHEAD_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    ws.row_dimensions[row + 1].height = 30

    col = 1
    for name, span in groups:
        cell = ws.cell(row=row, column=col, value=name)
        cell.font = HEAD_FONT
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for c in range(col, col + span):
            ws.cell(row=row, column=c).border = BORDER
            ws.cell(row=row, column=c).fill = HEAD_FILL
        if span > 1:
            ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + span - 1)
        else:
            ws.merge_cells(start_row=row, start_column=col, end_row=row + 1, end_column=col)
        col += span
    ws.row_dimensions[row].height = 22
    return row + 2


def write_flat_header(ws: Worksheet, row: int, headers: list[str]) -> int:
    """单层表头（门店三张明细、屠宰出库用这种）。"""
    for i, name in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=i, value=name)
        cell.font = HEAD_FONT
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    ws.row_dimensions[row].height = 32
    return row + 1


def write_rows(ws: Worksheet, start_row: int, rows: list[list],
               formats: list[str | None] | None = None,
               aligns: list[str] | None = None) -> int:
    for i, row in enumerate(rows):
        r = start_row + i
        for c, val in enumerate(row, start=1):
            cell = ws.cell(row=r, column=c, value=val)
            cell.font = BODY_FONT
            cell.border = BORDER
            if aligns and c - 1 < len(aligns) and aligns[c - 1]:
                align = aligns[c - 1]
            else:
                align = "right" if isinstance(val, (int, float)) else "left"
            cell.alignment = Alignment(horizontal=align, vertical="center",
                                       wrap_text=(align == "left" and isinstance(val, str)
                                                  and len(str(val)) > 12))
            if formats and c - 1 < len(formats) and formats[c - 1]:
                cell.number_format = formats[c - 1]
            if i % 2 == 1:
                cell.fill = ZEBRA_FILL
            ws.row_dimensions[r].height = 18
    return start_row + len(rows)


def write_total(ws: Worksheet, row: int, values: list, ncols: int,
                formats: list[str | None] | None = None,
                aligns: list[str] | None = None) -> int:
    for c in range(1, ncols + 1):
        val = values[c - 1] if c - 1 < len(values) else None
        cell = ws.cell(row=row, column=c, value=val)
        cell.font = TOTAL_FONT
        cell.fill = TOTAL_FILL
        cell.border = BORDER
        align = (aligns[c - 1] if aligns and c - 1 < len(aligns) and aligns[c - 1]
                 else ("right" if isinstance(val, (int, float)) else "left"))
        cell.alignment = Alignment(horizontal=align, vertical="center")
        if formats and c - 1 < len(formats) and formats[c - 1]:
            cell.number_format = formats[c - 1]
    ws.row_dimensions[row].height = 20
    return row + 1


def write_note(ws: Worksheet, row: int, text: str, ncols: int) -> None:
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = SUB_FONT
    cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(ncols, 2))
    ws.row_dimensions[row].height = 30


def set_widths(ws: Worksheet, widths: list[float]) -> None:
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def setup_page(ws: Worksheet, landscape: bool = True) -> None:
    ws.page_setup.orientation = "landscape" if landscape else "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True
    ws.print_title_rows = "1:4"


def freeze(ws: Worksheet, row: int) -> None:
    ws.freeze_panes = ws.cell(row=row, column=1)


def default_path(stem: str, day: str = "") -> Path:
    from mscm import config
    config.ensure_dirs()
    safe = f"{stem}-{day}" if day else stem
    return Path(config.EXPORT_DIR) / f"{safe}.xlsx"
