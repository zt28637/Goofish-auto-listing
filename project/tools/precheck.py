"""闲鱼上架队列预检 =「两段式」的第 1 段（L0 校验器）

**执行引擎无关**，两种入口：
- 命令行：`python project/tools/precheck.py [--xlsx 路径] [--csv 报告.csv]`
- 影刀环境：核心函数=`precheck`，参数=商品清单 xlsx 的绝对路径（**影刀里务必在参数栏传**：
  影刀会把脚本拷进 AppData 下的 app 沙箱，不传参时默认路径按脚本位置推导、必挂）。内部走 **`xbot.app.logging`** 逐行打印（FAIL=warning、
  其余=info、读表失败=error），并 return 字典：`aborted`/`error`/`total`/`pass`/`fail`/
  `report`(整段文本，打印用)/`rows`(每行 {row,pid,tag,codes})。分支 IF `%预检["fail"]% > 0`。
  · 「调用模块 / 执行Python代码」：函数名直接填 `precheck`。
  · 「运行Python脚本」(xbot_interpreter)：必须含 `main`，且 plugin_startup 会**带 1 个
    参数**调它——本文件 `main` 为万能签名，收到任何参数即走影刀分支执行 precheck
    （str/Path=清单路径 · dict=取 "xlsx" 键 · list=当命令行参数），不 argparse 不 sys.exit。
  xbot 不可导入（本机命令行）时日志自动退回 print。

只读 **四项必填**——上传图片(套图) / 描述 / 分类 / 价格；不写回、不开浏览器、不依赖登录态。
发货/原价/地址默认、"空发货点无需邮寄"等属执行段语义，预检一律不管。

退出码（仅命令行）：0=全部行合格；1=存在 FAIL 行；2=表读不了。

FAIL 码：分类 CAT_EMPTY/CAT_EMPTYSEG · 价格 PRICE_EMPTY/PRICE_BAD/PRICE_NONPOS
        套图 DIR_EMPTY/NO_DIR/EMPTY_DIR · 描述 DESC_EMPTY/DESC_LONG(>1500)
"""
import argparse
import csv
import sys
from pathlib import Path

import openpyxl

try:
    RUNTIME_XLSX = Path(__file__).resolve().parents[1] / "runtime" / "商品清单.xlsx"
except NameError:  # 影刀「执行Python代码」贴代码场景没有 __file__；此时应在参数里传路径
    RUNTIME_XLSX = Path("project/runtime/商品清单.xlsx")

DESC_MAX = 1500
COL_ID, COL_CAT, COL_PRICE, COL_DIR, COL_DESC = 0, 3, 6, 11, 12

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


def check_row(vals):
    """vals: 0 起索引列表。返回 FAIL 码列表（空=PASS），四项必填之外一律放行。"""
    fails = []

    cat = _cell(vals, COL_CAT)                               # 分类
    if not cat:
        fails.append("CAT_EMPTY")
    elif any(not s for s in cat.split("/")):
        fails.append("CAT_EMPTYSEG")                         # 空段 → 级联点击必挂

    price = _cell(vals, COL_PRICE)                           # 价格
    if not price:
        fails.append("PRICE_EMPTY")
    else:
        try:
            if float(price) <= 0:
                fails.append("PRICE_NONPOS")
        except ValueError:
            fails.append("PRICE_BAD")

    td = _cell(vals, COL_DIR)                                # 套图（上传图片）
    if not td:
        fails.append("DIR_EMPTY")
    else:
        p = Path(td)
        if not p.is_dir():
            fails.append("NO_DIR")
        elif not any(f.is_file() and "." in f.name for f in p.rglob("*")):
            fails.append("EMPTY_DIR")                        # 口径同影刀块028：递归、名含点

    desc = _cell(vals, COL_DESC)                             # 描述
    if not desc:
        fails.append("DESC_EMPTY")
    elif len(desc) > DESC_MAX:
        fails.append(f"DESC_LONG:{len(desc)}")

    return fails


def scan(xlsx):
    """核心扫描。返回 (rows, err)：rows=[(行号, pid, tag, fails, vals)]，err=None 为成功。"""
    try:
        wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
        ws = wb.active
    except Exception as e:
        return [], f"cannot read workbook: {e}"

    rows = []
    for r, vals in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        vals = list(vals)
        pid = _cell(vals, COL_ID)
        if not pid and not any(str(v).strip() for v in vals if v is not None):
            continue                                         # 空尾行不进队列
        fails = check_row(vals)
        rows.append((r, pid, "FAIL" if fails else "PASS", fails, vals))
    return rows, None


def _detail(vals):
    """该行四项必填的取值明细，方便影刀日志一眼定位（值本身可含中文）。"""
    return (f"cat={_cell(vals, COL_CAT) or '-'} "
            f"price={_cell(vals, COL_PRICE) or '-'} "
            f"dir={_cell(vals, COL_DIR) or '-'} "
            f"desclen={len(_cell(vals, COL_DESC))}")


def render(rows):
    """rows → (逐行详细文本, FAIL 行数)。命令行 print 与影刀返回值共用同一份。"""
    n_fail = sum(1 for _, _, tag, _, _ in rows if tag == "FAIL")
    lines = [f"ROW {r:3} {pid or '-':10} {tag:4} {' '.join(fails) or '-':22} | {_detail(vals)}"
             for r, pid, tag, fails, vals in rows]
    lines.append(f"SUMMARY total={len(rows)} pass={len(rows) - n_fail} fail={n_fail}")
    return "\n".join(lines), n_fail


def precheck(xlsx_path=None):
    """影刀入口：xbot.app.logging 逐行打日志；返回结构化 dict。不 exit。"""
    path = str(RUNTIME_XLSX)
    if xlsx_path:
        # 影刀参数栏常把路径连引号一起传进来（"F:\...xlsx"），openpyxl 会认成
        # 扩展名 .xlsx" 而拒收 → 先清洗首尾空白/中英文引号
        path = str(xlsx_path).strip().strip('\'"“”').strip() or path
    rows, err = scan(path)
    if err:
        _log("error", f"PRECHECK ABORT: {err}")
        return {"aborted": True, "error": str(err), "total": 0, "pass": 0, "fail": 0,
                "report": f"PRECHECK ABORT: {err}", "rows": []}
    text, n_fail = render(rows)
    for line in text.splitlines():
        _log("warning" if " FAIL " in line else "info", line)
    return {"aborted": False, "error": "",
            "total": len(rows), "pass": len(rows) - n_fail, "fail": n_fail,
            "report": text,
            "rows": [{"row": r, "pid": pid, "tag": tag, "codes": fails}
                     for r, pid, tag, fails, _ in rows]}


def _cli(argv):
    """本机命令行分支：argv 不含脚本名。返回退出码 0/1/2。"""
    ap = argparse.ArgumentParser(description="闲鱼上架队列预检（两段式第1段，引擎无关，只查四项必填）")
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
    text, n_fail = render(rows)
    print(text)
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["行号", "商品ID", "结论", "FAIL码", "描述前段"])
            w.writerows([(r, pid, tag, ";".join(fails), _cell(vals, COL_DESC)[:60])
                         for r, pid, tag, fails, vals in rows])
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
