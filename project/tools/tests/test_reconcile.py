"""两阶段台账 + 对账的回归测试（S3-4 / O2a）

核心回归：
- inflight / released **不能**被当成「已发布」（否则重复发布防护会误伤）
- 对账只按人的裁决回填，脚本不自动判定
"""
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import openpyxl

import ledger
import reconcile

TMP = Path(tempfile.mkdtemp(prefix="reconcile_test_"))
HEADERS = ["商品ID", "", "", "分类路径", "", "", "价格", "原价", "发货设置", "", "", "套图目录", "描述", "状态"]


def make_xlsx(name, rows):
    p = TMP / name
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for r in rows:
        v = [None] * 18
        v[0], v[3], v[6], v[11], v[12], v[13] = r
        ws.append(v)
    wb.save(p)
    return p


def read_status(p, row):
    return openpyxl.load_workbook(p, data_only=True).active.cell(row, 14).value


class TestLedgerState(unittest.TestCase):
    def setUp(self):
        ledger.LEDGER = TMP / f"l_{self._testMethodName}.jsonl"

    def test_claim_is_inflight(self):
        ledger.claim("P001", run_id="r1")
        self.assertEqual(ledger.current_state("P001"), "inflight")

    def test_confirm_after_claim(self):
        ledger.claim("P001", run_id="r1")
        ledger.confirm("P001", "上架成功")
        self.assertEqual(ledger.current_state("P001"), "confirmed")

    def test_release_supersedes_claim(self):
        ledger.claim("P001")
        ledger.release("P001", note="核对未发布")
        self.assertEqual(ledger.current_state("P001"), "released")

    def test_check_ignores_inflight(self):
        """★ 关键：还挂着 claim 的不算「发过」，否则没法重发。"""
        ledger.claim("P001")
        self.assertEqual(ledger.check("P001"), [])

    def test_check_ignores_released(self):
        ledger.claim("P001")
        ledger.release("P001")
        self.assertEqual(ledger.check("P001"), [])

    def test_check_hits_confirmed(self):
        ledger.confirm("P001", "上架成功")
        self.assertEqual(len(ledger.check("P001")), 1)

    def test_legacy_seed_record_counts_as_confirmed(self):
        """旧格式（无「事件」字段）要能兼容。"""
        ledger.append({"商品ID": "P900", "结果": "上架成功", "时间": "2026-11-07 20:00"})
        self.assertEqual(ledger.current_state("P900"), "confirmed")

    def test_inflight_respects_lease(self):
        ledger.append({"商品ID": "P777", "事件": "claim", "时间": "2026-01-01 00:00:00"})
        self.assertEqual([p for p, _ in ledger.inflight(lease_minutes=30)], ["P777"])

    def test_fresh_claim_not_listed(self):
        ledger.claim("P778")
        self.assertEqual(ledger.inflight(lease_minutes=30), [])


class TestReconcile(unittest.TestCase):
    def setUp(self):
        ledger.LEDGER = TMP / f"r_{self._testMethodName}.jsonl"

    def test_collect_finds_stuck_rows(self):
        p = make_xlsx("stuck.xlsx", [
            ("P001", "发饰/DIY", "19.9", "", "描述A", "上架中"),
            ("P002", "发饰/DIY", "20", "", "描述B", "待上架"),
        ])
        rows = reconcile.collect(p)
        self.assertEqual([r["pid"] for r in rows], ["P001"])
        self.assertEqual(rows[0]["row"], 2)

    def test_checklist_written(self):
        p = make_xlsx("cl.xlsx", [("P001", "发饰/DIY", "19.9", "", "星巴克马克杯" * 5, "上架中")])
        path = reconcile.write_checklist(reconcile.collect(p))
        text = path.read_text(encoding="utf-8")
        self.assertIn("P001", text)
        self.assertIn("待核对清单", text)

    def test_apply_published(self):
        p = make_xlsx("ap.xlsx", [("P001", "发饰/DIY", "19.9", "", "描述A", "上架中")])
        rc = reconcile.apply({2: "已发布"}, p)
        self.assertEqual(rc, 0)
        self.assertEqual(read_status(p, 2), "上架成功")
        self.assertEqual(ledger.current_state("P001"), "confirmed")

    def test_apply_not_published(self):
        p = make_xlsx("an.xlsx", [("P001", "发饰/DIY", "19.9", "", "描述A", "上架中")])
        rc = reconcile.apply({2: "未发布"}, p)
        self.assertEqual(rc, 0)
        self.assertEqual(read_status(p, 2), "待上架")
        self.assertEqual(ledger.current_state("P001"), "released")
        self.assertEqual(ledger.check("P001"), [])      # 可以重新入队

    def test_apply_skips_non_stuck_rows(self):
        p = make_xlsx("sk.xlsx", [("P001", "发饰/DIY", "19.9", "", "描述A", "上架成功")])
        reconcile.apply({2: "未发布"}, p)
        self.assertEqual(read_status(p, 2), "上架成功")   # 不动已成功的行

    def test_apply_rejects_unknown_verdict(self):
        p = make_xlsx("bad.xlsx", [("P001", "发饰/DIY", "19.9", "", "描述A", "上架中")])
        self.assertEqual(reconcile.apply({2: "也许吧"}, p), 2)
        self.assertEqual(read_status(p, 2), "上架中")


if __name__ == "__main__":
    unittest.main(verbosity=2)
