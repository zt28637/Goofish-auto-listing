# -*- coding: utf-8 -*-
"""上架步骤 2 · 套图上传（影刀 CodeFlow：xianyu_upload）

画布 043-051：目录内 `*.*` 递归、按文件名升序、逐文件全量上传（不挑扩展名）。
目录为空直接熔断——空目录=假成功温床。
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
from pathlib import Path

import xianyu_common as common
import ui_action
import xianyu_excel as excel

# 本步骤的元素
ELEM = {
    # 2026-11-17 实测：原主候选 tag:input@@type=file 已随改版漂移，
    # css 候选才是当前命中的那个；保留旧候选兜底（pick 按顺序试）。
    "文件上传": ["css:input[type=file]", "tag:input@@type=file"],
}



def _wait_publish_ready(page, timeout=30):
    """等发布页真正就绪再找上传控件。

    2026-11-23 实测（Edge 144→158 升级后）：登录层 `goto(发布页)` 返回时 DOM 尚未就绪，
    随后立刻找 `input[type=file]` 会在 20s 内全部落空——元素其实存在，只是页面还在导航。
    判据用「URL 到位 + document.readyState=complete」；超时不抛错，让后面的 pick 继续试。
    非发布页（单步其他页 / 测试用 Mock page）直接返回，不空转。
    """
    try:
        url = page.url
    except Exception:
        return
    if not isinstance(url, str) or "goofish.com/publish" not in url:
        return
    end = time.time() + timeout
    while time.time() < end:
        try:
            if page.run_js("return document.readyState") == "complete":
                return
        except Exception:
            pass
        time.sleep(0.5)
    common.log("[上传] 发布页 %ds 内未确认就绪，继续尝试查找元素" % timeout)


def upload_images(page, row):
    folder = str(excel.cell(row, 11))       # 索引 11 = 套图目录
    common.log("[上传] 套图目录：%s" % folder)
    common.event("upload_dir", dir=folder)
    files = sorted(str(p) for p in Path(folder).rglob("*.*"))
    if not files:
        raise RuntimeError("套图目录是空的：%s" % folder)
    for fp in files:
        common.event("upload_file", file=fp)
    _wait_publish_ready(page)
    uploader = ui_action.pick(page, ELEM, "文件上传", timeout=20)
    uploader.input(files)                   # 影刀逐个弹框=累加；DP 一次设全，末态一致
    time.sleep(1)


def main(args=None):
    """单步测试入口。无 args=离线自检；args 带 row/excel_row 才连浏览器真跑。"""
    if not args:
        return {"step": 2, "name": "upload_images", "source_col": 11}
    try:
        page = common.step_browser(args)
        row = common.step_row(args)
        upload_images(page, row)
        return {"ok": True, "step": 2, "row": args.get("excel_row")}
    except Exception as e:
        common.log("[单步] 上传套图 失败：%s" % e)
        return {"ok": False, "step": 2, "error": str(e)}




if __name__ == "__main__":
    import json
    import sys as _argv_sys
    print(json.dumps(main(common.args_from_argv(_argv_sys.argv)), ensure_ascii=False, indent=1))
