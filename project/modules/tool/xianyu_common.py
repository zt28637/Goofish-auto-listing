# -*- coding: utf-8 -*-
"""闲鱼上架 · 公共层（影刀 CodeFlow：xianyu_common）

职责：项目路径解析、状态枚举、日志三落（run.log / events.jsonl / xbot 运行日志）。
不做业务：编排在影刀 main 画布，业务在各步骤模块（0.打开浏览器 ~ 8.判定回写）。
"""

# ---- 仓库内跨文件夹 import 垫片（影刀 CodeFlow 是平铺的，这段在影刀里空转）----
import os as _os
import sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__)) if "__file__" in globals() else ""
if _HERE and _HERE not in _sys.path:          # 影刀运行时不把应用目录放进来
    _sys.path.insert(0, _HERE)
_ROOT = _os.path.dirname(_HERE) if _HERE else ""
for _d in ("tool", "1.登录", "2.上传套图", "3.填写描述", "4.选择分类",
           "5.填写价格", "6.设置发货", "7.发布", "8.判定回写"):
    _p = _os.path.join(_ROOT, _d) if _ROOT else ""
    if _p and _os.path.isdir(_p) and _p not in _sys.path:
        _sys.path.insert(0, _p)

import os as _os
import sys as _sys
_ROOT = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..")) if "__file__" in globals() else ""
for _d in ("tool", "0.打开浏览器", "1.登录", "2.上传套图", "3.填写描述",
               "4.选择分类", "5.填写价格", "6.设置发货", "7.发布", "8.判定回写", "9.编排"):
    _p = _os.path.join(_ROOT, _d) if _ROOT else ""
    if _p and _p not in _sys.path:
        _sys.path.insert(0, _p)


import json
import logging
import os
import sys
import time

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:                      # 影刀 CodeFlow 内联执行时没有 __file__
    HERE = ""

_PROJECT_CANDIDATES = [
    os.environ.get("GOOFISH_RPA_PROJECT"),
    os.path.normpath(os.path.join(HERE, "..", "..")) if HERE else "",
    os.path.normpath(os.path.join(HERE, "..", "..", "..")) if HERE else "",
    os.path.normpath(os.path.join(HERE, "..", "..", "..", "..")) if HERE else "",   # modules/咸鱼上架 → 仓库根
    r"F:\Programs\RPA自动化\2-电商上架自动化",
]


def _first_dir(candidates, required=None):
    for p in candidates:
        if not p or not os.path.isdir(p):
            continue
        if required and not os.path.exists(os.path.join(p, required)):
            continue
        return p
    return ""


PROJECT_ROOT = _first_dir(_PROJECT_CANDIDATES, required="project")
RUNTIME = os.path.join(PROJECT_ROOT, "project", "runtime") if PROJECT_ROOT else ""
EXCEL = os.environ.get("GOOFISH_RPA_EXCEL") or os.path.join(RUNTIME, "商品清单.xlsx")
CRED = os.path.join(PROJECT_ROOT, "project", "conf", "credentials.local.json") if PROJECT_ROOT else ""
TOOLS_DIR = os.path.join(PROJECT_ROOT, "project", "tools") if PROJECT_ROOT else ""

PUBLISH_URL = "https://www.goofish.com/publish"
LOGIN_FRAME = ["@id=alibaba-login-box",
               "css:iframe[frameborder=none][scrolling=no][data-spm-anchor-id*=publish]"]

# 状态枚举：与画布块 037 / 168 / 175 / 180 / 034 完全一致，手改错字即失配
ST_QUEUED = "待上架"
ST_RUNNING = "上架中"
ST_OK = "上架成功"
ST_FAIL = "上架失败"
ST_UNKNOWN = "上架情况不明，待人工确认"
ST_LOGIN_LOST = "中断·登录失效"

RUN_ID = time.strftime("%Y%m%d_%H%M%S")
LOG_DIR = os.path.join(RUNTIME, "logs", "run_" + RUN_ID) if RUNTIME else ""
_events_fp = None

try:
    import xbot
    _xlog = xbot.app.logging
except Exception:
    _xlog = None


def _ensure_log_dir():
    global _events_fp
    if not LOG_DIR:
        return
    os.makedirs(LOG_DIR, exist_ok=True)
    if _events_fp is None:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            handlers=[
                logging.FileHandler(os.path.join(LOG_DIR, "run.log"), encoding="utf-8"),
                logging.StreamHandler(sys.stdout),
            ],
        )
        _events_fp = open(os.path.join(LOG_DIR, "events.jsonl"), "a", encoding="utf-8")


def log(msg):
    _ensure_log_dir()
    logging.info(str(msg))
    if _xlog is not None:               # 影刀不吃 print：日志必须走 xbot
        try:
            _xlog.info(str(msg))
        except Exception:
            pass


def event(kind, **kw):
    """结构化事件：run_start / row_start / upload_file / category_step / count_* / PUBLISH|* / run_end"""
    _ensure_log_dir()
    if _events_fp is None:
        return
    rec = {"run": RUN_ID, "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind}
    rec.update(kw)
    _events_fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
    _events_fp.flush()


def keys():
    from DrissionPage.common import Keys
    return Keys


# ============================================================ 单步骤测试入口
def step_browser(args):
    """单步测试用：确保浏览器在 9224（登录层负责启动/复用），返回 page。"""
    import xianyu_login as login
    br = login.ensure_browser()
    if not br.get("ok"):
        raise RuntimeError(br.get("detail") or "浏览器不可用")
    from DrissionPage import ChromiumPage
    page = ChromiumPage("127.0.0.1:%d" % br["port"])
    if args.get("open"):
        page.get(args.get("url") or PUBLISH_URL)
    return page


def step_row(args):
    """单步测试用：args['row'] 直接给 18 列值，或 args['excel_row'] 给行号去清单里读。"""
    import xianyu_excel as excel
    if isinstance(args.get("row"), (list, tuple)):
        return list(args["row"])
    rn = args.get("excel_row")
    if not rn:
        raise RuntimeError("单步测试需要 --row <Excel行号>，或 args['row'] 传入 18 列值")
    read_ws, _wb, _ws = excel.open_books()
    return excel.row_vals(read_ws, int(rn))


def args_from_argv(argv):
    """命令行参数 → main(args) 的 dict：--row N / --pid X / --open / --confirm-publish / --write / --url U"""
    args = {"open": False, "confirm_publish": False, "write": False}
    it = iter(argv[1:])
    for a in it:
        if a == "--row":
            args["excel_row"] = int(next(it))
        elif a == "--pid":
            args["pid"] = next(it)
        elif a == "--open":
            args["open"] = True
        elif a == "--confirm-publish":
            args["confirm_publish"] = True
        elif a == "--write":
            args["write"] = True
        elif a == "--url":
            args["url"] = next(it)
    return args


def main(args=None):
    """自检入口：报告路径解析结果（不启动浏览器）。"""
    return {"project_root": PROJECT_ROOT, "excel": EXCEL, "log_dir": LOG_DIR,
            "tools": TOOLS_DIR, "run_id": RUN_ID}
