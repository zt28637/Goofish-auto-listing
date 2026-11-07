"""块号引用校验回归测试（S1-3）

真实回归点：2026-11-07 分类段插入 28 块后，README 的「分类选择 056–102」
与「确认上架 126–132」全部过期，而只校验总块数的 check_truth_source 抓不到。
"""
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import check_block_refs

TMP = Path(tempfile.mkdtemp(prefix="blockrefs_test_"))

TRANSCRIPT = """001  打开网页  [web.create]
013  折叠开始  折叠区域名称=咸鱼登录  [programing.region]
030  折叠结束  [programing.endregion]
056  折叠开始  折叠区域名称=分类选择  [programing.region]
130  折叠结束  [programing.endregion]
154  折叠开始  折叠区域名称=确认上架  [programing.region]
160  折叠结束  [programing.endregion]
"""

README_OK = """# 项目
## 画布分区细节（块号对应转录）

| 区段 | 块号 | 内容 |
|------|------|------|
| 咸鱼登录 | 013–030 | 登录 |
| 分类选择 | 056–130 | 级联 |
| 确认上架 | 154–160 | 发布 |
| 回跳 | 180 | 跳回 |

## 其他章节
| 分类选择 | 001–002 | 不该被读到 |
"""

README_STALE = README_OK.replace("| 分类选择 | 056–130 |", "| 分类选择 | 056–102 |")


def write(name, text):
    p = TMP / name
    p.write_text(text, encoding="utf-8")
    return p


class TestParse(unittest.TestCase):
    def test_regions_parsed(self):
        r = check_block_refs.parse_regions(write("t.md", TRANSCRIPT))
        self.assertEqual(r["咸鱼登录"], (13, 30))
        self.assertEqual(r["分类选择"], (56, 130))

    def test_readme_rows_only_in_section(self):
        rows = check_block_refs.parse_readme_rows(write("r.md", README_OK))
        names = [n for n, _, _ in rows]
        self.assertIn("分类选择", names)
        self.assertEqual(len(rows), 4)          # 其他章节里的表不算
        self.assertEqual(dict((n, (a, b)) for n, a, b in rows)["回跳"], (180, None))


class TestCompare(unittest.TestCase):
    def setUp(self):
        self.regions = check_block_refs.parse_regions(write("t2.md", TRANSCRIPT))

    def test_all_match(self):
        rows = check_block_refs.parse_readme_rows(write("r2.md", README_OK))
        checks, problems = check_block_refs.compare(self.regions, rows, 185)
        self.assertEqual(problems, [])

    def test_stale_detected(self):
        """056–102 vs 实际 056–130 —— 今天真实发生过的漂移。"""
        rows = check_block_refs.parse_readme_rows(write("r3.md", README_STALE))
        checks, problems = check_block_refs.compare(self.regions, rows, 185)
        self.assertEqual(len(problems), 1)
        self.assertIn("分类选择", problems[0])
        self.assertIn("056–130", problems[0])

    def test_single_block_beyond_total_flagged(self):
        rows = [("回跳", 999, None)]
        _, problems = check_block_refs.compare(self.regions, rows, 185)
        self.assertTrue(problems)

    def test_unknown_section_skipped(self):
        rows = [("准备", 1, 8)]
        checks, problems = check_block_refs.compare(self.regions, rows, 185)
        self.assertEqual(problems, [])
        self.assertEqual(checks[0][0], "·")


if __name__ == "__main__":
    unittest.main(verbosity=2)
