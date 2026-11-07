"""台账（防重复发布）与运行前体检的回归测试（S3）

重点回归两件真实事故：
- test_duplicate_detected：P001 被重复发布过 → 台账必须能查出来
- test_lock_blocks：WPS 占用清单文件 → 体检必须 BLOCK
"""
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import openpyxl

import ledger
import preflight

TMP = Path(tempfile.mkdtemp(prefix="s3_test_"))


def make_images(name, files=("01_主图_正面.jpg", "02_主图_45度.jpg")):
    d = TMP / name
    d.mkdir(parents=True, exist_ok=True)
    for f in files:
        (d / f).write_bytes(f.encode("utf-8") * 10)
    return str(d)


def make_xlsx(path, headers=None, rows=()):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers or [f"列{i}" for i in range(18)])
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


def row18(pid="P001", cat="发饰/DIY", directory="", status="待上架"):
    v = [None] * 18
    v[0], v[3], v[11], v[13] = pid, cat, directory, status
    return v


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.db = TMP / f"ledger_{self._testMethodName}.jsonl"
        ledger.LEDGER = self.db          # 测试隔离，不碰真实台账

    def test_cover_hash_is_content_based(self):
        a = ledger.cover_hash(make_images("h1"))
        b = ledger.cover_hash(make_images("h2"))          # 同样内容、不同目录
        self.assertEqual(a, b)
        c = make_images("h3", ("x.jpg",))
        self.assertNotEqual(a, ledger.cover_hash(c))

    def test_first_image_sorted_by_name(self):
        d = make_images("sort", ("b.jpg", "a.jpg"))
        self.assertEqual(ledger.first_image(d).name, "a.jpg")

    def test_first_image_missing_dir(self):
        self.assertIsNone(ledger.first_image(str(TMP / "nope")))
        self.assertEqual(ledger.cover_hash(str(TMP / "nope")), "")

    def test_duplicate_detected_by_id(self):
        """P001 被重复发布过 —— 这是台账存在的理由。"""
        ledger.append({"商品ID": "P001", "首图hash": "", "结果": "上架成功"})
        hits = ledger.check("P001")
        self.assertEqual(len(hits), 1)

    def test_not_duplicate_for_new_id(self):
        ledger.append({"商品ID": "P001", "首图hash": "aaa", "结果": "上架成功"})
        self.assertEqual(ledger.check("P002", cover="bbb"), [])

    def test_duplicate_by_cover(self):
        """换了 ID 但用的是同一张首图 → 仍提示。"""
        h = ledger.cover_hash(make_images("cover"))
        ledger.append({"商品ID": "P900", "首图hash": h, "结果": "上架成功"})
        self.assertTrue(ledger.check("P901", cover=h))

    def test_bad_line_tolerated(self):
        self.db.write_text('{"商品ID":"A"}\n不是json\n', encoding="utf-8")
        self.assertEqual(len(ledger.load()), 1)

    def test_seed_is_idempotent(self):
        d = make_images("seed")
        xlsx = make_xlsx(TMP / "seed.xlsx", rows=[
            row18("P001", directory=d, status="上架成功"),
            row18("P002", directory=d, status="待上架"),     # 未成功，不该入账
        ])
        first = ledger.seed_from_excel(xlsx)
        self.assertEqual(first["added"], ["P001"])
        second = ledger.seed_from_excel(xlsx)              # 再跑一次
        self.assertEqual(second["added"], [])
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(len(ledger.load()), 1)


class TestPreflight(unittest.TestCase):
    def setUp(self):
        self.cred = TMP / f"cred_{self._testMethodName}.json"
        preflight.CONF = self.cred
        ledger.LEDGER = TMP / f"pf_{self._testMethodName}.jsonl"

    def test_credentials_missing(self):
        level, _, _ = preflight.check_credentials()
        self.assertEqual(level, preflight.BLOCK)

    def test_credentials_ok(self):
        import json
        self.cred.write_text(json.dumps({"phone": "13800000000", "password": "x" * 10}), encoding="utf-8")
        level, _, detail = preflight.check_credentials()
        self.assertEqual(level, preflight.OK)
        self.assertIn("11 位", detail)

    def test_credentials_missing_field(self):
        """改密后最容易只改一半 —— 必须 BLOCK。"""
        self.cred.write_text('{"phone":"13800000000"}', encoding="utf-8")
        level, _, detail = preflight.check_credentials()
        self.assertEqual(level, preflight.BLOCK)
        self.assertIn("password", detail)

    def test_headers_ok(self):
        xlsx = make_xlsx(TMP / "hdr_ok.xlsx", headers=[
            "商品ID", "", "", "分类路径", "", "", "价格", "原价", "发货设置", "", "", "套图目录", "描述", "状态",
        ])
        level, _, _ = preflight.check_headers(xlsx)
        self.assertEqual(level, preflight.OK)

    def test_headers_drift_blocks(self):
        """上游插了一列 —— 影刀按列号读会静默串列。"""
        # 上游在最前面插了一列 → 后面所有列右移一位，分类路径跑到索引 4
        xlsx = make_xlsx(TMP / "hdr_bad.xlsx", headers=[
            "商品ID", "新增列", "", "", "分类路径", "", "", "价格", "原价", "发货设置", "", "", "套图目录", "描述", "状态",
        ])
        level, _, detail = preflight.check_headers(xlsx)
        self.assertEqual(level, preflight.BLOCK)
        self.assertIn("列6", detail)

    def test_lock_blocks_when_office_running(self):
        d = TMP / "lockdir"
        d.mkdir(exist_ok=True)
        x = d / "商品清单.xlsx"
        x.write_bytes(b"x")
        (d / "~$商品清单.xlsx").write_bytes(b"lock")
        orig = preflight._office_processes
        preflight._office_processes = lambda: [(1234, "wps.exe")]
        try:
            level, _, _ = preflight.check_lock(x)
        finally:
            preflight._office_processes = orig
        self.assertEqual(level, preflight.BLOCK)

    def test_stale_lock_is_only_warning(self):
        d = TMP / "staledir"
        d.mkdir(exist_ok=True)
        x = d / "商品清单.xlsx"
        x.write_bytes(b"x")
        (d / "~$商品清单.xlsx").write_bytes(b"lock")
        orig = preflight._office_processes
        preflight._office_processes = lambda: []
        try:
            level, _, _ = preflight.check_lock(x)
        finally:
            preflight._office_processes = orig
        self.assertEqual(level, preflight.WARN)

    def test_residue_detected(self):
        rows = [(2, "P001", "发饰/DIY", "上架中"), (3, "P002", "发饰/DIY", "待上架")]
        level, _, detail = preflight.check_residue(rows)
        self.assertEqual(level, preflight.WARN)
        self.assertIn("P001", detail)

    def test_ledger_gap_warns(self):
        rows = [(2, "P001", "发饰/DIY", "上架成功")]
        level, _, detail = preflight.check_ledger(rows)
        self.assertEqual(level, preflight.WARN)
        self.assertIn("ledger.py seed", detail)

    def test_ledger_covered_is_ok(self):
        ledger.append({"商品ID": "P001", "首图hash": "", "结果": "上架成功"})
        rows = [(2, "P001", "发饰/DIY", "上架成功")]
        level, _, _ = preflight.check_ledger(rows)
        self.assertEqual(level, preflight.OK)


if __name__ == "__main__":
    unittest.main(verbosity=2)
