# -*- coding: utf-8 -*-
"""上架步骤 5 · 价格与原价（影刀 CodeFlow：xianyu_price）

画布 132-138：先滚动价格框到可视区 → 点售价输列索引 6 → 点原价输列索引 7。
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

import xianyu_common as common
import ui_action
import xianyu_excel as excel

# 本步骤的元素
ELEM = {
    "价格输入框": [
        "xpath:/html/body/div[2]/div[2]/div[1]/form[1]/div[1]/div[3]/div[2]/div[1]/div[1]/div[1]/div[2]/div[1]/div[1]/span[1]/input[1]",
        "css:input[placeholder='0.00']",
    ],
    "原价输入框": [
        "xpath:/html/body/div[2]/div[2]/div[1]/form[1]/div[1]/div[3]/div[2]/div[1]/div[2]/div[1]/div[2]/div[1]/div[1]/span[1]/input[1]",
    ],
}



def fill_price(page, row):
    ui_action.pick(page, ELEM, "价格输入框", timeout=20).scroll.to_see()   # 画布 133 先滚动
    ui_action.click(page, ELEM, "价格输入框")
    page.actions.type(str(excel.cell(row, 6)), interval=0.05)       # 索引 6 = 售价
    ui_action.click(page, ELEM, "原价输入框")
    page.actions.type(str(excel.cell(row, 7)), interval=0.05)       # 索引 7 = 原价


def main(args=None):
    """单步测试入口。无 args=离线自检；args 带 row/excel_row 才连浏览器真跑。"""
    if not args:
        return {"step": 5, "name": "fill_price", "cols": [6, 7]}
    try:
        page = common.step_browser(args)
        row = common.step_row(args)
        fill_price(page, row)
        return {"ok": True, "step": 5, "row": args.get("excel_row")}
    except Exception as e:
        common.log("[单步] 填写价格 失败：%s" % e)
        return {"ok": False, "step": 5, "error": str(e)}




if __name__ == "__main__":
    import json
    import sys as _argv_sys
    print(json.dumps(main(common.args_from_argv(_argv_sys.argv)), ensure_ascii=False, indent=1))
