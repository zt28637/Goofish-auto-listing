# -*- coding: utf-8 -*-
"""凭据扫描 —— 工作区 + git 历史，一条命令证明「仓库里没有明文凭据」

背景（2026-11-18）：
  失败模式清单 A1 长期标红「历史提交仍含明文凭据」。实际用 `git log -S`
  拿工作区真实手机号/密码全量搜索是 0 命中，凭据从未入仓；那条结论是
  11-07 事故后按「删不掉就假设有」写的保守判断，已过时。
  与其重写历史（有风险、无收益），不如把「已证明干净」变成可重复执行的检查。

扫描对象：
  · 工作区：`git ls-files` 的已跟踪文件（凭据文件本身被 gitignore，不读）
  · 历史：`git log --all -p` 的新增行（覆盖已删除文件的历史内容）
  · 配置：credentials.local.json 存在时必须已被 gitignore

判定模式（只认「真凭据形态」，避免文档/环境变量误报）：
  mobile      11 位手机号（测试占位号 13800000000 / 13812345678 放行）
  secret       password/secret/token/api_key… = "值"（值 ≥6 字符）
  private_key  PEM 私钥头
  cookie       unb= / _nk_*= 后跟 ≥6 位值

退出码：0=干净 · 1=发现疑似凭据 · 2=git 不可用
用法：
    python project/tools/secret_scan.py            # 工作区 + 历史
    python project/tools/secret_scan.py --worktree-only
    python project/tools/secret_scan.py --json
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CRED = ROOT / "project" / "conf" / "credentials.local.json"

# 测试/文档占位号，不算泄露
ALLOW_MOBILE = {"13800000000", "13812345678"}
# 影刀指令目录是「参数名 → 中文说明」的生成文件，password/token 是字段名不是值
SKIP_PATHS = (
    "project/tools/shadowbot-canvas/sb_blocks_zh.json",
    "project/tools/shadowbot-canvas/sb_catalog.json",
)
# 明显的占位值，不算泄露
ALLOW_SECRET_WORDS = ("your_", "your-", "xxx", "***", "<", "{", "example",
                      "placeholder", "changeme", "test_", "dummy")

PATTERNS = [
    ("mobile", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("secret", re.compile(
        r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|authorization)"
        r"\b['\"]?\s*[:=]\s*(['\"])([^'\"]{6,})\2")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("cookie", re.compile(r"(?i)\b(unb|_nk_[A-Za-z0-9_]*)\s*=\s*([A-Za-z0-9%._\-]{6,})")),
]


def mask(value: str) -> str:
    """只露头尾，足够定位、不足以复用。"""
    v = str(value)
    if len(v) <= 6:
        return "***"
    return v[:3] + "***" + v[-2:]


def scan_text(text: str, source: str = "") -> list[dict]:
    """扫描一段文本，返回疑似凭据列表（值已脱敏）。纯函数，便于单测。"""
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for kind, pat in PATTERNS:
            for m in pat.finditer(line):
                value = m.group(3) if kind == "secret" else m.group(0)
                if kind == "mobile":
                    if value in ALLOW_MOBILE:
                        continue
                elif kind == "secret":
                    low = value.lower()
                    if any(w in low for w in ALLOW_SECRET_WORDS):
                        continue
                elif kind == "cookie":
                    value = m.group(0)
                hits.append({"kind": kind, "masked": mask(value),
                             "source": source, "line": lineno})
    return hits


def _skipped(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    return any(rel.endswith(s) for s in SKIP_PATHS)


def _git(*args: str) -> str:
    p = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "").strip() or "git 调用失败")
    return p.stdout


def scan_worktree() -> list[dict]:
    hits = []
    out = _git("ls-files", "-z")
    for rel in out.split("\0"):
        if not rel or _skipped(rel):
            continue
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits.extend(scan_text(text, source=rel))
    if CRED.exists():
        try:
            _git("check-ignore", "-q", str(CRED))
        except RuntimeError:
            hits.append({"kind": "cred_not_ignored", "masked": "***",
                         "source": str(CRED.relative_to(ROOT)), "line": 0})
    return hits


def scan_history() -> list[dict]:
    """只扫新增行：删除行的历史内容在「被加入的那次提交」里已经出现过。"""
    hits = []
    log = _git("log", "--all", "-p", "--pretty=format:__C__%H", "--")
    commit = "?"
    path = ""
    for line in log.splitlines():
        if line.startswith("__C__"):
            commit = line[5:]
        elif line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
        elif line.startswith("+") and not line.startswith("+++"):
            if not _skipped(path):
                hits.extend(scan_text(line[1:], source=commit[:8]))
    return hits


def main(argv=None) -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="扫描工作区与 git 历史中的明文凭据")
    ap.add_argument("--worktree-only", action="store_true")
    ap.add_argument("--history-only", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    hits = []
    if not a.history_only:
        hits += scan_worktree()
    if not a.worktree_only:
        try:
            hits += scan_history()
        except RuntimeError as e:
            print("[ERROR] 历史扫描失败：%s" % e)
            return 2

    if a.json:
        print(json.dumps(hits, ensure_ascii=False, indent=1))
    else:
        for h in hits:
            print("[HIT] %-14s %-10s %s:%s" % (h["kind"], h["masked"], h["source"], h["line"]))
        print("[OK] 未发现明文凭据（工作区 + 历史）" if not hits
              else "[FAIL] 发现 %d 处疑似凭据" % len(hits))
    return 0 if not hits else 1


if __name__ == "__main__":
    sys.exit(main())
