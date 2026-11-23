# -*- coding: utf-8 -*-
"""闲鱼上架 · Excel 层（影刀 CodeFlow：xianyu_excel）

商品清单.xlsx 的读写口径（18 列，索引 0 起；影刀按 loop_excel[n] 读，写状态列 N）：
  · 读：data_only 副本，避免公式单元格拿到公式文本
  · 写：原始副本（保留公式/格式），只改第 14 列（N），每次写完立即落盘
  · 行值列表与画布 loop_excel[索引] 对齐：row[0]=A … row[17]=R
"""

# ---- 仓库内跨文件夹 import 垫片（影刀 CodeFlow 是平铺的，正式跑时为空操作）----
import os as _os
import sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__)) if "__file__" in globals() else ""
_ROOT = _os.path.dirname(_HERE) if _HERE else ""
_MODS = ("tool", "1.登录", "2.上传套图", "3.填写描述", "4.选择分类",
         "5.填写价格", "6.设置发货", "7.发布", "8.判定回写")
for _p in ([_HERE] + [_os.path.join(_ROOT, _d) for _d in _MODS] if _ROOT else [_HERE]):
    if _p and _p not in _sys.path:
        _sys.path.insert(0, _p)

import openpyxl

import xianyu_common as common

STATUS_COL = 14        # N 列（1 基）
FIRST_DATA_ROW = 2
COL_COUNT = 18


def open_books(excel=None):
    """返回 (读 sheet, 写 workbook, 写 sheet)；写 workbook 负责 save。"""
    path = excel or common.EXCEL
    read_wb = openpyxl.load_workbook(path, data_only=True)
    write_wb = openpyxl.load_workbook(path)
    return read_wb.active, write_wb, write_wb.active


def set_status(write_wb, ws, row, text, excel=None):
    """写状态列并立即落盘（画布 157/158、168/175/180、185 的落盘语义）。"""
    ws.cell(row=row, column=STATUS_COL).value = text
    write_wb.save(excel or common.EXCEL)


def row_vals(read_ws, row):
    """1 基列 1..18 → 0 基列表（与画布 loop_excel[索引] 对齐）。"""
    return [read_ws.cell(row=row, column=c).value for c in range(1, COL_COUNT + 1)]


def cell(row, idx):
    v = row[idx] if idx < len(row) else None
    return "" if v is None else v


def read_status(read_ws, row):
    return str(read_ws.cell(row=row, column=STATUS_COL).value or "").strip()


def iter_pending(read_ws):
    """逐行给 (行号, 商品ID, 状态)，跳过全空行；状态过滤由调用方决定。"""
    for rn in range(FIRST_DATA_ROW, read_ws.max_row + 1):
        pid = read_ws.cell(row=rn, column=1).value
        status = read_status(read_ws, rn)
        if not pid and not status:
            continue
        yield rn, pid, status


def main(args=None):
    """自检入口：只读，列出待上架行（不写盘、不连浏览器）。"""
    read_ws, _wb, _ws = open_books()
    pending = [(rn, pid) for rn, pid, st in iter_pending(read_ws) if st == common.ST_QUEUED]
    return {"excel": common.EXCEL, "rows": read_ws.max_row, "pending": pending}
