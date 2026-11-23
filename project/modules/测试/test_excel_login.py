# -*- coding: utf-8 -*-
"""节点测试：Excel 层（列映射/状态过滤/回写落盘）+ 登录层（判定/复检/凭据）。"""

import os
import shutil
import tempfile
import unittest

import fakes  # noqa: F401  （加载路径垫片）
import openpyxl

import xianyu_common as common
import xianyu_excel as excel
import xianyu_login as login


def _make_book(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=1, column=1).value = "商品ID"
    ws.cell(row=1, column=14).value = "状态"
    ws.cell(row=2, column=1).value = "P005"
    ws.cell(row=2, column=4).value = "瑜伽垫/安踏/轻微使用痕迹/189/TPE"
    ws.cell(row=2, column=6).value = 35
    ws.cell(row=2, column=7).value = 69
    ws.cell(row=2, column=8).value = "包邮"
    ws.cell(row=2, column=12).value = "P005/套图"
    ws.cell(row=2, column=13).value = "描述"
    ws.cell(row=2, column=14).value = "待上架"
    ws.cell(row=3, column=1).value = "P006"
    ws.cell(row=3, column=14).value = "上架成功"
    ws.cell(row=4, column=1).value = None       # 全空行
    wb.save(path)


class TestExcel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "清单.xlsx")
        _make_book(self.path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_iter_pending_skips_empty_rows(self):
        read_ws, _wb, _ws = excel.open_books(self.path)
        rows = list(excel.iter_pending(read_ws))
        self.assertEqual([r[0] for r in rows], [2, 3])
        self.assertEqual(rows[0][1], "P005")
        self.assertEqual(rows[0][2], "待上架")

    def test_row_vals_index_matches_canvas(self):
        read_ws, _wb, _ws = excel.open_books(self.path)
        row = excel.row_vals(read_ws, 2)
        self.assertEqual(len(row), 18)
        self.assertEqual(row[0], "P005")                       # A 列
        self.assertEqual(row[3], "瑜伽垫/安踏/轻微使用痕迹/189/TPE")  # 分类
        self.assertEqual(row[5], 35)                           # 价格
        self.assertEqual(row[13], "待上架")                     # N 列状态

    def test_cell_handles_short_and_none(self):
        self.assertEqual(excel.cell([None], 3), "")
        self.assertEqual(excel.cell(["x"], 0), "x")

    def test_set_status_writes_and_saves(self):
        _rw, write_wb, write_ws = excel.open_books(self.path)
        excel.set_status(write_wb, write_ws, 2, common.ST_RUNNING, excel=self.path)
        check = openpyxl.load_workbook(self.path, data_only=True).active
        self.assertEqual(check.cell(row=2, column=14).value, "上架中")
        self.assertEqual(check.cell(row=3, column=14).value, "上架成功")  # 不误伤别的行


class TestLogin(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        self._lg = mock.patch.object(common, "log")
        self._lg.start()

    def tearDown(self):
        self._lg.stop()

    def test_login_doc_none_when_no_frame(self):
        self.assertIsNone(login.login_doc(fakes.FakePage(), timeout=0.2))

    def test_login_doc_returns_frame_when_tab_visible(self):
        frame = fakes.FakeEle()
        frame.wait.displayed_map[login.ELEM["密码登录选项"][0]] = True
        page = fakes.FakePage(ele_map={common.LOGIN_FRAME[0]: frame})
        self.assertIs(login.login_doc(page, timeout=0.2), frame)

    def test_login_doc_none_when_frame_is_stale(self):
        """回归：已登录页面残留 iframe 时不得判成「要登录」。"""
        frame = fakes.FakeEle()          # 密码登录 tab 不可见
        page = fakes.FakePage(ele_map={common.LOGIN_FRAME[0]: frame})
        self.assertIsNone(login.login_doc(page, timeout=0.2))

    def test_is_logged_in_by_cookie(self):
        page = fakes.FakePage(cookies=[{"name": "unb", "domain": ".goofish.com"}])
        self.assertTrue(login.is_logged_in(page))

    def test_is_logged_in_by_form_when_no_cookie(self):
        page = fakes.FakePage(ele_map={login.ELEM["描述输入框"][0]: fakes.FakeEle()})
        self.assertTrue(login.is_logged_in(page))

    def test_is_logged_out_when_neither(self):
        self.assertFalse(login.is_logged_in(fakes.FakePage()))

    def test_check_alive_true_when_desc_visible(self):
        desc = fakes.FakeEle()
        page = fakes.FakePage(ele_map={login.ELEM["描述输入框"][-1]: desc})
        self.assertTrue(login.check_alive(page))

    def test_check_alive_false_when_desc_gone_and_login_visible(self):
        frame = fakes.FakeEle()
        frame.wait.displayed_map[login.ELEM["密码登录选项"][0]] = True
        page = fakes.FakePage(ele_map={common.LOGIN_FRAME[0]: frame})
        self.assertFalse(login.check_alive(page))

    def test_login_failure_reports_not_alive(self):
        """登录/浏览器失败必须显式 alive=False；画布默认值也按 False 判。"""
        from unittest import mock
        with mock.patch.object(login, "ensure_browser", return_value={"ok": False, "detail": "x"}):
            self.assertFalse(login.main({"check": True}).get("alive", False))
        with mock.patch.object(login, "ensure_browser", side_effect=RuntimeError("x")):
            self.assertFalse(login.main({"check": True}).get("alive", False))

    def test_goto_retries_and_reattaches(self):
        """冷启动断连：goto 应重连后重试，且返回新句柄。"""
        from unittest import mock

        class Flaky(fakes.FakePage):
            def __init__(self):
                super().__init__()
                self.attempts = 0

            def get(self, url, **kw):
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("PageDisconnectedError")
                return super().get(url, **kw)

        page = Flaky()
        with mock.patch.object(login, "_attach", return_value=page), \
                mock.patch.object(login.time, "sleep"):
            got = login.goto(page, common.PUBLISH_URL)
        self.assertIs(got, page)
        self.assertEqual(page.attempts, 2)
        self.assertEqual(page.got, [common.PUBLISH_URL])

    def test_goto_raises_after_retries(self):
        """重连也救不回来时必须抛错，不能假装打开成功。"""
        from unittest import mock

        class Dead(fakes.FakePage):
            def __init__(self):
                super().__init__()
                self.attempts = 0

            def get(self, url, **kw):
                self.attempts += 1
                raise RuntimeError("timeout")

        page = Dead()
        with mock.patch.object(login, "_attach", return_value=page), \
                mock.patch.object(login.time, "sleep"):
            with self.assertRaises(RuntimeError):
                login.goto(page, common.PUBLISH_URL, retries=2)
        self.assertEqual(page.attempts, 3)      # 1 次 + 2 次重试

    def test_load_credentials_env_and_missing(self):
        old = {k: os.environ.get(k) for k in ("XIANYU_PHONE", "XIANYU_PASSWORD")}
        try:
            os.environ["XIANYU_PHONE"] = "13800000000"
            os.environ["XIANYU_PASSWORD"] = "pw"
            self.assertEqual(login.load_credentials(), ("13800000000", "pw"))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        # 环境变量清掉后若本地凭据存在则不应抛；这里只断言「不会静默返回空」
        phone = os.environ.pop("XIANYU_PHONE", None)
        pwd = os.environ.pop("XIANYU_PASSWORD", None)
        try:
            got = login.load_credentials()
            self.assertTrue(got[0] and got[1])
        except RuntimeError:
            self.assertFalse(os.path.exists(common.CRED))   # 只有凭据文件真的不存在才允许抛
        finally:
            if phone is not None:
                os.environ["XIANYU_PHONE"] = phone
            if pwd is not None:
                os.environ["XIANYU_PASSWORD"] = pwd


if __name__ == "__main__":
    unittest.main()
