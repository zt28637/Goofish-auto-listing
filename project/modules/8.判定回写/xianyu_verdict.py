# -*- coding: utf-8 -*-
"""上架步骤 8 · 成败判定与状态回写（影刀 CodeFlow：xianyu_verdict）

画布 164-185：
  · URL 跳到 /item = 成功（第一锚，2026-11-09 实测）
  · 「页面含咸鱼ID元素」= 成功（旧锚兜底；toast 不可信）
  · 发布按钮仍在 = 补点一次，补点后轮询跳转；仍不能确认 = 不明
  · **点过发布之后不写「失败」**：失败只属于点发布之前的步骤（2026-11-17 口径）
  · 三路回写状态列 N（168/175/180）→ 保存（185）→ 台账 confirm

Publish|verdict 事件必须与 verdict 同步落，崩溃后才能区分「确定没发」与「结果未知」。
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


RETRY_WAIT = 5.0          # 补点后等页面跳转的窗口（秒）；只认成功/不明


def _done(pid, result):
    """一条判定只落一次：结构化事件 + 台账。"""
    common.event("PUBLISH|verdict", pid=pid, result=result)
    _record(pid, result)
    return result


def _poll_item(page, seconds=RETRY_WAIT, step=0.5):
    """轮询 URL 是否跳到商品页；补点后页面可能异步跳转，不能只等固定 2s。"""
    end = time.time() + max(0.0, seconds)
    while True:
        if "/item" in (page.url or ""):
            return True
        if time.time() >= end:
            return False
        time.sleep(step)


def judge(page, pid, retry=True):
    """返回 'success' | 'unknown'；**点过发布后不再返回 'failed'**。

    口径（2026-11-17）：失败只在「能证明没发出去」时写——那是点发布之前的事。
    点过发布而无法确认（按钮仍在、无跳转），一律 'unknown'，交人工核对；
    盲判 failed 会诱发人工重排，直接制造重复 listing。

    2026-11-09 实测：发布成功后页面直接跳到 /item?id=<商品ID>，
    这比「页头咸鱼ID元素」更稳定，作为第一锚；失败/不明再按原锚兜底。
    """
    if "/item" in (page.url or ""):                    # 跳商品页 = 发布成功
        return _done(pid, "success")
    if page.ele(ELEM["咸鱼ID"][0], timeout=3):         # 旧锚兜底
        return _done(pid, "success")
    if page.ele(ELEM["发布"][0], timeout=2):           # 发布按钮还在 = 点击可能没生效
        if not retry:
            common.log("[判定] 发布按钮仍在；按口径不补点，结果不明")
            return _done(pid, "unknown")
        common.log("[判定] 发布按钮仍在，补点一次；补点后只认成功/不明")
        try:
            page.ele(ELEM["发布"][0]).click()
        except Exception as e:
            common.log("[判定] 补点失败：%s" % e)
            return _done(pid, "unknown")
        if _poll_item(page):                           # 补点可能慢，轮询而不是定睡
            return _done(pid, "success")
        return _done(pid, "unknown")
    return _done(pid, "unknown")


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
    """单步测试入口。无 args=离线自检；args 带 row/excel_row 才连浏览器真跑。

    异常也必须带 verdict 键：画布取 判定结果['verdict']，缺键会抛 KeyError
    被 Catch 兜成「上架失败」——而点过发布之后，真实答案是「不明」。
    """
    if not args:
        return {"step": 8, "name": "judge+apply", "anchors": [ELEM["咸鱼ID"][0], ELEM["发布"][0]]}
    pid = args.get("pid") or "TEST"
    try:
        page = common.step_browser(args)
        v = judge(page, pid)
        return {"ok": True, "step": 8, "verdict": v}
    except Exception as e:
        common.log("[单步] 判定 失败：%s" % e)
        _done(pid, "unknown")
        return {"ok": False, "step": 8, "verdict": "unknown", "error": str(e)}




if __name__ == "__main__":
    import json
    import sys as _argv_sys
    print(json.dumps(main(common.args_from_argv(_argv_sys.argv)), ensure_ascii=False, indent=1))
