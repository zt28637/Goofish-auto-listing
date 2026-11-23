# -*- coding: utf-8 -*-
"""运行指标 —— 从结构化事件日志算出「交付证据」，而不是靠感觉说跑过

数据源：`project/runtime/logs/run_*/events.jsonl`（每个步骤用 common.event 落的结构化事件）
输出：运行次数 / 处理行数 / 发布尝试 / 判定分布 / 发布→判定耗时 / 上传文件数 / 台账分布

口径：
  · **dry_run**：以 click 事件为准——dry 轮只写 begin，不写 click
  · **发布尝试** = PUBLISH|click 条数（真正点过按钮的次数）
  · **判定分布** = PUBLISH|verdict 的 result（success / unknown / failed）
  · 耗时只算同一 pid 的 begin → verdict，秒级（事件时间戳精度为秒）

用法：
    python project/tools/metrics.py                 # 控制台 Markdown 表
    python project/tools/metrics.py --json          # 机器可读
    python project/tools/metrics.py --write         # 写入 project/docs/量化结果.md
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "project" / "runtime" / "logs"
LEDGER = ROOT / "project" / "runtime" / "data" / "published.jsonl"
OUT_DOC = ROOT / "project" / "docs" / "量化结果.md"


def _ts(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def load_events() -> list[dict]:
    records = []
    for p in sorted(RUNS.glob("run_*/events.jsonl")):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    records.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            continue
    return records


def load_summaries() -> list[dict]:
    """旧画布/影刀的 txt 日志经 log_parse 解析出的历史轮汇总（11-07 那批）。"""
    out = []
    for p in sorted((ROOT / "project" / "runtime" / "data" / "logs_jsonl").glob("*.summary.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def load_ledger() -> dict:
    counts = {"total": 0, "seed": 0, "confirmed": 0, "released": 0, "failed": 0, "unknown": 0}
    if not LEDGER.exists():
        return counts
    try:
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            counts["total"] += 1
            if r.get("来源") == "seed-from-xlsx" or "事件" not in r:
                counts["seed"] += 1
            elif r.get("事件") == "release":
                counts["released"] += 1
            elif r.get("结果") == "上架成功":
                counts["confirmed"] += 1
            elif r.get("结果") == "上架失败":
                counts["failed"] += 1
            else:
                counts["unknown"] += 1
    except (OSError, json.JSONDecodeError):
        pass
    return counts


def summarize(records: list[dict], summaries: list[dict] = ()) -> dict:
    """纯函数：事件列表 → 指标 dict（便于单测）。"""
    runs = {}
    latencies = []
    for r in records:
        rid = r.get("run") or "?"
        st = runs.setdefault(rid, {
            "dry_run": bool(r.get("dry_run")) if r.get("kind") == "run_start" else None,
            "rows": 0, "clicks": 0, "verdicts": {"success": 0, "unknown": 0, "failed": 0},
            "uploads": 0, "start": None, "end": None, "begin": {},
        })
        kind = r.get("kind")
        if kind == "run_start":
            st["dry_run"] = bool(r.get("dry_run"))
            st["start"] = _ts(r.get("ts"))
        elif kind == "run_end":
            st["end"] = _ts(r.get("ts"))
        elif kind == "row_start":
            st["rows"] += 1
        elif kind == "upload_file":
            st["uploads"] += 1
        elif kind == "PUBLISH|begin":
            st["begin"][r.get("pid")] = _ts(r.get("ts"))
        elif kind == "PUBLISH|click":
            st["clicks"] += 1
        elif kind == "PUBLISH|verdict":
            res = r.get("result") or "unknown"
            st["verdicts"][res] = st["verdicts"].get(res, 0) + 1
            b = st["begin"].pop(r.get("pid"), None)
            t = _ts(r.get("ts"))
            if b and t:
                latencies.append(max(0.0, (t - b).total_seconds()))

    real_runs = [st for st in runs.values() if st["clicks"] > 0]
    verdicts = {"success": 0, "unknown": 0, "failed": 0}
    for st in runs.values():
        for k, v in st["verdicts"].items():
            verdicts[k] = verdicts.get(k, 0) + v

    durations = []
    for st in runs.values():
        if st["start"] and st["end"]:
            durations.append(max(0.0, (st["end"] - st["start"]).total_seconds()))

    hist_counts = {"count_success": 0, "count_fail": 0, "count_unknown": 0}
    hist_items = []
    hist_runs = []
    for s in summaries:
        for k in hist_counts:
            hist_counts[k] += int((s.get("counts") or {}).get(k, 0))
        produced = bool(s.get("rows")) or any((s.get("counts") or {}).values())
        if produced and s.get("duration_s") is not None:
            hist_runs.append(float(s["duration_s"]))
        for row in s.get("rows") or []:
            if row.get("duration_s") is not None:
                hist_items.append(float(row["duration_s"]))

    return {
        "runs": len(runs),
        "real_runs": len(real_runs),
        "rows": sum(st["rows"] for st in runs.values()),
        "publish_attempts": sum(st["clicks"] for st in runs.values()),
        "verdicts": verdicts,
        "uploads": sum(st["uploads"] for st in runs.values()),
        "publish_latency_median": median(latencies) if latencies else None,
        "publish_latency_max": max(latencies) if latencies else None,
        "run_duration_median": median(durations) if durations else None,
        "history": {
            "runs": len(summaries),
            "counts": hist_counts,
            "items": len(hist_items),
            "item_median": median(hist_items) if hist_items else None,
            "run_median": median(hist_runs) if hist_runs else None,
        },
        "ledger": load_ledger(),
    }


def render_md(m: dict) -> str:
    lat = m["publish_latency_median"]
    lat_max = m["publish_latency_max"]
    dur = m["run_duration_median"]
    led = m["ledger"]
    v = m["verdicts"]
    core = ["成功 %d" % v.get("success", 0), "不明 %d" % v.get("unknown", 0),
            "失败 %d" % v.get("failed", 0)]
    core += ["%s %d" % (k, n) for k, n in v.items()
             if k not in ("success", "unknown", "failed")]
    h = m["history"]
    hc = h["counts"]
    item_med = h["item_median"]
    run_med = h["run_median"]
    lines = [
        "# 量化结果（自动生成）",
        "",
        "> 由 `python project/tools/metrics.py --write` 从本地运行日志生成；日志本身不进仓。",
        "> 两段数据来源不同，分开看：**历史轮**来自影刀 txt 日志（11-07 旧画布整轮），**结构化事件**从 11-09 起逐步骤落盘。",
        "> 样本量小是事实，不美化：它证明「流程跑通过、有结构化证据」，不证明「大规模稳定性」。",
        "",
        "## 一、历史轮（影刀日志解析，log_parse）",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 轮次 | {h['runs']} |",
        f"| 成功 / 失败 / 不明 | {hc['count_success']} / {hc['count_fail']} / {hc['count_unknown']} |",
        f"| 统计到的商品件数 | {h['items']} |",
        f"| 单件耗时 中位数 | {item_med:.1f}s |" if item_med is not None else "| 单件耗时 中位数 | 无样本 |",
        f"| 整轮耗时（有产出的轮次） | {run_med:.1f}s |" if run_med is not None else "| 整轮耗时（有产出的轮次） | 无样本 |",
        "",
        "## 二、结构化事件轮（11-09 起，逐步骤 events.jsonl）",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 有事件的运行次数 | {m['runs']} |",
        f"| 真实发布轮次（点过发布） | {m['real_runs']} |",
        f"| 处理行数 | {m['rows']} |",
        f"| 发布尝试（click 次数） | {m['publish_attempts']} |",
        f"| 判定分布 | {' / '.join(core)} |",
        f"| 上传文件次数 | {m['uploads']} |",
        f"| 发布→判定 中位数 | {lat:.1f}s |" if lat is not None else "| 发布→判定 中位数 | 无样本 |",
        f"| 发布→判定 最长 | {lat_max:.1f}s |" if lat_max is not None else "| 发布→判定 最长 | 无样本 |",
        f"| 单轮耗时 中位数 | {dur:.1f}s |" if dur is not None else "| 单轮耗时 中位数 | 无样本 |",
        f"| 台账记录（总/seed/confirmed/released） | {led['total']} / {led['seed']} / {led['confirmed']} / {led['released']} |",
        "",
        "> 口径：**发布尝试**只算 `PUBLISH|click`，dry 轮只写 begin 不写 click。",
        "> 台账里的 seed 记录是从 Excel「上架成功」行补录的历史，不等于本系统实际跑出的成功数。",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="从运行事件计算交付指标")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true", help="写入 project/docs/量化结果.md")
    a = ap.parse_args(argv)

    m = summarize(load_events(), load_summaries())
    md = render_md(m)
    if a.json:
        print(json.dumps(m, ensure_ascii=False, indent=1))
    else:
        print(md)
    if a.write:
        OUT_DOC.write_text(md, encoding="utf-8")
        print("[OK] 已写入 %s" % OUT_DOC.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
