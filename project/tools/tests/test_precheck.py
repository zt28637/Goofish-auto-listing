"""precheck 回归测试（S2）

用例来源：2026-11-07 实测数据与故障。
- test_phone_watch_not_contact：P002 描述含「儿童电话手表」→ 不能被 DESC_CONTACT 误杀
- test_scan_learns_depth：从「上架成功」行自学习层数，层数不符 → WARN 而非 FAIL

运行：python -m unittest discover -s project/tools/tests -v
    或 python -m pytest project/tools/tests -q
"""
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import openpyxl

import precheck

TMP = Path(tempfile.mkdtemp(prefix="precheck_test_"))


def img_dir(name="ok", files=("01.jpg", "02.png")):
    d = TMP / name
    d.mkdir(parents=True, exist_ok=True)
    for f in files:
        (d / f).write_bytes(b"x")
    return str(d)


def make_vals(cat="智能手表/小天才/Z6", price="89", orig="159", directory=None,
              desc="自用九成新，功能正常", status="待上架"):
    """18 列（0 起索引）的一行，只填测试关心的几列。"""
    vals = [None] * 18
    vals[precheck.COL_ID] = "P001"
    vals[precheck.COL_CAT] = cat
    vals[precheck.COL_PRICE] = price
    vals[precheck.COL_ORIG] = orig
    vals[precheck.COL_DIR] = directory or img_dir(cat.replace("/", "_") + price)
    vals[precheck.COL_DESC] = desc
    vals[precheck.COL_STATUS] = status
    return vals


class TestHappyPath(unittest.TestCase):
    def test_clean_row_passes(self):
        fails, warns = precheck.check_row(make_vals())
        self.assertEqual(fails, [])
        self.assertEqual(warns, [])


class TestCategory(unittest.TestCase):
    def test_empty(self):
        fails, _ = precheck.check_row(make_vals(cat=""))
        self.assertIn("CAT_EMPTY", fails)

    def test_empty_segment(self):
        fails, _ = precheck.check_row(make_vals(cat="服饰//抓夹"))
        self.assertIn("CAT_EMPTYSEG", fails)

    def test_fullwidth_slash(self):
        """全角 ／ 不会被 "/" 拆开 → 影刀级联必挂。"""
        fails, _ = precheck.check_row(make_vals(cat="发饰／DIY／全新／抓夹"))
        self.assertIn("CAT_FULLWIDTH", fails)

    def test_fullwidth_backslash(self):
        fails, _ = precheck.check_row(make_vals(cat="发饰＼DIY＼全新"))
        self.assertIn("CAT_FULLWIDTH", fails)

    def test_halfwidth_space_is_tolerated(self):
        """级联是子串匹配，" DIY" 里的前导空格不影响命中 → 不拦。"""
        fails, _ = precheck.check_row(make_vals(cat="发饰/ DIY/ 抓夹"))
        self.assertNotIn("CAT_FULLWIDTH", fails)

    def test_depth_mismatch_is_warn_not_fail(self):
        """同根品类历史成功过 7 级，来了个 4 级 → 只警告，不阻断。"""
        fails, warns = precheck.check_row(make_vals(cat="智能手表/小天才"),
                                          seen_depths={"智能手表": {7}})
        self.assertEqual(fails, [])
        self.assertTrue(any(w.startswith("CAT_DEPTH:") for w in warns))

    def test_depth_match_no_warn(self):
        _, warns = precheck.check_row(make_vals(cat="智能手表/小天才/Z6"),
                                      seen_depths={"智能手表": {3}})
        self.assertEqual(warns, [])


class TestPrice(unittest.TestCase):
    def test_empty(self):
        fails, _ = precheck.check_row(make_vals(price=""))
        self.assertIn("PRICE_EMPTY", fails)

    def test_not_number(self):
        fails, _ = precheck.check_row(make_vals(price="12元"))
        self.assertIn("PRICE_BAD", fails)

    def test_zero(self):
        fails, _ = precheck.check_row(make_vals(price="0"))
        self.assertIn("PRICE_NONPOS", fails)

    def test_orig_lower_than_price(self):
        fails, _ = precheck.check_row(make_vals(price="199", orig="19.9"))
        self.assertTrue(any(f.startswith("PRICE_ORDER:") for f in fails))

    def test_orig_not_number(self):
        fails, _ = precheck.check_row(make_vals(price="199", orig="原价"))
        self.assertIn("PRICE_ORIG_BAD", fails)

    def test_orig_empty_is_ok(self):
        fails, _ = precheck.check_row(make_vals(orig=""))
        self.assertEqual(fails, [])

    def test_extreme_is_warn(self):
        fails, warns = precheck.check_row(make_vals(price="199000", orig=""))
        self.assertEqual(fails, [])
        self.assertTrue(any(w.startswith("PRICE_EXTREME:") for w in warns))


class TestImageDir(unittest.TestCase):
    def test_empty_dir(self):
        fails, _ = precheck.check_row(make_vals(directory=img_dir("empty", files=())))
        self.assertIn("EMPTY_DIR", fails)

    def test_no_dir(self):
        fails, _ = precheck.check_row(make_vals(directory=str(TMP / "not_exist")))
        self.assertIn("NO_DIR", fails)

    def test_non_image_file(self):
        """画布块 045 用 *.* 全量上传，混进 txt 会被传上去。"""
        fails, _ = precheck.check_row(make_vals(directory=img_dir("mixed", ("01.jpg", "说明.txt"))))
        self.assertTrue(any(f.startswith("IMG_BAD:") for f in fails))

    def test_only_images_ok(self):
        fails, _ = precheck.check_row(make_vals(directory=img_dir("imgs", ("a.JPG", "b.webp"))))
        self.assertEqual(fails, [])


class TestDescription(unittest.TestCase):
    def test_empty(self):
        fails, _ = precheck.check_row(make_vals(desc=""))
        self.assertIn("DESC_EMPTY", fails)

    def test_too_long(self):
        fails, _ = precheck.check_row(make_vals(desc="字" * 1501))
        self.assertTrue(any(f.startswith("DESC_LONG:") for f in fails))

    def test_phone_watch_not_contact(self):
        """★实测回归：P002 的商品名是「儿童电话手表」，不能被当成留了联系方式。"""
        desc = "自用儿童电话手表Z6pro翻转摄像头和视频通话功能正常 定位精准 电池耐用"
        fails, _ = precheck.check_row(make_vals(desc=desc))
        self.assertEqual([f for f in fails if f.startswith("DESC_CONTACT")], [])

    def test_phone_number_blocked(self):
        fails, _ = precheck.check_row(make_vals(desc="有意者联系 13812345678"))
        self.assertTrue(any(f.startswith("DESC_CONTACT:手机号") for f in fails))

    def test_wechat_blocked(self):
        fails, _ = precheck.check_row(make_vals(desc="加微信：abc_12345 详聊"))
        self.assertTrue(any(f.startswith("DESC_CONTACT:微信号") for f in fails))

    def test_qq_blocked(self):
        fails, _ = precheck.check_row(make_vals(desc="QQ:123456789"))
        self.assertTrue(any(f.startswith("DESC_CONTACT:QQ号") for f in fails))

    def test_bare_word_wechat_ok(self):
        """只说「微信」（无账号）不算——避免误伤。"""
        fails, _ = precheck.check_row(make_vals(desc="微信同号，支持验机"))
        self.assertEqual([f for f in fails if f.startswith("DESC_CONTACT")], [])


class TestScan(unittest.TestCase):
    """整表扫描：自学习层数 + tag 分级。"""

    def setUp(self):
        self.xlsx = TMP / "清单.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append([f"列{i}" for i in range(18)])
        ok = make_vals(cat="智能手表/小天才/Z6/蓝牙连接/35/蓝牙通话/全新", status="上架成功")
        pending_same = make_vals(cat="智能手表/小天才/Z6", status="待上架")
        for v in (ok, pending_same):
            ws.append(v)
        wb.save(self.xlsx)

    def test_learns_depth_from_successful_rows(self):
        rows, err = precheck.scan(self.xlsx)
        self.assertIsNone(err)
        self.assertEqual(len(rows), 2)
        # 第 2 行是「上架成功」的 7 级，给同根品类立了标杆
        # 第 3 行只有 3 级 → WARN（不阻断）
        _, pid, tag, fails, warns, _ = rows[1]
        self.assertEqual(tag, "WARN")
        self.assertEqual(fails, [])
        self.assertTrue(any(w.startswith("CAT_DEPTH:") for w in warns))

    def test_render_summary_counts(self):
        rows, _ = precheck.scan(self.xlsx)
        text, n_fail, n_warn = precheck.render(rows)
        self.assertEqual(n_fail, 0)
        self.assertEqual(n_warn, 1)
        self.assertIn("warn=1", text)

    def test_return_dict_has_warn_key(self):
        d = precheck.precheck(str(self.xlsx))
        self.assertFalse(d["aborted"])
        self.assertIn("warn", d)
        self.assertIn("warnings", d)
        self.assertEqual(d["fail"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
