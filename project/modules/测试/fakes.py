# -*- coding: utf-8 -*-
"""节点测试共用假对象：FakePage / FakeEle / FakeActions。

原则：测试只验本仓逻辑（分支、守卫、状态映射），不碰真实浏览器；
     页面行为用最小实现模拟，元素定位由各步骤自己的 ELEM 提供。
"""

import os
import sys

# 与各模块同款路径垫片：让测试目录能 import 兄弟模块
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
for _d in ("tool", "0.打开浏览器", "1.登录", "2.上传套图", "3.填写描述",
               "4.选择分类", "5.填写价格", "6.设置发货", "7.发布", "8.判定回写", "9.编排"):
    _p = os.path.join(_ROOT, _d)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)


class FakeScroll:
    def __init__(self):
        self.seen = 0

    def to_see(self):
        self.seen += 1


class FakeActions:
    def __init__(self):
        self.typed = []

    def type(self, value, interval=None):
        self.typed.append(value)


class FakeWait:
    def __init__(self, displayed_map=None):
        self.displayed_map = displayed_map or {}
        self.doc_loaded_calls = 0

    def doc_loaded(self, timeout=15):
        self.doc_loaded_calls += 1
        return True

    def ele_displayed(self, loc, timeout=2):
        return bool(self.displayed_map.get(loc, False))


class FakeEle:
    def __init__(self, text="", cls="", children=None, on_click=None):
        self.text = text
        self._cls = cls
        self._children = children or []
        self._on_click = on_click
        self.clicks = 0
        self.inputs = []
        self.value = ""
        self.scroll = FakeScroll()
        self.wait = FakeWait()

    def attr(self, name):
        return self._cls if name == "class" else ""

    def click(self, **kw):
        self.clicks += 1
        if self._on_click:
            self._on_click(self)

    def child(self, index=1, **kw):
        if 1 <= index <= len(self._children):
            return self._children[index - 1]
        return None

    def parent(self):
        return FakeEle()

    def eles(self, loc, **kw):
        return []

    def ele(self, loc, timeout=None, **kw):
        return None

    def clear(self):
        self.value = ""

    def hover(self):
        self.hovered = True

    def input(self, value, **kw):
        self.inputs.append(value if isinstance(value, str) else list(value))
        if isinstance(value, str):
            self.value = value


class FakePage:
    """loc → 元素 / 元素列表 / None；未登记的一律 None（等价「找不到」）。"""

    def __init__(self, ele_map=None, eles_map=None, cookies=None):
        self.cookie_list = cookies or []
        self.ele_map = ele_map or {}
        self.eles_map = eles_map or {}
        self.actions = FakeActions()
        self.wait = FakeWait()
        self.got = []
        self.url = "about:blank"

    def ele(self, loc, timeout=None, **kw):
        v = self.ele_map.get(loc)
        if callable(v):
            return v()
        return v

    def eles(self, loc, **kw):
        v = self.eles_map.get(loc)
        if callable(v):
            return v()
        return v or []

    def cookies(self, all_domains=False):
        return self.cookie_list

    def get(self, url):
        self.got.append(url)
        self.url = url

    def get_screenshot(self, **kw):
        return True

    @property
    def html(self):
        return ""
