"""改动闸门（S1-4 / D2 收口）：一条命令跑完全部一致性检查

改完画布或文档后，只需要记住这一条：

    python project/tools/verify.py

依次跑：
  1. 画布快照比对   canvas_snapshot.py --check      （需影刀编辑器在线且开着本仓应用，否则 SKIP）
  2. 三处块数一致   check_truth_source.py            （画布 = 转录 = 快照 = 文档；无画布时退化为 --offline）
  3. 块号引用一致   check_block_refs.py              （README 分区表 vs 折叠区域，按名字对）
  4. 凭据扫描       secret_scan.py                   （工作区 + git 历史无明文凭据）
  5. 回归测试       unittest discover（加 --tests 才跑，默认跳过以保持秒级）
  6. 节点测试       project/modules/测试（上架步骤级纯离线用例）

**应用身份**：编辑器一次只开一个应用，studio-mcp 不区分应用。若当前打开的不是本仓
应用（「自动化上架」），画布相关检查一律不比对、标「未校验」，退出码 1——开错应用
时拿别家画布算出的「一致」或「不一致」都是假的。

退出码: 0=全过（含离线 SKIP）· 1=有失败或存在未校验项 · 2=检查脚本本身不存在
"""

import argparse
import io
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parents[1]

TEST_SUITES = [
    ("回归测试", TOOLS / "tests"),
    ("节点测试", ROOT / "project" / "modules" / "测试"),
]

STEPS = [
    # (名称, 命令, 是否需要编辑器, 编辑器不可用时的离线替代参数；None=只能跳过)
    ("画布快照比对", [str(TOOLS / "canvas_snapshot.py"), "--check"], "editor", None),
    ("三处块数一致", [str(TOOLS / "check_truth_source.py")], "editor", ["--offline"]),
    ("块号引用一致", [str(TOOLS / "check_block_refs.py")], None, None),
    ("凭据扫描", [str(TOOLS / "secret_scan.py")], None, None),
]


def editor_state() -> tuple:
    """(在线, 当前应用名, 开错应用时的实际应用名, 本仓期望应用名)

    编辑器一次只开一个应用，而 studio-mcp 不区分应用：开着别家应用时读到的就是别家画布。
    这里先验身份，避免拿别家画布判本仓不一致（2026-11-23 项目二误报 main 83→16）。
    """
    sys.path.insert(0, str(TOOLS / "shadowbot-canvas"))
    try:
        import sb_mcp
        sb_mcp.discover_port()
    except Exception:
        return False, "", None, ""
    try:
        return True, sb_mcp.current_app_name(), sb_mcp.wrong_app(), sb_mcp.EXPECTED_APP_NAME
    except Exception:
        return True, "", None, ""


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

    online, app_name, wrong, expected = editor_state()
    results = []
    unverified = []

    for name, args, need, fallback in STEPS:
        if need == "editor" and (not online or wrong):
            reason = "影刀编辑器未启动" if not online else f"编辑器开的是「{wrong}」"
            if fallback is None:
                results.append((name, "SKIP", f"{reason}（未校验）", ""))
                if wrong:
                    unverified.append(name)
                continue
            rc, out = run(args + fallback)
            results.append((f"{name}(离线)", "PASS" if rc == 0 else "FAIL", reason, out))
            continue
        rc, out = run(args)
        results.append((name, "PASS" if rc == 0 else "FAIL", "", out))

    if a.tests:
        for label, suite in TEST_SUITES:
            if not Path(suite).is_dir():
                results.append((label, "SKIP", "目录不存在", ""))
                continue
            rc, out = run(["-m", "unittest", "discover", "-s", str(suite), "-t", str(suite)])
            summary = [ln for ln in out.splitlines() if ln.startswith(("Ran ", "OK", "FAILED"))]
            results.append((label, "PASS" if rc == 0 else "FAIL", " / ".join(summary), out))

    state = "离线"
    if online:
        state = f"在线 · 应用「{app_name}」" if app_name else "在线（应用名未知）"
    print(f"闸门检查（编辑器{state}）")
    if wrong:
        print(f"  ⚠ 开错应用：当前「{wrong}」≠ 本仓「{expected}」，画布相关项无法校验")
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
    if unverified:
        print(f"[!] {len(unverified)} 项未校验：{', '.join(unverified)}")
        print(f"    编辑器打开的是「{wrong}」，本仓应用是「{expected}」。切到「{expected}」后重跑。")
        return 1
    print("[OK] 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
