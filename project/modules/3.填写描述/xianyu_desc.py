# -*- coding: utf-8 -*-
"""上架步骤 3 · 描述写入（影刀 CodeFlow：xianyu_desc）

画布 052-056：点 contenteditable → Ctrl+A 清场 → 输入描述（列索引 12）。
清场必须做：编辑器会保留上一件草稿，不清就是追加两遍。
"""

# ---- 仓库内跨文件夹 import 垫片（影刀 CodeFlow 是平铺的，这段在影刀里空转）----
import os as _os
import sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__)) if "__file__" in globals() else ""
if _HERE and _HERE not in _sys.path:          # 影刀运行时不把应用目录放进来
    _sys.path.insert(0, _HERE)
_ROOT = _os.path.dirname(_HERE) if _HERE else ""
for _d in ("tool", "1.登录", "2.上传套图", "3.填写描述", "4.选择分类",
           "5.填写价格", "6.设置发货", "7.发布", "8.判定回写"):
    _p = _os.path.join(_ROOT, _d) if _ROOT else ""
    if _p and _os.path.isdir(_p) and _p not in _sys.path:
        _sys.path.insert(0, _p)

import os as _os
import sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__)) if "__file__" in globals() else ""
if _HERE and _HERE not in _sys.path:      # 影刀运行时不把应用目录放进来
    _sys.path.insert(0, _HERE)
for _root in (_HERE, _os.path.dirname(_HERE) if _HERE else ""):
    for _d in ("tool", "0.打开浏览器", "1.登录", "2.上传套图", "3.填写描述",
               "4.选择分类", "5.填写价格", "6.设置发货", "7.发布", "8.判定回写", "9.编排"):
        _p = _os.path.join(_root, _d) if _root else ""
        if _p and _p not in _sys.path:
            _sys.path.insert(0, _p)

import time

import xianyu_common as common
import ui_action
import xianyu_excel as excel

# 本步骤的元素
ELEM = {
    "描述输入框": [
        "xpath:/html/body/div[2]/div[2]/div[1]/form[1]/div[1]/div[2]/div[1]/div[1]/div[2]/div[1]/div[1]/div[1]/div[1]",
        "css:[contenteditable=true]",
    ],
}



def fill_description(page, row):
    ui_action.click(page, ELEM, "描述输入框", timeout=20)
    time.sleep(1)
    page.actions.type((common.keys().CONTROL, "a"))            # 清场
    page.actions.type(str(excel.cell(row, 12)), interval=0.05)  # 索引 12 = 描述
    time.sleep(1)


def main(args=None):
    """单步测试入口。无 args=离线自检；args 带 row/excel_row 才连浏览器真跑。"""
    if not args:
        return {"step": 3, "name": "fill_description", "source_col": 12}
    try:
        page = common.step_browser(args)
        row = common.step_row(args)
        fill_description(page, row)
        return {"ok": True, "step": 3, "row": args.get("excel_row")}
    except Exception as e:
        common.log("[单步] 填写描述 失败：%s" % e)
        return {"ok": False, "step": 3, "error": str(e)}




if __name__ == "__main__":
    import json
    import sys as _argv_sys
    print(json.dumps(main(common.args_from_argv(_argv_sys.argv)), ensure_ascii=False, indent=1))
