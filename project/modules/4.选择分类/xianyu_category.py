# -*- coding: utf-8 -*-
"""上架步骤 4 · 分类选择（影刀 CodeFlow：xianyu_category）

2026-11-09 现网页面的口径（与 11-07 的级联不同，已在工作日志留证据）：
    分类 / 品牌 / 成色 / 长度 / 材质   —— 五个独立下拉框
    Excel 列索引 3 的路径段，按顺序一一对应：
        瑜伽垫 / 安踏 / 轻微使用痕迹 / 189 / TPE
        → 分类   品牌            成色      长度   材质

做法：
  1. 按标签找到字段 → 已选中目标值就跳过（幂等）
  2. 点开下拉 → 搜索框输入目标值（过滤长列表）
  3. 在可见选项里找「包含目标值」的第一项并点击
  4. 五个字段都填上才算成功；任一目标值点不到 → 该行判失败（回写上架失败并跳过）

为什么用「包含」而不是相等：页面选项带前缀/区间
    安踏 → ANTA/安踏，189 → 180-189cm，TPE → TPE
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

# Excel 路径段 → 页面字段（顺序固定，多出来的段忽略并告警）
FIELDS = ["分类", "品牌", "成色", "长度", "材质"]

# 下拉选项（antd）：先试标准类名，再退回模糊匹配；选项出现是异步的，用轮询等
OPTION_WAIT = 5
OPTION_LOCATORS = ["css:.ant-select-item-option", "css:[class*=option]"]


def choose_category(page, row):
    """按路径逐字段选择。返回 True=全部填好；False=有目标值没点中。"""
    path = [p.strip() for p in str(excel.cell(row, 3)).split("/") if p.strip()]
    if not path:
        raise RuntimeError("分类路径为空")

    if len(path) > len(FIELDS):
        common.log("[分类] 路径段比字段多，忽略多余段：%s" % path[len(FIELDS):])

    for label, target in zip(FIELDS, path):
        if not _select_field(page, label, target):
            common.log("[分类] 字段「%s」没选中「%s」，该行判失败" % (label, target))
            return False
        common.log("[分类] %s = %s" % (label, target))
    return True


def _form_item(page, label):
    """按标签找表单项：label 的 title/text == 字段名。"""
    for item in page.eles("css:.ant-form-item"):
        lab = item.ele("tag:label", timeout=0.3)
        if not lab:
            continue
        name = (lab.attr("title") or lab.text or "").strip()
        if name == label:
            return item
    return None


def _select_field(page, label, target):
    """一个字段：已选对就跳过；否则点开 → 搜索 → 轮询候选选项 → 点中 → 重新取字段复核。"""
    for _attempt in range(2):
        item = _form_item(page, label)
        if item is None:
            common.log("[分类] 页面没有「%s」字段" % label)
            return False
        if target in (item.text or ""):
            return True                                   # 幂等：已经是这个值

        select = item.ele("css:.ant-select", timeout=3)
        if select is None:
            common.log("[分类] 「%s」不是下拉框" % label)
            return False
        select.click()
        time.sleep(0.5)

        box = select.ele("tag:input", timeout=1)          # 搜索框：输入可过滤长列表
        if box:
            try:
                page.actions.type(str(target), interval=0.05)
            except Exception:
                pass

        if _click_option(page, target, timeout=OPTION_WAIT):
            time.sleep(0.5)
            fresh = _form_item(page, label)               # 点完页面会重建，必须重新取
            if fresh and target in (fresh.text or ""):
                return True
            common.log("[分类] 已点选项，但「%s」复核仍未生效，重试" % label)
        _escape(page)
        time.sleep(0.3)
    return False


def _click_option(page, target, timeout=None):
    """轮询等选项出现：过滤/重建是异步的，固定等待会撞空列表。"""
    end = time.time() + (OPTION_WAIT if timeout is None else timeout)
    while time.time() < end:
        for loc in OPTION_LOCATORS:
            for opt in page.eles(loc):
                if target in (opt.text or "") and _visible(opt):
                    opt.click()
                    return True
        time.sleep(0.3)
    return False


def _visible(el):
    try:
        return el.states.is_displayed
    except Exception:
        return True


def _escape(page):
    try:
        page.actions.type(common.keys().ESCAPE)
    except Exception:
        pass


def main(args=None):
    """单步测试入口。无 args=离线自检；args 带 row/excel_row 才连浏览器真跑。"""
    if not args:
        return {"step": 4, "name": "choose_category", "fields": FIELDS}
    try:
        page = common.step_browser(args)
        row = common.step_row(args)
        ok = choose_category(page, row)
        if not ok:
            return {"ok": False, "step": 4}
        return {"ok": True, "step": 4, "row": args.get("excel_row")}
    except Exception as e:
        common.log("[单步] 选择分类 失败：%s" % e)
        return {"ok": False, "step": 4, "error": str(e)}




if __name__ == "__main__":
    import json
    import sys as _argv_sys
    print(json.dumps(main(common.args_from_argv(_argv_sys.argv)), ensure_ascii=False, indent=1))
