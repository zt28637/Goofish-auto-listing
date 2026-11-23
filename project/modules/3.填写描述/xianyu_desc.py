# -*- coding: utf-8 -*-
"""上架步骤 3 · 描述写入（影刀 CodeFlow：xianyu_desc）

画布 052-056：点 contenteditable → Ctrl+A 清场 → 输入描述（列索引 12）。
清场必须做：编辑器会保留上一件草稿，不清就是追加两遍。
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

import time

import xianyu_common as common
import ui_action
import xianyu_excel as excel

# 本步骤的元素
ELEM = {
    # 2026-11-17 实测：绝对 XPath 主候选已漂移，css 候选才是当前命中的那个；
    # 语义定位优先，绝对路径仅作兜底（pick 按顺序试）。
    "描述输入框": [
        "css:[contenteditable=true]",
        "xpath:/html/body/div[2]/div[2]/div[1]/form[1]/div[1]/div[2]/div[1]/div[1]/div[2]/div[1]/div[1]/div[1]/div[1]",
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
