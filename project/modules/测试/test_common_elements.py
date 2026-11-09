# -*- coding: utf-8 -*-
"""节点测试：common（路径/状态/事件日志）+ elements（注册表/自愈/重试）。"""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import fakes  # noqa: F401  （加载路径垫片）
import xianyu_common as common
import ui_action


class TestCommonConstants(unittest.TestCase):
    def test_status_enums_match_canvas(self):
        self.assertEqual(common.ST_QUEUED, "待上架")
        self.assertEqual(common.ST_RUNNING, "上架中")
        self.assertEqual(common.ST_OK, "上架成功")
        self.assertEqual(common.ST_FAIL, "上架失败")
        self.assertEqual(common.ST_UNKNOWN, "上架情况不明，待人工确认")
        self.assertEqual(common.ST_LOGIN_LOST, "中断·登录失效")

    def test_project_root_and_excel_resolution(self):
        self.assertTrue(common.PROJECT_ROOT.endswith("2-电商上架自动化"))
        self.assertTrue(os.path.isabs(common.EXCEL))


class TestEventLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_dir, self._old_fp = common.LOG_DIR, common._events_fp
        common.LOG_DIR, common._events_fp = self.tmp, None

    def tearDown(self):
        if common._events_fp is not None:
            common._events_fp.close()
        common.LOG_DIR, common._events_fp = self._old_dir, self._old_fp
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_event_writes_jsonl(self):
        common.event("row_start", row=6, pid="P005")
        common.event("PUBLISH|verdict", pid="P005", result="success")
        lines = open(os.path.join(self.tmp, "events.jsonl"), encoding="utf-8").read().splitlines()
        self.assertEqual(len(lines), 2)
        first = json.loads(lines[0])
        self.assertEqual(first["kind"], "row_start")
        self.assertEqual(first["row"], 6)
        self.assertEqual(json.loads(lines[1])["result"], "success")


REG = {"A": ["text:不存在", "css:.x"]}


class TestElements(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        self._lg = mock.patch.object(common, "log")
        self._lg.start()

    def tearDown(self):
        self._lg.stop()

    def test_pick_falls_back_to_next_candidate(self):
        el = object()
        page = fakes.FakePage(ele_map={REG["A"][1]: el})
        self.assertIs(ui_action.pick(page, REG, "A", timeout=0.1), el)

    def test_pick_required_raises_when_all_missing(self):
        with self.assertRaises(RuntimeError):
            ui_action.pick(fakes.FakePage(), REG, "A", timeout=0.1)

    def test_pick_optional_returns_none(self):
        self.assertIsNone(ui_action.pick(fakes.FakePage(), REG, "A", timeout=0.1, required=False))

    def test_click_clicks_once(self):
        el = fakes.FakeEle()
        page = fakes.FakePage(ele_map={REG["A"][1]: el})
        ui_action.click(page, REG, "A")
        self.assertEqual(el.clicks, 1)

    def test_fill_sets_value(self):
        el = fakes.FakeEle()
        page = fakes.FakePage(ele_map={REG["A"][1]: el})
        with mock.patch("time.sleep"):
            ui_action.fill(page, REG, "A", "35")
        self.assertEqual(el.value, "35")
        self.assertEqual(el.clicks, 1)

    def test_wait_stable_returns_stable_value(self):
        import itertools
        seq = itertools.chain([[], ["x"], ["x"], ["x"]], itertools.repeat(["x"]))
        with mock.patch("time.sleep"):
            got = ui_action.wait_stable(lambda: next(seq), need=2)
        self.assertEqual(got, ["x"])


if __name__ == "__main__":
    unittest.main()
