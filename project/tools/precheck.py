"""闲鱼上架队列预检 =「两段式」的第 1 段（L0 校验器）

**执行引擎无关**，两种入口：
- 命令行：`python project/tools/precheck.py [--xlsx 路径] [--csv 报告.csv]`
- 影刀环境：核心函数=`precheck`，参数=商品清单 xlsx 的绝对路径（**影刀里务必在参数栏传**：
  影刀会把脚本拷进 AppData 下的 app 沙箱，不传参时默认路径按脚本位置推导、必挂）。内部走 **`xbot.app.logging`** 逐行打印（FAIL=warning、
  其余=info、读表失败=error），并 return 字典：`aborted`/`error`/`total`/`pass`/`fail`/`warn`/
  `report`(整段文本，打印用)/`rows`(每行 {row,pid,tag,codes,warns})。分支 IF `%预检["fail"]% > 0`。
  · 「调用模块 / 执行Python代码」：函数名直接填 `precheck`。
  · 「运行Python脚本」(xbot_interpreter)：必须含 `main`，且 plugin_startup 会**带 1 个
    参数**调它——本文件 `main` 为万能签名，收到任何参数即走影刀分支执行 precheck
    （str/Path=清单路径 · dict=取 "xlsx" 键 · list=当命令行参数），不 argparse 不 sys.exit。
  xbot 不可导入（本机命令行）时日志自动退回 print。

只读，不写回、不开浏览器、不依赖登录态。

**两级判定**（2026-11-07 引入）：
- `fail`：「一定跑不通」，计入 precheck["fail"] → 画布 IF 分支整批不跑
- `warn`：「可疑但能跑」，只打日志 → 不阻断（画布侧接口不变）

FAIL 码：
  分类 CAT_EMPTY / CAT_EMPTYSEG / **CAT_FULLWIDTH**（全角斜杠或全角空格 → 影刀按 "/" 拆分必挂）
  价格 PRICE_EMPTY / PRICE_BAD / PRICE_NONPOS / **PRICE_ORIG_BAD** / **PRICE_ORDER**（原价<现价）
  套图 DIR_EMPTY / NO_DIR / EMPTY_DIR / **IMG_BAD**（目录内含非图片文件——画布是 *.* 全量上传）
  描述 DESC_EMPTY / DESC_LONG(>1500) / **DESC_CONTACT**（真实联系方式，会被限流）

WARN 码：
  价格 **PRICE_EXTREME**（>10 万，疑似小数点错位）
  分类 **CAT_DEPTH**（与同根品类历史上「上架成功」行的层数不一致，自学习口径，无样本则不判）

退出码（仅命令行）：0=无 FAIL（有 WARN 也算 0）；1=存在 FAIL；2=表读不了。
"""
import argparse
import csv
import re
import sys
from pathlib import Path

import openpyxl

try:
    RUNTIME_XLSX = Path(__file__).resolve().parents[1] / "runtime" / "商品清单.xlsx"
except NameError:  # 影刀「执行Python代码」贴代码场景没有 __file__；此时应在参数里传路径
    RUNTIME_XLSX = Path("project/runtime/商品清单.xlsx")

DESC_MAX = 1500
COL_ID, COL_CAT, COL_PRICE, COL_ORIG, COL_DIR, COL_DESC, COL_STATUS = 0, 3, 6, 7, 11, 12, 13

# 套图目录只许图片：画布块 045/048 用 *.* 全量上传，混进 txt/pdf 会被一起传上去
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
PRICE_MAX = 100_000                      # 超过即疑似小数点/单位错位
_FULLWIDTH_RX = re.compile(r"[／＼]")      # 全角斜杠/反斜杠：影刀按 "/" 拆不开，整条会当一个段
                                          # （半角空格不拦：级联是子串匹配，前导空格不影响命中）
# 只认真实联系方式形态。「电话」「微信」这类裸词不匹配——商品名里「儿童电话手表」会误伤
_CONTACT_RX = [
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("微信号", re.compile(r"(?i)(?:微信|v信|weixin|vx)\s*[:：]?\s*[A-Za-z0-9_-]{5,}")),
    ("QQ号", re.compile(r"(?i)qq\s*[:：]\s*\d{5,}")),
]

try:
    from xbot.app import logging as _xlog                    # 影刀内置日志
except Exception:
    _xlog = None


def _log(level, msg):
    """level: info/warning/error。影刀走日志面板，本机环境退回 print。"""
    if _xlog is not None:
        getattr(_xlog, level)(msg)
    else:
        print(msg)


def _cell(vals, i):
    v = vals[i] if i < len(vals) else None
    return "" if v is None else str(v).strip()


def _contact_hit(desc: str):
    for kind, rx in _CONTACT_RX:
        if rx.search(desc):
            return kind
    return ""


def _cat_root(cat: str) -> str:
    return cat.split("/")[0].strip()


def _cat_depth(cat: str) -> int:
    return len([s for s in cat.split("/")])


def check_row(vals, seen_depths=None):
    """vals: 0 起索引列表。返回 (fails, warns)；两者都为空 = PASS。

    seen_depths: {根品类: {历史上架成功过的层数}}，用于 CAT_DEPTH 自学习比对；None=不判。
    「分类顺序对不对」离线判不了（只有页面知道每级候选值），这里不做顺序推断——
    段序错由画布侧的两道守卫兜底（级别未推进 / 等待超限 → 判失败跳过该行）。
    """
    fails, warns = [], []

    cat = _cell(vals, COL_CAT)                               # 分类
    if not cat:
        fails.append("CAT_EMPTY")
    elif _FULLWIDTH_RX.search(cat):
        fails.append("CAT_FULLWIDTH")                        # 全角分隔符不会被 "/" 拆开
    elif any(not s.strip() for s in cat.split("/")):
        fails.append("CAT_EMPTYSEG")                         # 空段 → 级联点击必挂
    elif seen_depths:
        root, depth = _cat_root(cat), _cat_depth(cat)
        known = seen_depths.get(root)
        if known and depth not in known:
            warns.append(f"CAT_DEPTH:{depth}≠{sorted(known)}")

    price = _cell(vals, COL_PRICE)                           # 价格
    pv = None
    if not price:
        fails.append("PRICE_EMPTY")
    else:
        try:
            pv = float(price)
            if pv <= 0:
                fails.append("PRICE_NONPOS")
            elif pv > PRICE_MAX:
                warns.append(f"PRICE_EXTREME:{price}")
        except ValueError:
            fails.append("PRICE_BAD")

    orig = _cell(vals, COL_ORIG)                             # 原价
    if orig:
        try:
            if pv is not None and float(orig) < pv:
                fails.append(f"PRICE_ORDER:{orig}<{price}")
        except ValueError:
            fails.append("PRICE_ORIG_BAD")

    td = _cell(vals, COL_DIR)                                # 套图（上传图片）
    if not td:
        fails.append("DIR_EMPTY")
    else:
        p = Path(td)
        if not p.is_dir():
            fails.append("NO_DIR")
        else:
            files = [f for f in p.rglob("*") if f.is_file() and "." in f.name]
            if not files:
                fails.append("EMPTY_DIR")                    # 口径同影刀块045：递归、名含点
            else:
                bad = [f.name for f in files if f.suffix.lower() not in IMG_EXTS]
                if bad:
                    fails.append(f"IMG_BAD:{bad[0]}" + (f"(+{len(bad) - 1})" if len(bad) > 1 else ""))

    desc = _cell(vals, COL_DESC)                             # 描述
    if not desc:
        fails.append("DESC_EMPTY")
    else:
        if len(desc) > DESC_MAX:
            fails.append(f"DESC_LONG:{len(desc)}")
        hit = _contact_hit(desc)
        if hit:
            fails.append(f"DESC_CONTACT:{hit}")

    return fails, warns


def _seen_depths(all_vals):
    """从「上架成功」的历史行自学习：{根品类: {层数}}。没有成功的行 → 空 dict（不判层数）。"""
    seen = {}
    for vals in all_vals:
        if _cell(vals, COL_STATUS) != "上架成功":
            continue
        cat = _cell(vals, COL_CAT)
        if not cat or _FULLWIDTH_RX.search(cat):
            continue
        seen.setdefault(_cat_root(cat), set()).add(_cat_depth(cat))
    return seen


def scan(xlsx):
    """核心扫描。返回 (rows, err)：rows=[(行号, pid, tag, fails, warns, vals)]，err=None 为成功。"""
    try:
        wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
        ws = wb.active
    except Exception as e:
        return [], f"cannot read workbook: {e}"

    raw = []
    for r, vals in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        vals = list(vals)
        pid = _cell(vals, COL_ID)
        if not pid and not any(str(v).strip() for v in vals if v is not None):
            continue                                         # 空尾行不进队列
        raw.append((r, pid, vals))

    seen = _seen_depths([v for _, _, v in raw])              # 先学后判
    rows = []
    for r, pid, vals in raw:
        fails, warns = check_row(vals, seen)
        tag = "FAIL" if fails else ("WARN" if warns else "PASS")
        rows.append((r, pid, tag, fails, warns, vals))
    return rows, None


def _detail(vals):
    """该行必填项的取值明细，方便影刀日志一眼定位（值本身可含中文）。"""
    return (f"cat={_cell(vals, COL_CAT) or '-'} "
            f"price={_cell(vals, COL_PRICE) or '-'} "
            f"orig={_cell(vals, COL_ORIG) or '-'} "
            f"dir={_cell(vals, COL_DIR) or '-'} "
            f"desclen={len(_cell(vals, COL_DESC))}")


def render(rows):
    """rows → (逐行详细文本, FAIL 行数, WARN 行数)。命令行 print 与影刀返回值共用同一份。"""
    n_fail = sum(1 for x in rows if x[2] == "FAIL")
    n_warn = sum(1 for x in rows if x[2] == "WARN")
    lines = []
    for r, pid, tag, fails, warns, vals in rows:
        codes = " ".join(fails + warns) or "-"
        lines.append(f"ROW {r:3} {pid or '-':10} {tag:4} {codes:22} | {_detail(vals)}")
    lines.append(f"SUMMARY total={len(rows)} pass={len(rows) - n_fail - n_warn} "
                 f"warn={n_warn} fail={n_fail}")
    return "\n".join(lines), n_fail, n_warn


def precheck(xlsx_path=None):
    """影刀入口：xbot.app.logging 逐行打日志；返回结构化 dict。不 exit。

    返回 dict 新增 `warn`/`warnings`；`fail` 语义不变（只有能确定跑不通的才算），
    因此画布侧 `IF 预检["fail"] > 0` 无需改动。
    """
    path = str(RUNTIME_XLSX)
    if xlsx_path:
        # 影刀参数栏常把路径连引号一起传进来（"F:\...xlsx"），openpyxl 会认成
        # 扩展名 .xlsx" 而拒收 → 先清洗首尾空白/中英文引号
        path = str(xlsx_path).strip().strip('\'"“”').strip() or path
    rows, err = scan(path)
    if err:
        _log("error", f"PRECHECK ABORT: {err}")
        return {"aborted": True, "error": str(err), "total": 0, "pass": 0, "fail": 0,
                "warn": 0, "report": f"PRECHECK ABORT: {err}", "rows": []}
    text, n_fail, n_warn = render(rows)
    for line in text.splitlines():
        level = "warning" if (" FAIL " in line or " WARN " in line) else "info"
        _log(level, line)
    return {"aborted": False, "error": "",
            "total": len(rows), "pass": len(rows) - n_fail - n_warn, "fail": n_fail,
            "warn": n_warn,
            "warnings": [{"row": r, "pid": pid, "codes": warns}
                         for r, pid, tag, fails, warns, _ in rows if tag == "WARN"],
            "report": text,
            "rows": [{"row": r, "pid": pid, "tag": tag, "codes": fails, "warns": warns}
                     for r, pid, tag, fails, warns, _ in rows]}


def _cli(argv):
    """本机命令行分支：argv 不含脚本名。返回退出码 0（无 FAIL）/1（有 FAIL）/2（表读不了）。"""
    ap = argparse.ArgumentParser(description="闲鱼上架队列预检（两段式第1段，引擎无关）")
    ap.add_argument("--xlsx", default=str(RUNTIME_XLSX))
    ap.add_argument("--csv", help="可选：UTF-8-BOM 明细报告，Excel 直开")
    a = ap.parse_args(argv)

    try:  # 明细行含中文，stdout 被重定向时按 utf-8 写，不让 gbk 抛异常
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    rows, err = scan(a.xlsx)
    if err:
        print(f"PRECHECK ABORT: cannot read workbook: {err[24:]}")
        return 2
    text, n_fail, _n_warn = render(rows)
    print(text)
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["行号", "商品ID", "结论", "FAIL码", "WARN码", "描述前段"])
            w.writerows([(r, pid, tag, ";".join(fails), ";".join(warns), _cell(vals, COL_DESC)[:60])
                         for r, pid, tag, fails, warns, vals in rows])
        print(f"CSV={a.csv}")
    return 1 if n_fail else 0


def main(*args, **kwargs):
    """双环境入口。
    本机 CLI：`python precheck.py ...` 底部 sys.exit(main()) 无参 → _cli 分支。
    影刀「运行Python脚本」：plugin_startup 带 1 参调 main——收到任何参数即走影刀分支，
    执行 precheck() 返回 dict（xbot 日志已在其内打好），绝不 argparse sys.argv、绝不 exit。
      参数约定：str/Path=清单路径 · dict=取 "xlsx"/"xlsx_path" 键 · None=默认路径
                · list[str]=视作命令行参数（等价本机运行）。
    """
    if not args and not kwargs:
        return _cli(sys.argv[1:])
    src = args[0] if args else kwargs
    if isinstance(src, (list, tuple)):
        if len(src) == 1 and isinstance(src[0], str) and not src[0].startswith("-"):
            src = src[0]                                 # 影刀把单参数包成 list → 视作路径
        elif all(isinstance(x, str) for x in src):
            return _cli(list(src))                       # 命令行风格参数组
    path = None
    if isinstance(src, dict):
        path = src.get("xlsx") or src.get("xlsx_path")
    elif isinstance(src, (str, Path)):
        path = src
    return precheck(str(path) if path else None)


if __name__ == "__main__":
    sys.exit(main())
