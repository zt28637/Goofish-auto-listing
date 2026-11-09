# -*- coding: utf-8 -*-
"""页面交互工具（影刀 CodeFlow：ui_action）

对应项目一的 `model/tool/ui_action.py`：只解决一件事——**DrissionPage 的元素会过期**。
页面局部刷新后，手里的元素句柄就作废；人的做法是「每次操作前重新看一眼」，
本文件把这套动作固化下来。

与项目一版本的差异：
  · 这里传入的是「步骤自己的 ELEM 注册表 + 键名」，支持一条键多个候选定位符（自愈）
  · 保留 pick / click；补齐 fill（输入后回读确认）与 wait_stable（等页面稳定）
  · 元素表归各步骤自己维护，本文件不持有任何元素

用法：
    import ui_action
    ui_action.click(page, ELEM, "发布")
    ui_action.fill(page, ELEM, "价格输入框", "35")
    wait_stable(lambda: len(page.eles("css:.ant-select-item-option")))
"""

import time

# 这两类异常的意思是「页面变了，手里的元素作废了」，可以重查重试
TRANSIENT_NAMES = ("ElementLostError", "ContextLostError", "ElementNotFoundError")


def _transient():
    from DrissionPage.errors import ElementLostError, ContextLostError, ElementNotFoundError
    return (ElementLostError, ContextLostError, ElementNotFoundError)


def pick(doc, registry, key, timeout=8, required=True):
    """按 registry[key] 的候选顺序找元素，第一个命中即返回；全不中时 required 决定抛错或返回 None。"""
    cands = registry[key] if isinstance(registry[key], list) else [registry[key]]
    for i, loc in enumerate(cands):
        t = timeout if i == len(cands) - 1 else 2
        try:
            el = doc.ele(loc, timeout=t)
        except Exception:
            el = None
        if el:
            if i:
                import xianyu_common as common
                common.log("[自愈] %s 第%d候选命中：%s" % (key, i + 1, loc))
            return el
    if required:
        raise RuntimeError("元素「%s」全部候选落空：%s" % (key, cands))
    return None


def click(doc, registry, key, timeout=8, retries=1):
    """找到 → 点击；元素被 SPA 换掉时重查再点。"""
    last = None
    for _ in range(retries + 1):
        el = pick(doc, registry, key, timeout=timeout)
        try:
            el.click()
            return el
        except _transient() as e:
            last = e
            time.sleep(0.3)
    raise RuntimeError("「%s」连点%d轮都被 SPA 换掉：%s" % (key, retries + 1, last))


def fill(doc, registry, key, text, timeout=8, retries=1):
    """点一下 → 清空 → 输入 → 回读确认；回读不一致也当失败重试。"""
    text = str(text)
    last = None
    for _ in range(retries + 1):
        el = pick(doc, registry, key, timeout=timeout)
        try:
            el.click()
            el.clear()
            el.input(text)
            if (el.value or "") != text:
                raise RuntimeError("填值未生效：期望 %r，实际 %r" % (text, el.value))
            return el
        except _transient() + (RuntimeError,) as e:
            last = e
            time.sleep(0.3)
    raise RuntimeError("「%s」填写失败：%s" % (key, last))


def hover(doc, registry, key, timeout=8, retries=1):
    last = None
    for _ in range(retries + 1):
        el = pick(doc, registry, key, timeout=timeout)
        try:
            el.hover()
            return el
        except _transient() as e:
            last = e
            time.sleep(0.3)
    raise RuntimeError("「%s」悬停失败：%s" % (key, last))


def wait_stable(read, timeout=12, sample=0.5, need=2, require_nonempty=True):
    """反复调用 read()，连续 need 次结果相同才算稳定；返回稳定值（超时返回最后一次读数）。

    read 必须是函数（每次重新读），不是某一瞬间的数据：
        wait_stable(lambda: len(page.eles("css:.ant-select-item-option")))   ✅
        wait_stable(len(page.eles("css:.ant-select-item-option")))           ❌
    """
    start = time.time()
    previous = None
    same = 0
    while time.time() - start < timeout:
        time.sleep(sample)
        current = read()
        if require_nonempty and not current:
            previous, same = current, 0
            continue
        same = same + 1 if current == previous else 0
        if same >= need:
            return current
        previous = current
    return previous


def main(args=None):
    return {"api": "pick/click/fill/hover(doc, registry, key) + wait_stable(read)"}
