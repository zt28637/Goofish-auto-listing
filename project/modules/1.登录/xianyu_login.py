# -*- coding: utf-8 -*-
"""上架步骤 1 · 浏览器 + 登录（影刀 CodeFlow：xianyu_login）

职责合并（2026-11-09）：不再单独有「打开浏览器」步骤——登录层自己保证
「固定 profile 的 Edge 已启动 + 登录态可用」，结构复用项目一的 login_browser。

对应画布 014-031 + 032-035：
  · 登录框在 iframe 里；换 tab 后 iframe 会换，必须重取句柄
  · 密码走剪贴板，不落日志
  · 滑块 / 扫码 / 人脸 = 人类专属区：超时即返回失败，不自动重登
  · check_alive() 给编排层逐行复检（描述框不可见 + 登录表单可见 = 掉线）

本步骤自己的元素表 ELEM；改版只改这里。
"""

# ---- 仓库内跨文件夹 import 垫片（影刀 CodeFlow 是平铺的，正式跑时为空操作）----
import os as _os
import sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__)) if "__file__" in globals() else ""
_ROOT = _os.path.dirname(_HERE) if _HERE else ""
_MODS = ("tool", "1.登录", "2.上传套图", "3.填写描述", "4.选择分类",
         "5.填写价格", "6.设置发货", "7.发布", "8.判定回写")
for _p in ([_HERE] + [_os.path.join(_ROOT, _d) for _d in _MODS] if _ROOT else [_HERE]):
    if _p and _p not in _sys.path:
        _sys.path.insert(0, _p)

import json
import os
import random
import time

import xianyu_common as common
import ui_action

# 本步骤的元素（登录 iframe 内 + 判断「已登录」用的描述框）
ELEM = {
    "密码登录选项": ["text:密码登录"],
    "登录表单短信登录": ["text:短信登录"],
    "手机号输入框": [
        "css:input[placeholder*='账号名']",
        "css:input[placeholder*='手机号']",
        "xpath:/html/div[1]/div[1]/div[1]/div[1]/form[1]/div[1]/div[2]/input[1]",
    ],
    "《隐私政策》": ["@id=fm-agreement-checkbox", "class:fm-agreement-text"],
    "登录按钮": ["css:button.fm-button.password-login", "text=登录"],
    "快速进入": ["text:快速进入"],
    # 只用于「是否已登录」的判据：描述框在=登录态正常
    "描述输入框": ["css:[contenteditable=true]"],
}


# 浏览器（与项目一 login_browser 同款：固定 profile + 调试端口 + 反自动化标识）
PORT = int(os.environ.get("GOOFISH_RPA_PORT", "9224"))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PROFILE = os.path.join(common.PROJECT_ROOT, "project", "runtime", "profile") if common.PROJECT_ROOT else ""


def _port_open(port=PORT, timeout=1.0):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def _attach(port=None):
    """attach 到已启动的浏览器。单独成函数，方便测试替换。"""
    from DrissionPage import ChromiumPage
    return ChromiumPage("127.0.0.1:%d" % (port or PORT))


def goto(page, url, retries=2):
    """导航到 url；冷启动断连时重连再试。

    冷启动时 Edge 会恢复上次的标签页，DP 拿到的首个 page 可能被顶掉
    （PageDisconnectedError）或卡在 stopLoading；重连一个新句柄即可恢复。
    返回最终可用的 page——调用方必须用返回值，不能继续用旧句柄。
    """
    last = None
    for attempt in range(retries + 1):
        try:
            page.get(url, timeout=30)
            return page
        except Exception as e:
            last = e
            common.log("[登录] 打开页面失败（第%d次）：%s" % (attempt + 1, type(e).__name__))
            if attempt < retries:
                time.sleep(1.5)
                try:
                    page = _attach()
                except Exception:
                    pass
    raise last


def ensure_browser():
    """确保端口上有可用的 Edge：已开则 attach 验活，否则用固定 profile 启动。"""
    from DrissionPage import ChromiumPage, ChromiumOptions
    if _port_open():
        try:
            page = _attach()
            _ = page.url
            return {"ok": True, "launched": False, "detail": "复用已有浏览器",
                    "port": PORT, "profile": PROFILE}
        except Exception as e:
            return {"ok": False, "launched": False, "detail": "端口已开但 attach 失败：%s" % type(e).__name__,
                    "port": PORT, "profile": PROFILE}

    co = ChromiumOptions()
    if os.path.exists(EDGE):
        co.set_browser_path(EDGE)
    if PROFILE:
        try:
            os.makedirs(PROFILE, exist_ok=True)
        except OSError:
            pass
        co.set_user_data_path(PROFILE)
    co.set_local_port(PORT)
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_argument("--no-first-run")
    co.set_argument("--no-default-browser-check")
    co.headless(False)
    try:
        page = ChromiumPage(co)
        time.sleep(1)                      # 等 Edge 恢复标签页/首个导航落定
        page = goto(page, common.PUBLISH_URL)
        time.sleep(2)
        return {"ok": True, "launched": True, "detail": "已启动浏览器",
                "port": PORT, "profile": PROFILE}
    except Exception as e:
        return {"ok": False, "launched": False, "detail": "启动失败：%s: %s" % (type(e).__name__, e),
                "port": PORT, "profile": PROFILE}


def is_logged_in(page):
    """登录态判据：闲鱼认证 cookie 在，或发布表单可见。"""
    try:
        ck = {c.get("name") for c in page.cookies(all_domains=True)
              if "goofish" in (c.get("domain") or "")}
        if "unb" in ck or any((n or "").startswith("_nk_") for n in ck):
            return True
    except Exception:
        pass
    return page.ele(ELEM["描述输入框"][0], timeout=2) is not None


def load_credentials():
    phone = os.environ.get("XIANYU_PHONE")
    password = os.environ.get("XIANYU_PASSWORD")
    if (not phone or not password) and common.CRED and os.path.exists(common.CRED):
        with open(common.CRED, encoding="utf-8") as f:
            data = json.load(f)
        phone = phone or data.get("phone")
        password = password or data.get("password")
    if not phone or not password:
        raise RuntimeError("缺少凭据：project/conf/credentials.local.json 或 XIANYU_PHONE/XIANYU_PASSWORD")
    return str(phone).strip(), str(password).strip()


def login_doc(page, timeout=10):
    """返回「密码登录 tab 可见」的登录 iframe；超时 None（残留 iframe 不算要登录）。"""
    from DrissionPage.errors import ElementLostError, ContextLostError
    end = time.time() + timeout
    while time.time() < end:
        fe = None
        for loc in common.LOGIN_FRAME:
            fe = page.ele(loc, timeout=1)
            if fe:
                break
        if not fe:
            return None
        try:
            if fe.wait.ele_displayed(ELEM["密码登录选项"][0], timeout=2):
                return fe
        except (ContextLostError, ElementLostError):
            time.sleep(0.5)
    return None


def ensure_login(page):
    """密码登录 → 勾隐私 → 等待 → 快速进入。返回 (ok, detail)。"""
    page.wait.doc_loaded(timeout=15)
    if is_logged_in(page):
        common.log("[登录] cookie/表单显示已登录")
        return True, "already"
    doc = login_doc(page)
    if not doc:
        common.log("[登录] 未见登录框，视为已登录")
        return True, "already"
    phone, password = load_credentials()
    if doc.ele(ELEM["登录表单短信登录"][0], timeout=3):
        ui_action.click(doc, ELEM, "密码登录选项")
        time.sleep(1)
        doc = login_doc(page) or doc          # 换 tab 换了 iframe，重取句柄
    ui_action.click(doc, ELEM, "手机号输入框")
    page.actions.type([phone, common.keys().TAB], interval=0.05)
    _set_clipboard(password)
    page.actions.type((common.keys().CONTROL, "v"))
    time.sleep(1)
    try:
        ui_action.click(doc, ELEM, "《隐私政策》", timeout=5)
    except Exception:
        common.log("[登录] 隐私政策勾选失败，继续尝试登录")
    time.sleep(1)
    ui_action.click(doc, ELEM, "登录按钮")
    time.sleep(random.uniform(5, 7))
    if page.ele(ELEM["快速进入"][0], timeout=2):
        try:
            page.ele(ELEM["快速进入"][0]).click()
            time.sleep(2)
        except Exception:
            pass
    common.log("[登录] 滑块/扫码/人脸=人类专属区：最长等 300s")
    end = time.time() + 300
    while time.time() < end:
        if not login_doc(page, timeout=1):
            common.log("[登录] 成功")
            return True, "login"
        time.sleep(2)
    common.log("[登录] 未完成——本轮不继续（不自动重登）")
    return False, "login_timeout"


def check_alive(page):
    """描述框可见 = 登录态正常；不可见且登录表单可见 = 已掉线。"""
    if page.ele(ELEM["描述输入框"][0], timeout=2) is not None:
        return True
    return login_doc(page, timeout=1) is None


def _set_clipboard(text):
    """密码走剪贴板，避免落日志/键盘记录；失败则仍尝试粘贴。"""
    try:
        import subprocess
        subprocess.run(["powershell", "-command", "Set-Clipboard -Value '" + str(text).replace("'", "''") + "'"],
                       check=True, timeout=10)
    except Exception:
        common.log("[登录] 剪贴板设置失败")


def main(args=None):
    """单步测试入口。无 args=离线自检；args 带 row/excel_row 才连浏览器真跑。"""
    if not args:
        return {"step": 1, "name": "login", "elements": sorted(ELEM.keys())}
    try:
        br = ensure_browser()                      # 浏览器由登录层自己保证
        if not br.get("ok"):
            return {"ok": False, "alive": False, "step": 1, "error": br.get("detail")}
        from DrissionPage import ChromiumPage
        page = ChromiumPage("127.0.0.1:%d" % br["port"])
        if args.get("open"):
            page = goto(page, common.PUBLISH_URL)
        if args.get("check"):                      # 供 main 循环内复检
            return {"ok": True, "alive": check_alive(page)}
        ok, detail = ensure_login(page)
        return {"ok": ok, "step": 1, "detail": detail, "browser": br.get("detail")}
    except Exception as e:
        common.log("[单步] 登录 失败：%s" % e)
        return {"ok": False, "alive": False, "step": 1, "error": str(e)}




if __name__ == "__main__":
    import json
    import sys as _argv_sys
    print(json.dumps(main(common.args_from_argv(_argv_sys.argv)), ensure_ascii=False, indent=1))
