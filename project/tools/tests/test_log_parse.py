"""日志结构化回归测试（S3-3 / O3）

真实回归点：
- 影刀存在**两种**导出格式（BOM + 逗号毫秒 + 冒号 / 无 BOM + 点毫秒）
- 每件耗时靠「套图目录」行切分，最后一件以统计行为终点
"""
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import log_parse

TMP = Path(tempfile.mkdtemp(prefix="logparse_test_"))

FORMAT_A = """\ufeff[信息] [2026-11-07 10:21:00,168]: 开始执行...
[信息] [2026-11-07 10:21:00,170]: ROW   2 P001       PASS -    | cat=发饰/DIY price=19.9
[警告] [2026-11-07 10:21:00,171]: ROW   3 P002       FAIL CAT_EMPTY | cat= price=-
[信息] [2026-11-07 10:21:00,172]: SUMMARY total=2 pass=1 warn=0 fail=1
"""

FORMAT_B = """[信息] [2026-11-07 10:48:52.114] 开始执行...
[信息] [2026-11-07 10:48:52.200] F:\\proj\\products\\P001\\套图
[信息] [2026-11-07 10:48:55.200] F:\\proj\\products\\P001\\套图\\01.jpg
[信息] [2026-11-07 10:48:57.200] F:\\proj\\products\\P001\\套图\\02.jpg
[信息] [2026-11-07 10:49:00.200] 第1级已正确: 发饰，跳过
[信息] [2026-11-07 10:49:05.200] F:\\proj\\products\\P002\\套图
[信息] [2026-11-07 10:49:20.200] F:\\proj\\products\\P002\\套图\\原图.jpg
[信息] [2026-11-07 10:49:30.000] 上架成功数量：2
[警告] [2026-11-07 10:49:30.100] 上架失败数量：0
[警告] [2026-11-07 10:49:30.200] 上架不明情况数量：0
"""


def write(name, text):
    p = TMP / name
    p.write_text(text, encoding="utf-8")
    return p


class TestFormats(unittest.TestCase):
    def test_format_a_bom_comma_colon(self):
        events, summary = log_parse.parse_file(write("a.txt", FORMAT_A))
        self.assertEqual(summary["unparsed"], 0)
        self.assertEqual(len(events), 4)
        self.assertEqual(events[0]["ts"], "2026-11-07 10:21:00.168")

    def test_format_b_dot_no_colon(self):
        events, summary = log_parse.parse_file(write("b.txt", FORMAT_B))
        self.assertEqual(summary["unparsed"], 0)
        self.assertEqual(events[0]["ts"], "2026-11-07 10:48:52.114")

    def test_unparsed_lines_counted(self):
        p = write("c.txt", "[信息] [2026-11-07 10:21:00.100] ok\n这行不是日志格式\n")
        _, summary = log_parse.parse_file(p)
        self.assertEqual(summary["unparsed"], 1)


class TestClassify(unittest.TestCase):
    def test_row_start(self):
        ev = log_parse.classify(r"F:\p\products\P001\套图", "信息")
        self.assertEqual((ev["kind"], ev["pid"]), ("row_start", "P001"))

    def test_upload_file(self):
        ev = log_parse.classify(r"F:\p\products\P001\套图\01.jpg", "信息")
        self.assertEqual((ev["kind"], ev["pid"]), ("upload_file", "P001"))

    def test_precheck_row(self):
        ev = log_parse.classify("ROW   2 P001       FAIL CAT_EMPTY | cat=", "信息")
        self.assertEqual(ev["kind"], "precheck_row")
        self.assertEqual(ev["row"], 2)
        self.assertEqual(ev["tag"], "FAIL")
        self.assertEqual(ev["codes"], ["CAT_EMPTY"])

    def test_counts(self):
        self.assertEqual(log_parse.classify("上架成功数量：4", "信息")["kind"], "count_success")
        self.assertEqual(log_parse.classify("上架不明情况数量：0", "警告")["kind"], "count_unknown")

    def test_category_step(self):
        ev = log_parse.classify("第1级已正确: 发饰，跳过", "信息")
        self.assertEqual((ev["kind"], ev["level"]), ("category_step", 1))


class TestSummary(unittest.TestCase):
    def setUp(self):
        self.events, self.summary = log_parse.parse_file(write("sum.txt", FORMAT_B))

    def test_two_rows_detected(self):
        self.assertEqual([r["pid"] for r in self.summary["rows"]], ["P001", "P002"])

    def test_duration_uses_next_row_start(self):
        # P001: 10:48:52.200 → P002 起点 10:49:05.200 = 13.0s
        self.assertEqual(self.summary["rows"][0]["duration_s"], 13.0)

    def test_last_row_ends_at_counts(self):
        # P002: 10:49:05.200 → 上架成功数量 10:49:30.000 = 24.8s
        self.assertEqual(self.summary["rows"][1]["duration_s"], 24.8)

    def test_files_counted(self):
        self.assertEqual(self.summary["rows"][0]["files"], 2)
        self.assertEqual(self.summary["rows"][1]["files"], 1)

    def test_counts(self):
        self.assertEqual(self.summary["counts"]["count_success"], 2)
        self.assertEqual(self.summary["counts"]["count_fail"], 0)

    def test_total_duration(self):
        self.assertAlmostEqual(self.summary["duration_s"], 38.1, places=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
