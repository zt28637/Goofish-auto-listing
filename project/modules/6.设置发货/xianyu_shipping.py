# -*- coding: utf-8 -*-
"""上架步骤 6 · 发货设置（影刀 CodeFlow：xianyu_shipping）

画布 139-153：包邮 / 按距离计费 / 一口价 / 无需邮寄 四分支（else 静默走无需邮寄），
含「支持自提」则追加勾选。
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
    "包邮按钮": ["xpath:/html/body/div[2]/div[2]/div[1]/form[1]/div[1]/div[5]/div[2]/div[1]/div[1]/div[1]/div[1]/label[1]/span[1]/input[1]",
                 "text=包邮"],
    "按距离计费": ["xpath:/html/body/div[2]/div[2]/div[1]/form[1]/div[1]/div[5]/div[2]/div[1]/div[1]/div[1]/div[1]/label[2]/span[1]/input[1]",
                   "text=按距离计费"],
    "一口价": ["xpath:/html/body/div[2]/div[2]/div[1]/form[1]/div[1]/div[5]/div[2]/div[1]/div[1]/div[1]/div[1]/label[3]/span[1]/input[1]",
               "text=一口价"],
    "无需邮寄": ["xpath:/html/body/div[2]/div[2]/div[1]/form[1]/div[1]/div[5]/div[2]/div[1]/div[1]/div[1]/div[1]/label[4]/span[1]/input[1]",
                 "text=无需邮寄"],
    "支持自提": ["xpath:/html/body/div[2]/div[2]/div[1]/form[1]/div[1]/div[5]/div[2]/div[1]/div[1]/div[1]/button[1]/span[1]",
                 "text=支持自提"],
}



def set_shipping(page, row):
    ship = str(excel.cell(row, 8))          # 索引 8 = 发货设置
    if "包邮" in ship:
        ui_action.click(page, ELEM, "包邮按钮")
    elif "按距离计费" in ship:
        ui_action.click(page, ELEM, "按距离计费")
    elif "一口价" in ship:
        ui_action.click(page, ELEM, "一口价")
    else:
        ui_action.click(page, ELEM, "无需邮寄")     # 画布 else：静默走无需邮寄（预检 warn 兜底）
    time.sleep(1)
    if "支持自提" in ship:
        ui_action.click(page, ELEM, "支持自提")
    time.sleep(1)


def main(args=None):
    """单步测试入口。无 args=离线自检；args 带 row/excel_row 才连浏览器真跑。"""
    if not args:
        return {"step": 6, "name": "set_shipping", "source_col": 8}
    try:
        page = common.step_browser(args)
        row = common.step_row(args)
        set_shipping(page, row)
        return {"ok": True, "step": 6, "row": args.get("excel_row")}
    except Exception as e:
        common.log("[单步] 设置发货 失败：%s" % e)
        return {"ok": False, "step": 6, "error": str(e)}




if __name__ == "__main__":
    import json
    import sys as _argv_sys
    print(json.dumps(main(common.args_from_argv(_argv_sys.argv)), ensure_ascii=False, indent=1))
