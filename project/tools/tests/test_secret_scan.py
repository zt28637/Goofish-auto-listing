# -*- coding: utf-8 -*-
"""凭据扫描回归测试

重点回归两件事：
- 真凭据形态必须命中（手机号 / 赋值型密码 / cookie / 私钥）
- 已知不误报：环境变量名、测试占位号、文档里的字段名与占位值
"""
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import secret_scan as ss


def kinds(text):
    return [h["kind"] for h in ss.scan_text(text)]


class TestSecretScan(unittest.TestCase):
    def test_clean_text(self):
        text = "import os\npassword = os.environ.get('XIANYU_PASSWORD')\n"
        self.assertEqual(kinds(text), [])

    def test_real_mobile_detected(self):
        hits = ss.scan_text("联系方式 13912345678")
        self.assertEqual([h["kind"] for h in hits], ["mobile"])

    def test_allowlisted_mobile(self):
        self.assertEqual(kinds("13800000000 / 13812345678"), [])

    def test_masked_mobile_not_hit(self):
        self.assertEqual(kinds("152****4727"), [])

    def test_password_assignment(self):
        hits = ss.scan_text('password = "hunter2xyz"')
        self.assertEqual([h["kind"] for h in hits], ["secret"])

    def test_json_secret_assignment(self):
        self.assertEqual(kinds('{"token": "abcdef123456"}'), ["secret"])

    def test_placeholder_not_hit(self):
        for text in ('password = "your_password"',
                     '{"password": "x" * 10}',
                     'XIANYU_PASSWORD=abc123',
                     'password: "***MASKED***"'):
            self.assertEqual(kinds(text), [], text)

    def test_private_key(self):
        self.assertIn("private_key", kinds("-----BEGIN RSA PRIVATE KEY-----"))

    def test_cookie_value(self):
        self.assertIn("cookie", kinds("Cookie: unb=2200000001; other=1"))
        self.assertEqual(kinds("if \"unb\" in ck or n.startswith(\"_nk_\")"), [])

    def test_mask_keeps_ends(self):
        self.assertEqual(ss.mask("13912345678"), "139***78")
        self.assertEqual(ss.mask("abc"), "***")


if __name__ == "__main__":
    unittest.main()
