# -*- coding: utf-8 -*-
"""上架步骤 8 · 成败判定与状态回写（影刀 CodeFlow：xianyu_verdict）

画布 164-185：
  · 判「页面含咸鱼ID元素」=成功（toast 不可信）
  · 发布按钮仍在=失败，补点一次（画布 174 原样保留）
  · 其余=不明
  · 三路回写状态列 N（168/175/180）→ 保存（185）→ 台账 confirm

Publish|verdict 事件必须与 verdict 同步落，崩溃后才能区分「确定没发」与「结果未知」。
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

import xianyu_common as common
import ui_action
import xianyu_excel as excel

# 本步骤的元素
ELEM = {
    "咸鱼ID": ["xpath:/html/body/div[2]/div[2]/div[1]/div[1]/a[1]/div[1]/div[2]/div[1]/div[1]"],
    "发布": ["xpath:/html/body/div[2]/div[2]/div[2]/button[1]", "css:button[type=submit]"],
}




def _record(pid, result):
    """台账只做数据记录：成功/失败/不明都写一条，供事后统计；不参与拦截。"""
    try:
        import sys
        if common.TOOLS_DIR and common.TOOLS_DIR not in sys.path:
            sys.path.insert(0, common.TOOLS_DIR)
        import ledger
        ledger.confirm(str(pid), result if result in ("success", "failed") else "unknown",
                       run_id=common.RUN_ID)
    except Exception as e:
        common.log("[台账] 记录失败（不影响上架）：%s" % e)


def judge(page, pid):
    """返回 'success' | 'failed' | 'unknown'。

    2026-11-09 实测：发布成功后页面直接跳到 /item?id=<商品ID>，
    这比「页头咸鱼ID元素」更稳定，作为第一锚；失败/不明再按原锚兜底。
    """
    url = page.url or ""
    if "/item" in url:                                # 跳商品页 = 发布成功
        common.event("PUBLISH|verdict", pid=pid, result="success")
        _record(pid, "success")
        return "success"
    if page.ele(ELEM["咸鱼ID"][0], timeout=3):        # 旧锚兜底
        common.event("PUBLISH|verdict", pid=pid, result="success")
        _record(pid, "success")
        return "success"
    if page.ele(ELEM["发布"][0], timeout=2):          # 发布按钮还在 = 失败，补点一次
        common.log("[判定] 发布按钮仍在，补点一次（画布 174 原样保留）")
        try:
            page.ele(ELEM["发布"][0]).click()
        except Exception:
            pass
        common.event("PUBLISH|verdict", pid=pid, result="failed")
        _record(pid, "failed")
        return "failed"
    common.event("PUBLISH|verdict", pid=pid, result="unknown")
    _record(pid, "unknown")
    return "unknown"


def apply(state, rn, pid, write_wb, write_ws, led, dry_run):
    """按判定结果写状态列 + 台账，返回中文状态串（dry 原样返回）。"""
    if state == "dry":
        return "dry"
    status = {"success": common.ST_OK, "failed": common.ST_FAIL}.get(state, common.ST_UNKNOWN)
    if not dry_run:
        excel.set_status(write_wb, write_ws, rn, status)
        try:
            led.confirm(str(pid), state if state in ("success", "failed") else "unknown",
                        run_id=common.RUN_ID)
        except Exception:
            pass
    common.event("count_" + state, pid=pid, result=state)
    return status


def main(args=None):
    """单步测试入口。无 args=离线自检；args 带 row/excel_row 才连浏览器真跑。"""
    if not args:
        return {"step": 8, "name": "judge+apply", "anchors": [ELEM["咸鱼ID"][0], ELEM["发布"][0]]}
    try:
        page = common.step_browser(args)
        v = judge(page, args.get("pid") or "TEST")
        return {"ok": True, "step": 8, "verdict": v}
    except Exception as e:
        common.log("[单步] 判定 失败：%s" % e)
        return {"ok": False, "step": 8, "error": str(e)}




if __name__ == "__main__":
    import json
    import sys as _argv_sys
    print(json.dumps(main(common.args_from_argv(_argv_sys.argv)), ensure_ascii=False, indent=1))
