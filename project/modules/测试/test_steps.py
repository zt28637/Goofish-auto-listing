# -*- coding: utf-8 -*-
"""节点测试：上架各步骤（上传/描述/分类/价格/发货/发布/判定回写）。"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

import fakes  # noqa: F401  （加载路径垫片）

import xianyu_common as common
import xianyu_upload as upload
import xianyu_desc as desc
import xianyu_category as category
import xianyu_price as price
import xianyu_shipping as shipping
import xianyu_publish as publish
import xianyu_verdict as verdict

ROW = ["P005", "TPE瑜伽垫", "", "瑜伽垫/安踏/轻微使用痕迹/189/TPE", "", "", 35, 69, "包邮", "", "",
       r"F:\Products\P005\套图", "描述文本", "待上架"]


class _Quiet(unittest.TestCase):
    def setUp(self):
        self._ev = mock.patch.object(common, "event")
        self._lg = mock.patch.object(common, "log")
        self._ev.start()
        self._lg.start()

    def tearDown(self):
        self._ev.stop()
        self._lg.stop()


class TestUpload(_Quiet):
    def test_rejects_empty_folder(self):
        tmp = tempfile.mkdtemp()
        try:
            row = list(ROW)
            row[11] = tmp
            with self.assertRaises(RuntimeError):
                upload.upload_images(fakes.FakePage(), row)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_sorts_files(self):
        tmp = tempfile.mkdtemp()
        try:
            for name in ("02.jpg", "01.jpg"):
                open(os.path.join(tmp, name), "w").close()
            up = fakes.FakeEle()
            page = fakes.FakePage(ele_map={upload.ELEM["文件上传"][0]: up})
            row = list(ROW)
            row[11] = tmp
            with mock.patch("time.sleep"):
                upload.upload_images(page, row)
            self.assertEqual([os.path.basename(p) for p in up.inputs[0]], ["01.jpg", "02.jpg"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestDesc(_Quiet):
    def test_types_ctrl_a_then_text(self):
        box = fakes.FakeEle()
        page = fakes.FakePage(ele_map={desc.ELEM["描述输入框"][0]: box})
        with mock.patch("time.sleep"):
            desc.fill_description(page, ROW)
        self.assertEqual(page.actions.typed[0], (common.keys().CONTROL, "a"))
        self.assertEqual(page.actions.typed[1], "描述文本")


class FakeLabel:
    def __init__(self, title):
        self._t = title

    def attr(self, name):
        return self._t if name == "title" else ""

    @property
    def text(self):
        return self._t


class FakeOpt:
    def __init__(self, text, on_pick):
        self.text = text
        self.clicks = 0
        self._on_pick = on_pick
        self.states = type("S", (), {"is_displayed": True})()

    def click(self, **kw):
        self.clicks += 1
        self._on_pick(self.text)


class FakeSelect:
    def __init__(self, item, page):
        self.item = item
        self.page = page
        self.clicks = 0

    def click(self, **kw):
        self.clicks += 1
        self.page.open_item = self.item       # 打开后，页面上能看到这个字段的选项

    def ele(self, loc, timeout=None):
        return self.item.search_box if "input" in loc else None


class FakeFormItem:
    def __init__(self, label, options, page, current=""):
        self.label = label
        self.current = current
        self.page = page
        self.select = FakeSelect(self, page)
        self.search_box = object()
        self.option_objs = [FakeOpt(o, self._pick) for o in options]

    def _pick(self, text):
        self.current = text

    @property
    def text(self):
        return self.label + " " + self.current

    def ele(self, loc, timeout=None):
        if "label" in loc:
            return FakeLabel(self.label)
        if "ant-select" in loc:
            return self.select
        return None


class CatPage(fakes.FakePage):
    def __init__(self, items):
        super().__init__()
        self.items = items
        self.open_item = None

    def eles(self, loc, **kw):
        if "ant-form-item" in loc:
            return self.items
        if loc in ("css:.ant-select-item-option", "css:[class*=option]"):
            return self.open_item.option_objs if self.open_item else []
        return []


class TestCategory(_Quiet):
    def setUp(self):
        super().setUp()
        self._ow = category.OPTION_WAIT
        category.OPTION_WAIT = 0.2

    def tearDown(self):
        category.OPTION_WAIT = self._ow
        super().tearDown()

    def _page(self, values, options=None):
        options = options or {
            "分类": ["瑜伽垫", "健腹轮"],
            "品牌": ["ANTA/安踏", "奥义"],
            "成色": ["全新", "轻微使用痕迹"],
            "长度": ["180-189cm", "190-199cm"],
            "材质": ["TPE", "PU橡胶"],
        }
        items = [FakeFormItem(f, options.get(f, []), None) for f in category.FIELDS]
        page = CatPage(items)
        for it in items:
            it.select.page = page
        return page, items

    def test_fills_five_fields_in_order(self):
        page, items = self._page({})
        with mock.patch("time.sleep"):
            self.assertTrue(category.choose_category(page, ROW))
        self.assertEqual([it.current for it in items],
                         ["瑜伽垫", "ANTA/安踏", "轻微使用痕迹", "180-189cm", "TPE"])

    def test_skips_field_already_correct(self):
        page, items = self._page({})
        items[0].current = "瑜伽垫"          # 分类已经是目标值
        with mock.patch("time.sleep"):
            self.assertTrue(category.choose_category(page, ROW))
        self.assertEqual(items[0].select.clicks, 0)
        self.assertEqual(items[1].select.clicks, 1)

    def test_fails_when_option_missing(self):
        page, items = self._page({}, options={
            "分类": ["瑜伽垫"], "品牌": ["ANTA/安踏"], "成色": ["全新"],
            "长度": ["180-189cm"], "材质": [],          # 材质下拉里没有 TPE
        })
        with mock.patch("time.sleep"):
            self.assertFalse(category.choose_category(page, ROW))

    def test_extra_segments_are_ignored(self):
        row = list(ROW)
        row[3] = "瑜伽垫/安踏/轻微使用痕迹/189/TPE/多余段"
        page, _items = self._page({})
        with mock.patch("time.sleep"):
            self.assertTrue(category.choose_category(page, row))


class TestPrice(_Quiet):
    def test_types_price_then_original(self):
        p = fakes.FakeEle()
        o = fakes.FakeEle()
        page = fakes.FakePage(ele_map={price.ELEM["价格输入框"][0]: p,
                                       price.ELEM["原价输入框"][0]: o})
        price.fill_price(page, ROW)
        self.assertEqual(page.actions.typed, ["35", "69"])


class TestShipping(_Quiet):
    def test_four_branches(self):
        for text, key in (("包邮", "包邮按钮"), ("按距离计费", "按距离计费"),
                          ("一口价", "一口价"), ("无需邮寄", "无需邮寄")):
            el = fakes.FakeEle()
            page = fakes.FakePage(ele_map={shipping.ELEM[key][0]: el})
            row = list(ROW)
            row[8] = text
            with mock.patch("time.sleep"):
                shipping.set_shipping(page, row)
            self.assertEqual(el.clicks, 1, text)

    def test_pickup_appended(self):
        base = fakes.FakeEle()
        pickup = fakes.FakeEle()
        page = fakes.FakePage(ele_map={shipping.ELEM["包邮按钮"][0]: base,
                                       shipping.ELEM["支持自提"][0]: pickup})
        row = list(ROW)
        row[8] = "包邮，支持自提"
        with mock.patch("time.sleep"):
            shipping.set_shipping(page, row)
        self.assertEqual((base.clicks, pickup.clicks), (1, 1))


class TestPublish(_Quiet):
    def test_dry_does_not_click(self):
        btn = fakes.FakeEle()
        page = fakes.FakePage(ele_map={publish.ELEM["发布"][0]: btn})
        self.assertEqual(publish.publish(page, "P005", dry_run=True), "dry")
        self.assertEqual(btn.clicks, 0)

    def test_real_run_clicks_once(self):
        btn = fakes.FakeEle()
        page = fakes.FakePage(ele_map={publish.ELEM["发布"][0]: btn})
        with mock.patch("time.sleep"):
            self.assertEqual(publish.publish(page, "P005"), "clicked")
        self.assertEqual(btn.clicks, 1)


class TestVerdict(_Quiet):
    def setUp(self):
        super().setUp()
        self._rec = mock.patch.object(verdict, "_record")
        self._rec.start()

    def tearDown(self):
        self._rec.stop()
        super().tearDown()

    def _page(self, success_el=None, publish_el=None):
        return fakes.FakePage(ele_map={verdict.ELEM["咸鱼ID"][0]: success_el,
                                       verdict.ELEM["发布"][0]: publish_el})

    def test_success_anchor(self):
        self.assertEqual(verdict.judge(self._page(fakes.FakeEle(), fakes.FakeEle()), "P005"), "success")

    def test_success_by_item_url(self):
        page = self._page(None, None)
        page.url = "https://www.goofish.com/item?id=1096805699542"
        self.assertEqual(verdict.judge(page, "P005"), "success")

    def test_failed_anchor_clicks_again(self):
        btn = fakes.FakeEle()
        self.assertEqual(verdict.judge(self._page(None, btn), "P005"), "failed")
        self.assertEqual(btn.clicks, 1)          # 补点一次（画布 174）

    def test_unknown_anchor(self):
        self.assertEqual(verdict.judge(self._page(None, None), "P005"), "unknown")

    def test_success_records_ledger(self):
        verdict.judge(self._page(fakes.FakeEle(), fakes.FakeEle()), "P005")
        verdict._record.assert_called_with("P005", "success")


class TestSingleStepEntry(unittest.TestCase):
    """每个步骤都能单独当流程跑：无参数=自检，带 row=真跑。"""

    def test_selfcheck_returns_step_number(self):
        import xianyu_login as login
        mods = {login: 1, upload: 2, desc: 3, category: 4, price: 5,
                shipping: 6, publish: 7, verdict: 8}
        for mod, step in mods.items():
            self.assertEqual(mod.main(None)["step"], step, mod.__name__)

    def test_args_from_argv(self):
        args = common.args_from_argv(
            ["x.py", "--row", "6", "--pid", "P005", "--open", "--confirm-publish", "--write"])
        self.assertEqual(args["excel_row"], 6)
        self.assertEqual(args["pid"], "P005")
        self.assertTrue(args["open"] and args["confirm_publish"] and args["write"])

    def test_step_row_accepts_explicit_values(self):
        row = list(range(18))
        self.assertEqual(common.step_row({"row": row}), row)

    def test_step_row_requires_a_source(self):
        with self.assertRaises(RuntimeError):
            common.step_row({})


class TestRegistries(unittest.TestCase):
    """每个步骤自己持有元素表；新增步骤时这里会提醒。"""

    def test_each_step_has_own_elements(self):
        import xianyu_login as login
        steps = {"login": login, "upload": upload, "desc": desc, "price": price,
                 "shipping": shipping, "publish": publish, "verdict": verdict}
        for name, mod in steps.items():
            reg = getattr(mod, "ELEM", None)
            self.assertIsInstance(reg, dict, name)
            self.assertTrue(reg, name)
            for key, cands in reg.items():
                self.assertIsInstance(cands, list, "%s.%s" % (name, key))
                self.assertTrue(all(isinstance(c, str) and c for c in cands), "%s.%s" % (name, key))
        self.assertTrue(category.FIELDS)


class FakeCell:
    def __init__(self, store, key):
        self.store, self.key = store, key
        self.value = None


class FakeWs:
    def __init__(self):
        self.cells = {}

    def cell(self, row, column):
        cell = FakeCell(self.cells, (row, column))
        self.cells[(row, column)] = cell
        return cell


class TestApply(_Quiet):
    def _run(self, state, dry=False):
        ws = FakeWs()
        led = mock.Mock()
        status = verdict.apply(state, 2, "P005", mock.Mock(), ws, led, dry)
        return status, ws.cells, led

    def test_success(self):
        status, cells, led = self._run("success")
        self.assertEqual(status, common.ST_OK)
        self.assertEqual(cells[(2, 14)].value, common.ST_OK)
        led.confirm.assert_called_once()

    def test_failed(self):
        status, cells, _l = self._run("failed")
        self.assertEqual(status, common.ST_FAIL)
        self.assertEqual(cells[(2, 14)].value, common.ST_FAIL)

    def test_unknown(self):
        status, cells, led = self._run("unknown")
        self.assertEqual(status, common.ST_UNKNOWN)
        self.assertEqual(cells[(2, 14)].value, common.ST_UNKNOWN)
        self.assertEqual(led.confirm.call_args[0][1], "unknown")

    def test_dry_writes_nothing(self):
        status, cells, led = self._run("dry", dry=True)
        self.assertEqual(status, "dry")
        self.assertEqual(cells, {})
        self.assertFalse(led.confirm.called)


if __name__ == "__main__":
    unittest.main()
