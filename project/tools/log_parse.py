"""运行日志结构化（S3-3 / O3）：把影刀导出的自由文本日志解析成 JSONL + 每件耗时

**为什么需要**：影刀导出的 `logs/*.txt` 是 `[级别] [时间] 消息` 的自由文本，
只能人眼读。要算「每件上架多久」「失败原因分布」「P50/P95」就必须先结构化。

**可用的信号**（实测 2026-11-07 的日志格式）：
  - `ROW n PID PASS|FAIL|WARN | ...`        → 预检逐行结果
  - `SUMMARY total=… pass=… warn=… fail=…` → 预检汇总
  - 一行只有套图目录路径（含 `products/<ID>/套图`）→ **该件开始处理**（画布块 044）
  - `上架成功数量：N` 等三行                → 本轮最终结果
  - 其余行（目标值、首子类名、WebElement…）→ 保留在 JSONL 里，但只用于计数

**每件耗时怎么算**：日志里没有行号，但「套图目录」打印是该件的第一个动作，
下一件的「套图目录」= 上一件的结束点；最后一件以「上架成功数量」行为结束点。

用法:
    python log_parse.py                      # 解析 project/runtime/logs/ 全部 txt
    python log_parse.py <某个.txt>            # 只解析一个
    python log_parse.py --summary            # 只看汇总表，不写 JSONL

输出:
    project/runtime/data/logs_jsonl/<run>.jsonl   每行一条事件
    project/runtime/data/logs_jsonl/<run>.summary.json
"""

import argparse
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "project" / "runtime" / "logs"
OUT = ROOT / "project" / "runtime" / "data" / "logs_jsonl"

# 影刀存在两种导出格式（实测 2026-11-07）：
#   A: [信息] [2026-11-07 10:21:00,168]: 消息    ← 带 BOM、毫秒用逗号、右括号后有冒号
#   B: [信息] [2026-11-07 10:21:40.569] 消息
LINE_RE = re.compile(
    r"^﻿?\[(?P<level>[^\]]+)\]\s*\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})[.,](?P<ms>\d+)\]:?\s?(?P<msg>.*)$")
ROW_RE = re.compile(r"^ROW\s+(?P<row>\d+)\s+(?P<pid>\S+)\s+(?P<tag>PASS|FAIL|WARN)\s+(?P<codes>\S*)\s*\|")
SUMMARY_RE = re.compile(r"^SUMMARY\s+total=(?P<total>\d+)\s+pass=(?P<pass>\d+)\s+warn=(?P<warn>\d+)\s+fail=(?P<fail>\d+)")
COUNT_RE = re.compile(r"^(上架成功数量|上架失败数量|上架不明情况数量)[：:]\s*(?P<n>\d+)")
PID_RE = re.compile(r"products[\\/](?P<pid>[^\\/]+)[\\/]套图")
STEP_RE = re.compile(r"^第(?P<level>\d+)级已正确")
# 发布段结构化标记（画布块 155/158/166/172/178）：
#   PUBLISH|begin|pid=P003 · PUBLISH|click|pid=P003 · PUBLISH|verdict|pid=P003|result=success
PUBLISH_RE = re.compile(r"^PUBLISH\|(?P<event>begin|click|verdict)\|pid=(?P<pid>[^|]*)(?:\|result=(?P<result>\w+))?")

KIND_COUNT = {
    "上架成功数量": "count_success",
    "上架失败数量": "count_fail",
    "上架不明情况数量": "count_unknown",
}


def _is_bare_path(msg: str) -> bool:
    """只由路径组成的行（画布块 044 打印套图目录、047 打印文件路径）。"""
    return "|" not in msg and "=" not in msg and re.search(r"[\\/]", msg) is not None


def classify(msg: str, level: str) -> dict:
    """把一行消息归成结构化事件。认不出的归 other，但原文保留。"""
    if msg.startswith("开始执行"):
        return {"kind": "run_start"}
    m = ROW_RE.match(msg)
    if m:
        return {"kind": "precheck_row", "row": int(m["row"]), "pid": m["pid"],
                "tag": m["tag"], "codes": [c for c in m["codes"].split() if c]}
    m = SUMMARY_RE.match(msg)
    if m:
        return {"kind": "precheck_summary", **{k: int(m[k]) for k in ("total", "pass", "warn", "fail")}}
    m = COUNT_RE.match(msg)
    if m:
        return {"kind": KIND_COUNT[m.group(1)], "value": int(m["n"])}
    m = STEP_RE.match(msg)
    if m:
        return {"kind": "category_step", "level": int(m["level"])}
    m = PUBLISH_RE.match(msg)
    if m:
        ev = {"kind": f"publish_{m['event']}", "pid": m["pid"]}
        if m["result"]:
            ev["result"] = m["result"]
        return ev
    if _is_bare_path(msg):
        pid = PID_RE.search(msg)
        if pid and msg.rstrip().rstrip("\\/").endswith("套图"):
            return {"kind": "row_start", "pid": pid["pid"]}      # 该件开始处理
        if pid:
            return {"kind": "upload_file", "pid": pid["pid"]}    # 单个文件上传
    if msg.startswith("执行结束"):
        return {"kind": "run_end"}
    return {"kind": "other"}


def parse_file(path: Path, run: str | None = None) -> tuple:
    """返回 (events, summary)。event = {run, seq, ts, level, kind, msg, ...}"""
    run = run or path.stem
    events, bad = [], 0
    text = path.read_text(encoding="utf-8-sig", errors="replace")   # utf-8-sig 吃掉 BOM
    for seq, raw in enumerate(text.splitlines()):
        if not raw.strip():
            continue
        m = LINE_RE.match(raw)
        if not m:
            bad += 1
            continue
        ts = f"{m['ts']}.{m['ms'].zfill(3)[:3]}"                    # 统一成 .mmm
        ev = {"run": run, "seq": seq, "ts": ts, "level": m["level"], "msg": m["msg"]}
        ev.update(classify(m["msg"], m["level"]))
        events.append(ev)
    return events, build_summary(events, run, bad)


def _ts(ev):
    return datetime.strptime(ev["ts"], "%Y-%m-%d %H:%M:%S.%f")


def build_summary(events, run, bad=0) -> dict:
    """汇总：起止/总耗时/预检/分件耗时/最终计数。"""
    s = {"run": run, "lines": len(events), "unparsed": bad,
         "start": events[0]["ts"] if events else "", "end": events[-1]["ts"] if events else "",
         "duration_s": 0.0, "precheck": {}, "counts": {}, "rows": []}

    if events:
        s["duration_s"] = round((_ts(events[-1]) - _ts(events[0])).total_seconds(), 1)

    for ev in events:
        if ev["kind"] == "precheck_summary":
            s["precheck"] = {k: ev[k] for k in ("total", "pass", "warn", "fail")}
        elif ev["kind"] in KIND_COUNT.values():
            s["counts"][ev["kind"]] = ev["value"]

    # 分件：以 row_start 为界，下一件起点 / 结束时分为终点
    starts = [i for i, ev in enumerate(events) if ev["kind"] == "row_start"]
    ends_at = next((i for i, ev in enumerate(events)
                    if ev["kind"] in ("count_success", "count_fail", "count_unknown")), len(events))
    for n, i in enumerate(starts):
        nxt = starts[n + 1] if n + 1 < len(starts) else ends_at
        seg = events[i:nxt]
        end_ev = events[nxt] if nxt < len(events) else events[-1]
        clicked = any(e["kind"] == "publish_click" for e in seg)
        verdict = next((e.get("result") for e in seg if e["kind"] == "publish_verdict"), None)
        s["rows"].append({
            "pid": events[i]["pid"],
            "start": events[i]["ts"],
            "duration_s": round((_ts(end_ev) - _ts(events[i])).total_seconds(), 1),
            "events": len(seg),
            "files": sum(1 for e in seg if e["kind"] == "upload_file"),
            "category_steps": sum(1 for e in seg if e["kind"] == "category_step"),
            "publish_clicked": clicked,
            "verdict": verdict,
            # 崩溃后可判定性：没点过 = 确定没发；点了没判决 = 未知；有判决 = 已知
            "certainty": ("unknown" if clicked and not verdict
                          else ("not_published" if not clicked else verdict)),
        })
    return s


def write_out(events, summary, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    jl = out_dir / f"{summary['run']}.jsonl"
    with open(jl, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    sp = out_dir / f"{summary['run']}.summary.json"
    sp.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return jl, sp


def print_summary(summaries):
    print(f"{'run':22} {'时长':>8} {'件数':>4} {'成功':>4} {'失败':>4} {'不明':>4}  分件耗时")
    for s in summaries:
        c = s["counts"]
        rows = ", ".join(f"{r['pid']}={r['duration_s']}s" for r in s["rows"]) or "-"
        print(f"{s['run']:22} {s['duration_s']:>7.1f}s {len(s['rows']):>4} "
              f"{c.get('count_success', '-'):>4} {c.get('count_fail', '-'):>4} "
              f"{c.get('count_unknown', '-'):>4}  {rows}")
    print()
    for s in summaries:
        if s["precheck"]:
            p = s["precheck"]
            print(f"{s['run']}: 预检 total={p['total']} pass={p['pass']} warn={p['warn']} fail={p['fail']}"
                  f" · 未解析行 {s['unparsed']}")


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="影刀日志结构化（只读 txt → JSONL）")
    ap.add_argument("file", nargs="?", help="单个日志 txt；省略=解析 logs/ 全部")
    ap.add_argument("--dir", default=str(LOGS))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--summary", action="store_true", help="只打印汇总，不写文件")
    a = ap.parse_args()

    files = [Path(a.file)] if a.file else sorted(Path(a.dir).glob("*.txt"))
    if not files:
        print(f"[!] 没有找到日志：{a.dir}")
        return 1

    summaries = []
    for f in files:
        events, summary = parse_file(f)
        summaries.append(summary)
        if not a.summary:
            jl, sp = write_out(events, summary, Path(a.out))
            print(f"[OK] {f.name} → {jl.relative_to(ROOT)}（{len(events)} 条事件）")

    print()
    print_summary(summaries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
