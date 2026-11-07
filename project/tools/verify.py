"""改动闸门（S1-4 / D2 收口）：一条命令跑完全部一致性检查

改完画布或文档后，只需要记住这一条：

    python project/tools/verify.py

依次跑：
  1. 画布快照比对   canvas_snapshot.py --check      （需影刀编辑器在线，离线则 SKIP）
  2. 三处块数一致   check_truth_source.py            （画布 = 转录 = 快照 = 文档）
  3. 块号引用一致   check_block_refs.py              （README 分区表 vs 折叠区域，按名字对）
  4. 回归测试       unittest discover（加 --tests 才跑，默认跳过以保持秒级）

退出码: 0=全过（含 SKIP）· 1=有失败 · 2=检查脚本本身不存在
"""

import argparse
import io
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parents[1]

STEPS = [
    ("画布快照比对", [str(TOOLS / "canvas_snapshot.py"), "--check"], "editor"),
    ("三处块数一致", [str(TOOLS / "check_truth_source.py")], None),
    ("块号引用一致", [str(TOOLS / "check_block_refs.py")], None),
]


def editor_online() -> bool:
    sys.path.insert(0, str(TOOLS / "shadowbot-canvas"))
    try:
        import sb_mcp
        sb_mcp.discover_port()
        return True
    except Exception:
        return False


def run(script_args: list) -> tuple:
    p = subprocess.run([sys.executable, "-X", "utf8", *script_args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="改动闸门：一条命令跑完全部一致性检查")
    ap.add_argument("--tests", action="store_true", help="同时跑单元测试")
    ap.add_argument("-v", "--verbose", action="store_true", help="透传各步完整输出")
    a = ap.parse_args()

    online = editor_online()
    results = []

    for name, args, need in STEPS:
        if need == "editor" and not online:
            results.append((name, "SKIP", "影刀编辑器未启动（离线跳过）", ""))
            continue
        rc, out = run(args)
        results.append((name, "PASS" if rc == 0 else "FAIL", "", out))

    if a.tests:
        rc, out = run(["-m", "unittest", "discover", "-s", str(TOOLS / "tests")])
        summary = [ln for ln in out.splitlines() if ln.startswith(("Ran ", "OK", "FAILED"))]
        results.append(("回归测试", "PASS" if rc == 0 else "FAIL", " / ".join(summary), out))

    print(f"闸门检查（编辑器{'在线' if online else '离线'}）")
    print("-" * 56)
    for name, status, note, out in results:
        mark = {"PASS": "✓", "FAIL": "✗", "SKIP": "·"}[status]
        print(f"  {mark} {name:10} {status:4} {note}")
        if status == "FAIL":
            for line in [ln for ln in out.splitlines() if ln.strip()][-8:]:
                print(f"      {line}")
        elif a.verbose and out.strip():
            for line in out.splitlines():
                print(f"      {line}")
    print("-" * 56)

    failed = [r for r in results if r[1] == "FAIL"]
    if failed:
        print(f"[FAIL] {len(failed)} 项未通过：{', '.join(r[0] for r in failed)}")
        return 1
    print("[OK] 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
