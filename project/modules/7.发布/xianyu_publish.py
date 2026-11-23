# -*- coding: utf-8 -*-
"""上架步骤 7 · 点发布（影刀 CodeFlow：xianyu_publish）

画布 155-163：
  PUBLISH|begin（块 156）→ 写「上架中」并落盘由编排层在调用前完成
  PUBLISH|click（块 159）→ 点发布（块 160）→ 等加载完成（块 161）→ 等 2s（块 162）

只负责「点」；判定与回写在 xianyu_verdict。
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

import sys

import xianyu_common as common
import ui_action

# 本步骤的元素
ELEM = {
    "发布": ["xpath:/html/body/div[2]/div[2]/div[2]/button[1]", "css:button[type=submit]"],
}



def publish(page, pid, dry_run=False):
    """返回 'clicked' | 'dry'。台账只做记录，不在这里拦截（2026-11-09 定调）。"""
    common.event("PUBLISH|begin", pid=pid)
    if dry_run:
        common.log("[发布] dry_run：不点发布")
        return "dry"
    common.event("PUBLISH|click", pid=pid)
    ui_action.click(page, ELEM, "发布", timeout=20)          # 画布 160
    try:
        page.wait.doc_loaded(timeout=15)              # 画布 161
    except Exception:
        pass
    time.sleep(2)                                     # 画布 162
    return "clicked"


def main(args=None):
    """单步测试入口。无 args=离线自检；args 带 row/excel_row 才连浏览器真跑。

    state 是画布判断「是否点过发布」的唯一依据：
      clicked=已点（之后结果只分成功/不明）· dry=没点 · click_failed=点击抛错（按没点处理）
    """
    if not args:
        return {"step": 7, "name": "publish"}
    try:
        page = common.step_browser(args)
        state = publish(page, args.get("pid") or "TEST",
                        dry_run=not args.get("confirm_publish"))
        return {"ok": True, "step": 7, "state": state}
    except Exception as e:
        common.log("[单步] 发布 失败：%s" % e)
        return {"ok": False, "step": 7, "state": "click_failed", "error": str(e)}




if __name__ == "__main__":
    import json
    import sys as _argv_sys
    print(json.dumps(main(common.args_from_argv(_argv_sys.argv)), ensure_ascii=False, indent=1))
