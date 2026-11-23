# -*- coding: utf-8 -*-
"""运行指标口径回归：dry 轮不算发布尝试、判定分布、发布→判定耗时。"""
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import metrics


def ev(run, ts, kind, **kw):
    return dict(run=run, ts=ts, kind=kind, **kw)


class TestMetrics(unittest.TestCase):
    def test_empty(self):
        m = metrics.summarize([])
        self.assertEqual(m["runs"], 0)
        self.assertEqual(m["publish_attempts"], 0)
        self.assertIsNone(m["publish_latency_median"])

    def test_dry_run_not_counted_as_publish(self):
        recs = [
            ev("r1", "2026-11-09 18:00:01", "run_start", dry_run=True),
            ev("r1", "2026-11-09 18:00:02", "PUBLISH|begin", pid="P001"),
            ev("r1", "2026-11-09 18:00:05", "PUBLISH|verdict", pid="P001", result="unknown"),
        ]
        m = metrics.summarize(recs)
        self.assertEqual(m["runs"], 1)
        self.assertEqual(m["real_runs"], 0)
        self.assertEqual(m["publish_attempts"], 0)
        self.assertEqual(m["verdicts"], {"success": 0, "unknown": 1, "failed": 0})

    def test_real_run_latency_and_counts(self):
        recs = [
            ev("r2", "2026-11-17 14:00:00", "run_start", dry_run=False),
            ev("r2", "2026-11-17 14:00:01", "row_start", pid="P005"),
            ev("r2", "2026-11-17 14:00:02", "upload_file", file="a.jpg"),
            ev("r2", "2026-11-17 14:00:10", "PUBLISH|begin", pid="P005"),
            ev("r2", "2026-11-17 14:00:11", "PUBLISH|click", pid="P005"),
            ev("r2", "2026-11-17 14:00:16", "PUBLISH|verdict", pid="P005", result="success"),
            ev("r2", "2026-11-17 14:00:20", "run_end"),
        ]
        m = metrics.summarize(recs)
        self.assertEqual(m["real_runs"], 1)
        self.assertEqual(m["rows"], 1)
        self.assertEqual(m["uploads"], 1)
        self.assertEqual(m["publish_attempts"], 1)
        self.assertEqual(m["verdicts"]["success"], 1)
        self.assertEqual(m["publish_latency_median"], 6.0)
        self.assertEqual(m["run_duration_median"], 20.0)

    def test_history_summary(self):
        summaries = [
            {"run": "r", "duration_s": 213.0, "counts": {"count_success": 4},
             "rows": [{"pid": "P002", "duration_s": 76.8},
                      {"pid": "P003", "duration_s": 53.8},
                      {"pid": "P004", "duration_s": 49.4}]},
        ]
        m = metrics.summarize([], summaries)
        self.assertEqual(m["history"]["runs"], 1)
        self.assertEqual(m["history"]["counts"]["count_success"], 4)
        self.assertEqual(m["history"]["items"], 3)
        self.assertAlmostEqual(m["history"]["item_median"], 53.8)
        self.assertEqual(m["history"]["run_median"], 213.0)

    def test_render_md_mentions_seed_caveat(self):
        md = metrics.render_md(metrics.summarize([]))
        self.assertIn("seed", md)
        self.assertIn("无样本", md)


if __name__ == "__main__":
    unittest.main()
