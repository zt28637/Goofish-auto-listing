# -*- coding: utf-8 -*-
"""咸鱼_批量上架 —— 1:1 复刻影刀 process3（127块，转录源：2-电商上架自动化/project/modules/咸鱼_批量上架.md）

做法照搬，不改逻辑：已知冗余（IF012）原样保留，"失败再点一次发布"（块115）原样保留，
键盘输入统一用 page.actions.type()（CDP 全局键盘→焦点元素，等价影刀"键盘输入"，间隔50ms 同参数）。

影刀概念 ↔ DrissionPage 概念对照（面试台词）：
  网页对象 咸鱼发布页      ↔ page（一个标签页一个对象）
  元素库                   ↔ 本文件 ELEM 注册表（一条 = 一个定位符）
  IF 元素可见(web)         ↔ page.wait.ele_displayed(loc, timeout)
  IF 网页包含(contains_element) ↔ bool(page.ele(loc, timeout))
  点击元素+执行后延迟1s    ↔ ele.click(); time.sleep(1)
  键盘输入(含{TAB})        ↔ page.actions.type([文本, Keys.TAB], interval=0.05)
  设置剪切板+^{v}          ↔ Set-Clipboard + type((Keys.CONTROL,'v'))
  上传文件(web) 逐个弹窗   ↔ input[type=file].input(文件列表)（一次设全，末态一致）
  循环Excel内容            ↔ pandas 行遍历
  等待网页加载完成         ↔ page.wait.doc_loaded()
  滚动元素至可视区域       ↔ ele.scroll.to_see()
  获取相似元素列表(web)    ↔ page.eles(loc)
  获取关联元素(child idx1) ↔ ele.child(index=1)
  影刀自动跨框架          ↔ page.ele('…iframe').doc（10-12 元素库提取实测：登录表单整体在
                            login-iframe-wrap 的 iframe 里——主文档直接跑登录定位符必错元素）
"""
import random
import subprocess
import time
from pathlib import Path

import pandas as pd
from DrissionPage import ChromiumPage, ChromiumOptions
from DrissionPage.common import Keys
from DrissionPage.errors import ContextLostError, ElementLostError
import logging
import urllib.request

# ============ SKILL drissionpage §1/§2/§3：透明层 ============
RUN_DIR = Path(__file__).parent / 'runs' / time.strftime('%Y-%m-%d_%H%M%S')
RUN_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
                    handlers=[logging.FileHandler(RUN_DIR / 'run.log', encoding='utf-8'),
                              logging.StreamHandler()])


def log(*args):
    """一条日志两处落：控制台(StreamHandler) + runs/<时间戳>/run.log；不再双打"""
    logging.info(' '.join(str(a) for a in args))


def ensure_browser(port=9444):
    """10-13 12:59 用户授权自动化流水线：门由脚本自己开。
    先探门验指纹（Browser 须含 Edg——9333 曾被影刀常驻桥冒充的教训）；
    没门→subprocess 拉起克隆档案 Edge→轮询 20s→仍无 Edg 指纹=快速失败。"""
    addr = f'127.0.0.1:{port}'

    def _probe():
        try:
            v = urllib.request.urlopen(f'http://{addr}/json/version', timeout=2).read().decode()
            return 'Edg/' in v
        except Exception:
            return False

    if _probe():
        return
    subprocess.Popen([r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                      f'--remote-debugging-port={port}',
                      f'--user-data-dir={Path(__file__).parent}\\edge_profile'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    end = time.time() + 20
    while time.time() < end:
        if _probe():
            return
        time.sleep(1)
    raise SystemExit(f'[开门失败] {addr} 20s 内无 Edge 指纹。'
                     f'查：影刀常驻桥占端口？档案被别的实例锁？')


def pick(doc, key, timeout=8, required=True):
    """定位符自愈层：ELEM 值可为 str 或候选列表，按序试，首个命中即返回。
    全不中→required 则抛带证据目录的错（step() 会截图存证），否则返回 None。"""
    cands = ELEM[key]
    cands = cands if isinstance(cands, list) else [cands]
    for i, cand in enumerate(cands):
        loc, idx = cand if isinstance(cand, tuple) else (cand, 1)            # 候选可带序号（同式多实例）
        el = doc.ele(loc, index=idx, timeout=timeout if i == len(cands) - 1 else 2)
        if el:
            if i:
                log(f'[自愈] {key} 第{i + 1}候选命中：{loc}')
            return el
    if required:
        raise RuntimeError(f'元素「{key}」全部候选落空：{cands}')
    return None


def click(doc, key, timeout=8):
    """SPA 专治：找到≠点得着（元素可能在 find 与 click 之间被局部刷新换掉）。
    ElementLost→重抓再点，两轮为止。"""
    for _ in range(2):
        el = pick(doc, key, timeout=timeout)
        try:
            el.click()
            return el
        except ElementLostError:
            time.sleep(0.5)
    raise RuntimeError(f'「{key}」连点两轮都被 SPA 换掉，看证据截图')


def step(page, name, fn):
    """步骤级透明：编号+耗时全记录；失败自动截图+HTML 存证到 runs/（复盘三问指着证据答）"""
    t0 = time.time()
    logging.info(f'[STEP] {name} ...')
    try:
        r = fn()
        logging.info(f'[ OK ] {name}  {time.time() - t0:.1f}s')
        return r
    except Exception as e:
        logging.error(f'[FAIL] {name}  {time.time() - t0:.1f}s  {type(e).__name__}: {e}')
        if page is not None:
            import re as _re
            safe = _re.sub(r'[\\/:*?#"<>|\s]', '_', name)                    # 13:27：# 等字符曾坑掉存证
            try:
                page.get_screenshot(path=str(RUN_DIR), name=f'fail_{safe}.png')
                log(f'[EVIDENCE] 截图已存：fail_{safe}.png')
            except Exception:
                log('[EVIDENCE] 截图没抓到')
            try:
                (RUN_DIR / f'fail_{safe}.html').write_text(page.html, encoding='utf-8')
                log(f'[EVIDENCE] HTML 已存：fail_{safe}.html')
            except Exception:
                log('[EVIDENCE] HTML 也没抓到（浏览器可能已死）')
        raise RuntimeError(f'卡在步骤「{name}」，证据在 {RUN_DIR}') from e

# ============ 应用参数（影刀 003-004 ============
PUBLISH_URL = 'https://www.goofish.com/publish'
# 10-13 影刀面板终审：登录 iframe 自带稳定 id（阿里系老式登录框）。
# 位置式备选（若改版 iframe 没 id 再换回）：'css:div[class*="login-iframe-wrap"] iframe'
LOGIN_FRAME = '@id=alibaba-login-box'
ROOT_DIR = r"F:\Programs\RPA自动化\2-电商上架自动化\project\runtime\products"   # 003（画布备着，实际目录走清单列11）
LIST_PATH = r"F:\Programs\RPA自动化\2-电商上架自动化\project\runtime\商品清单.xlsx"  # 004
PHONE = '15270024727'          # 016 键盘输入内容（画布里脱敏，此处明文=本机自用，勿外发）
PASSWORD = 'qweasd31'          # 017 剪切板内容（同上）

# ============ 元素库注册表（影刀元素库 ↔ 定位符）============
ELEM = {
    '密码登录选项':       'text:密码登录',                     # 本会话已实测命中
    '登录表单短信登录':   'text:短信登录',                     # 【猜】文案不对就改这里（原样复刻的冗余IF）
    '手机号输入框':       [('xpath:/html/body/div[1]/div[1]/div[1]/div[1]'
                            '/form[1]/div[1]/div[2]/input[1]'),   # 10-13 影刀库提取，登录 iframe 内文档
                           'css:input[placeholder*="账号名"]',      # 自愈候选：密码 tab 占位文案
                           'css:input[placeholder*="手机号"]'],     # 自愈候选：短信 tab 占位文案
    '《隐私政策》':       ['@id=fm-agreement-checkbox',           # 10-13 影刀面板终审：本体=该 input
                           'class:fm-agreement-text'],           # 自愈候选：label（for=联动勾选）
    '登录按钮':           ['css:button.fm-button.password-login',  # 10-13 影刀面板终审
                           'text=登录'],                            # 自愈候选
    '文件上传':           ['tag:input@@type=file',              # 【猜·10-12】DOM 通则；命中 0 个=在 iframe，先 get_frame
                           'css:input[type=file]'],             # 自愈候选（css 等价写法）
    '描述输入框':         'css:[contenteditable=true]',        # 13:14 活体探针实测：0 个 textarea，
                                                                # 编辑器=contenteditable（class=editor--哈希）
    # 以下四格=10-12 从影刀本地元素库提取（脚本已迁 作品系统\个人资源1-影刀RPA_SKILL\tools\extract_yingdao_elements.py，
    #   源=ShadowBot/users/…/d11f1f15…/xbot_robot/selectorsV2.xml）【待实跑验：index-of-type 基序假设】
    '分类*':              ('xpath:/html/body/div[2]/div[2]/div[1]/form[1]/div[1]/div[2]/div[4]'
                           '/div[1]/div[2]/div[1]/div[2]/div[1]/div[1]/div[1]/div[1]'),
    '选项列表':           'xpath:/html/body/div[5]/div[1]/div[1]/div[2]/div[1]/div[1]/div[1]/div[2]',  # 影刀原名"发饰/头饰"；下拉=portal 挂在 body 第5个div
    # 13:19 探针实测：新版页面 3 个 placeholder=0.00 输入框，按序取前两个（价/原价），第三个疑似运费
    '价格输入框':         [('css:input[placeholder="0.00"]', 1),
                           ('xpath:/html/body/div[2]/div[2]/div[1]/form[1]/div[1]/div[3]/div[2]/div[1]'
                            '/div[1]/div[1]/div[2]/div[1]/div[1]/span[1]/input[1]')],
    '原价输入框':         [('css:input[placeholder="0.00"]', 2),
                           ('xpath:/html/body/div[2]/div[2]/div[1]/form[1]/div[1]/div[3]/div[2]/div[1]'
                            '/div[2]/div[1]/div[2]/div[1]/div[1]/span[1]/input[1]')],
    '包邮按钮':           'text=包邮',                         # 【猜】
    '按距离计费':         'text=按距离计费',                   # 【猜】
    '一口价':             'text=一口价',                       # 【猜】
    '无需邮寄':           'text=无需邮寄',                     # 【猜】
    '支持自提':           'text=支持自提',                     # 【猜】
    '发布':               ['text=发布',                          # 【猜】
                           'xpath:/html/body/div[2]/div[2]/div[2]/button[1]',  # 影刀库提取
                           'css:button[type=submit]'],          # 自愈候选
    '咸鱼ID':             ('xpath:/html/body/div[2]/div[2]/div[1]/div[1]/a[1]/div[1]'
                           '/div[2]/div[1]/div[1]'),            # 影刀库提取：页头用户区节点；【待实跑验】
}


def _check_elements():
    missing = [k for k, v in ELEM.items() if not v]
    if missing:
        log('元素注册表还没填，去影刀元素库把 XPath 抄进来：')
        for k in missing:
            log(f'  ELEM[{k!r}] = ...')
        raise SystemExit(1)


# ============ 折叠：咸鱼登录（块 009-023）============
def _login_doc(page, timeout=10):
    """取登录 iframe 的【当前】文档句柄。两条实战坑都在这：
    ① 00:23 SPA 先插 about:blank 壳再导航 → 抓早了 ContextLostError → 循环重抓；
    ② 00:28 点"密码登录"换 tab 时闲鱼整个换 iframe → 旧句柄变幽灵（手机号那次"成功"
       其实是打进了短信旧表单的同位路径）→ 换 tab 后必须重新调本函数，不缓存。"""
    end = time.time() + timeout
    while time.time() < end:
        fe = page.ele(LOGIN_FRAME, timeout=1)
        if not fe:
            return None
        try:
            if fe.wait.ele_displayed(ELEM['密码登录选项'], timeout=2):
                return fe
        except (ContextLostError, ElementLostError):                             # 13:07 实锤：ele_displayed 查
            time.sleep(0.5)                                                      # style 时把 ContextLost 包成
    return fe                                                                    # ElementLost 重抛，两个都要接


def do_login(page):
    # 10-13 元素库提取实锤：登录表单整体在 login-iframe-wrap 的 iframe 里。
    # 影刀"网页对象"自动跨帧+每步现查；DP 必须显式进帧且换 tab 后重取句柄。
    page.wait.doc_loaded(timeout=15)                                             # 010
    doc = _login_doc(page)                                                       # 011 判"是否需要登录"（帧在=要登录）
    if doc:
        if doc.ele(ELEM['登录表单短信登录'], timeout=3):                           # 012 原样复刻（已知恒真）
            click(doc, '密码登录选项')                                              # 013
            time.sleep(1)                                                          #   执行后延迟
            doc = _login_doc(page) or doc                                          # ★换 tab 换了 iframe，重取句柄
        click(doc, '手机号输入框')                                                   # 015 点击聚焦（自愈层）
        page.actions.type([PHONE, Keys.TAB], interval=0.05)                        # 016 键盘输入 手机号{TAB}
                                                                                   #   （CDP 全局键盘→焦点元素，跨帧有效）
        subprocess.run(['powershell', '-command', f'Set-Clipboard {PASSWORD}'],
                       check=True)                                                 # 017 设置剪切板
        page.actions.type((Keys.CONTROL, 'v'))                                     # 018 ^{v} 粘贴（密码框全程未捕获）
        time.sleep(1)
        # 019 DP 的 ele() 找不到返回 NoneElement（假值），不抛异常——`or` 兜底链直接用
        click(doc, '《隐私政策》', timeout=5)                                       # 019 自愈层：checkbox→label
        time.sleep(1)
        click(doc, '登录按钮')                                                      # 020 自愈层
        time.sleep(random.uniform(5, 7))                                           # 021 random 5-7s
        # 成功判断（§3 铁律：不靠 toast）——升级：判登录 iframe 整体消失
        log('[登录] 滑块/扫码/人脸=人类专属区：滑块你来拖，二维码用闲鱼APP扫，最长 300s…')
        ok, end = False, time.time() + 300
        while time.time() < end:
            if not page.ele(LOGIN_FRAME, timeout=1):
                ok = True
                break
            time.sleep(2)
        log('[登录] 成功' if ok else '[登录] 未完成 —— 后面步骤大概率全崩，先解决登录')
    else:
        log('[登录] 未见登录框，视为已登录')                                      # 022/else


# ============ 折叠：套图上传（块 025-033）============
def upload_images(page, row):
    folder = str(row[11])                                                          # 026 套图目录=清单列11
    log('[日志] 套图目录:', folder)                                              # 027
    files = sorted(str(p) for p in Path(folder).rglob('*.*'))                      # 028 含子目录，按名排序
    if not files:                                                                  # 14:58 熔断：空目录=假成功温床
        raise RuntimeError(f'套图目录是空的：{folder}（先补图再跑，DRY 也不放过）')
    uploader = pick(page, '文件上传', timeout=20)                                  # 031 的上传控件（自愈层）
    for fp in files:                                                               # 029-032
        log('[上传]', fp)                                                        # 030
    uploader.input(files)                                                          #   影刀逐个弹框=累加；DP 一次设全，末态一致


# ============ 折叠：描述写入（块 034-037）============
def fill_description(page, row):
    click(page, '描述输入框', timeout=20)                                          # 035（自愈层：重抓再点）
    time.sleep(1)
    page.actions.type((Keys.CONTROL, 'a'))                                         # 14:44 全选清场：contenteditable
                                                                                   #   留草稿，不清=追加（同款文两遍）
    page.actions.type(str(row[12]), interval=0.05)                                 # 036 描述=清单列12，50ms/键
                                                                                 #   contenteditable 吃全局键盘，同画布
    time.sleep(1)


# ============ 折叠：分类选择（块 038-082）============
COND = {'全新', '几乎全新', '轻微使用痕迹', '明显使用痕迹'}          # 成色档常见值（13:56 清单实测含"全新"）


def _form_item(page, label, timeout=10):
    """新版页面字段组：按标签名取 ant-form-item 容器（13:44 截图结构）"""
    end = time.time() + timeout
    while time.time() < end:
        for it in page.eles('css:.ant-form-item'):
            parts = (it.text or '').split('\n')
            if parts and parts[0].strip().rstrip('*') == label:
                return it
        time.sleep(0.5)
    return None


def _pick_option(page, word, timeout=3):
    """点下拉选项：10-18 00:05 教训——`text=星巴克` 是精确匹配，真实选项文本是
    「starbucks/星巴克」→ 漏点、品牌留空、核对挂。改为「选项文本包含词」即命中；
    只在可见的 antd 选项里找，避免点到旧 overlay。返回是否点到。"""
    end = time.time() + timeout
    while time.time() < end:
        for opt in page.eles('css:.ant-select-item-option'):
            if word not in (opt.text or ''):
                continue
            try:
                vis = opt.states.is_displayed
            except Exception:
                vis = True
            if vis:
                opt.click()
                return True
        time.sleep(0.3)
    return False


def choose_category(page, row):
    # 13:56 定版：新版=独立字段组（分类*/品牌/成色/发饰分类），清单列3 打包四段。
    # 策略=读字段现值→缺什么补什么（品牌=输入+建议项；成色=点开选档）→终核不齐报错留证。
    path = [p for p in str(row[3]).split('/') if p]
    cond = [t for t in path if t in COND]                                            # 成色档
    brand = path[1] if len(path) > 2 and path[1] not in COND else None               # 14:44：首段后第一个非成色段=品牌
    leaf = path[-1]                                                                  # 族叶子（发饰分类等，字段在才管）
    attrs = [t for t in path if t not in [path[0], brand, leaf] + cond]              # 属性规格段：新版独立区，v1 跳过
    if attrs:
        log(f'[分类] 属性规格段未适配，跳过：{attrs}（站点非必填，见 14:40 证据）')

    def _field_val(label):
        it = _form_item(page, label, timeout=3)
        return (it.text or '') if it else ''

    if brand and brand not in _field_val('品牌'):                                    # 品牌：antd Select 先点开才有 input
        item = _form_item(page, '品牌')
        if item:
            item.click()
            time.sleep(1)
            inp = item.ele('tag:input', timeout=3) or page.ele('css:input[placeholder*="品牌"]', timeout=2)
            if inp:
                page.actions.type(brand, interval=0.05)
                time.sleep(1)
                if not _pick_option(page, brand, 2):                                 # 建议项=包含词的选项
                    page.actions.type(Keys.ESCAPE)                                   # 自由文本，关下拉
            else:
                log(f'[分类] 品牌点开后仍无 input，{brand} 跳过（看证据）')
        time.sleep(0.5)
    for c in cond:                                                                   # 成色：多选标签字段，幂等+清残值
        item = _form_item(page, '成色')
        if not item:
            continue
        vals = [v for v in (item.text or '').split() if v and v != '成色']
        if vals == [c]:
            continue                                                                 # 已 exactly 选中，不动
        item.click()
        time.sleep(0.5)
        for _ in range(len(vals) + 2):                                               # 画布 065 退格法清残留标签
            page.actions.type(Keys.BACKSPACE)
            time.sleep(0.3)
        if not _pick_option(page, c, 3):                                             # 同上，包含匹配
            log(f'[分类] 成色档「{c}」下拉里没找到（看证据）')
        page.actions.type(Keys.ESCAPE)
        time.sleep(0.5)
    leaf_item = _form_item(page, '发饰分类', timeout=3)                              # 族叶子字段：在才管
    if leaf_item and leaf not in (leaf_item.text or ''):
        leaf_item.click()
        time.sleep(1)
        if not _pick_option(page, leaf, 3):                                          # 同上，包含匹配
            log(f'[分类] 叶子段「{leaf}」下拉里没找到（看证据）')
        page.actions.type(Keys.ESCAPE)
        time.sleep(0.5)
    need = [path[0]] + ([brand] if brand else []) + cond + \
           ([leaf] if leaf_item else [])
    cat = ' '.join(_field_val(k) for k in ('分类', '品牌', '成色', '发饰分类'))
    missing = [t for t in need if t not in cat]
    if not missing:
        log(f'[分类] 新版字段核对通过：{need} 全在表单里')
        return
    raise RuntimeError(f'分类核对失败：缺{missing}，字段={cat!r}，清单={row[3]!r}——看证据截图')
    # --- 以下=画布 038-082 级联原版，13:44 新版 DOM 核验后不可达；留档供面试讲"旧页面怎么做的" ---
    path = str(row[3]).split('/')                                                  # 039 分类路径=列3，按/拆
    levels = len(path)                                                             # 040
    cur = 0                                                                        # 041 当前级别
    stall = 0                                                                      # ★偏离1:1新增：同级空转计数（§3教训：外层无限圈要自带出口）
    while cur < levels:                                                            # 042 While
        boxes = page.eles(ELEM['分类*'])                                           # 043 每轮重取（页面刷新句柄失效，§5注）
        if len(boxes) <= cur:                                                      # 044-047 框数没涨上来→等1s跳过
            log(f'[分类] 第{cur + 1}级还没出现，等1s')
            time.sleep(1)
            stall += 1
            if stall >= 10:
                raise RuntimeError(f'第{cur + 1}级分类框 10s 没长出来，数据/页面二选一有问题，停')
            continue
        box = boxes[cur]                                                           # 048
        cur_text = box.text or ''                                                  # 049-050
        target = path[cur]                                                         # 051-052
        if cur_text in target:                                                     # 053 原方向：当前值 in 目标值
            log(f'第{cur + 1}级已正确: {cur_text}，跳过')                          # 054
            cur += 1                                                               # 055
            stall = 0                                                              # ★进级即清零
            continue
        # ---- Else（056-079）：点开这一级并选项 ----
        box.click()                                                                # 058
        time.sleep(1)
        for _bs in range(20):                                                      # 059 清脏值（13:36 加帽：画布原版
            first = box.child(index=1)                                             # 060 无限圈在新DOM上=静默
            cls = (first.attr('class') or '') if first else ''                     # 061 BACKSPACE死循环陷阱3）
            if 'ant-select-selection-overflow-item-suffix' in cls:                 # 062 只剩占位suffix=已清空
                break                                                              # 063
            if not first:
                break                                                              # 新DOM无子节点=视为干净
            page.actions.type(Keys.BACKSPACE)                                      # 065 退格删一个标签
            time.sleep(1)
        else:
            log('[分类] 清脏值 20 次封顶强出（新版 DOM 标记已变，见 SKILL  backlog）')
        time.sleep(1)                                                              # 068
        box.scroll.to_see()                                                        # 069 滚动至可视
        prev = cur
        for opt in page.eles(ELEM['选项列表']):                                     # 070-071
            txt = opt.text or ''                                                   # 072
            if txt in target:                                                      # 073 原方向：选项文本 in 目标值
                opt.click()                                                        # 074
                time.sleep(1)
                cur += 1                                                           # 075
                break                                                              # 076
        time.sleep(1)                                                              # 079
        stall = 0 if cur > prev else stall + 1                                     # ★本级没动=空转+1
        if stall >= 3:
            raise RuntimeError(f'第{cur + 1}级选项里找不到「{target}」，3 轮空转已停（画布原版=死循环）')


# ============ 折叠：价格输入（块 083-089）============
def fill_price(page, row):
    e = pick(page, '价格输入框', timeout=20)
    e.scroll.to_see()                                                              # 084
    e.click()                                                                      # 085
    page.actions.type(str(row[6]), interval=0.05)                                  # 086 价格=列6
    e2 = pick(page, '原价输入框', timeout=20)
    e2.click()                                                                     # 087（画布此处不滚动）
    page.actions.type(str(row[7]), interval=0.05)                                  # 088 原价=列7


# ============ 折叠：发货设置（块 090-104）============
def set_shipping(page, row):
    ship = str(row[8])                                                             # 091 发货设置=列8
    if ship in '包邮':                                                             # 092 原方向：变量 in 常量
        page.ele(ELEM['包邮按钮']).click()                                          # 093
    elif ship in '按距离计费':                                                      # 094
        page.ele(ELEM['按距离计费']).click()                                        # 095
    elif ship in '一口价':                                                          # 096
        page.ele(ELEM['一口价']).click()                                            # 097
    else:                                                                           # 098
        page.ele(ELEM['无需邮寄']).click()                                          # 099
    time.sleep(1)
    if ship in '支持自提':                                                          # 101-103（可与上面叠加）
        page.ele(ELEM['支持自提']).click()
    time.sleep(1)


# ============ 发布 + 成败判断（块 105-122）============
def publish_and_judge(page, cnt):
    # 105 备注：地址采用默认设置（不操作）
    # 14:32 新锚（用户肉眼实锤 P001 已发布成功）：新版 SPA 发布成功=跳回【空白新表单】，
    # 画布旧锚双双失效——咸鱼ID 头部节点改版漂移；"发布按钮还在=失败"在"成功也回新表单"面前反判。
    # 语义重置锚：发布前描述非空 ∧ 发布后描述空 = 表单被清 = 成功；描述仍在 = 被校验拦下。
    ed = pick(page, '描述输入框', timeout=5, required=False)
    before = (ed.text or '').strip() if ed else ''
    import os as _os
    if _os.environ.get('DP_DRY'):                                                  # 14:44 DRY：验到发布前为止，
        log('[判定] DP_DRY=1，跳过真实发布点击（验证模式）')                        #   不给店铺再添真实 listing
        return 'dry'
    click(page, '发布', timeout=20)                                                # 106
    page.wait.doc_loaded(timeout=15)                                               # 107
    time.sleep(3)                                                                  # 108
    ed2 = pick(page, '描述输入框', timeout=5, required=False)
    after = (ed2.text or '').strip() if ed2 else ''
    if before and not after:
        cnt['成功'] += 1                                                           # 110-111
        log('[判定] 表单已清空=发布成功（语义重置锚）')
        return '成功'
    if after:
        cnt['失败'] += 1                                                           # 114
        log('[判定] 描述仍在=被校验拦下，原样保留再点一次')
        click(page, '发布')                                                        # 115 原样保留：再点一次
        return '失败'
    log('[日志] 待人工确认')                                                      # 118
    cnt['不明'] += 1                                                               # 119
    return '不明'


# ============ 主流程（块 001-024、123-127）============
def main():
    _check_elements()

    # 连接架构（10-13 定版，SKILL §1 门①）：浏览器先行带端口启动克隆档案 Edge → gate() 探门 → attach。
    # 不再由 DP 拉起浏览器（本机 11:44 实锤不稳且静默挂起）；启动快捷方式命令在 gate() 报错文案里。
    ensure_browser()                                                               # 12:59 授权：门由脚本自开+验指纹
    page = ChromiumPage('127.0.0.1:9444')                                          # 端口已验→接管现有窗口
    # 002 获取已打开的网页对象：DP 里 page 本身就是网页对象，省
    # 005-007 三个计数变量 → 用一个 dict
    cnt = {'成功': 0, '失败': 0, '不明': 0}                                         # 005-007

    # 008 实测（10-12）：真表名='商品清单'，写 'Sheet1' 直接 ValueError；用索引 0 免疫改名
    df = step(None, '008读商品清单', lambda: pd.read_excel(LIST_PATH, sheet_name=0))
    rows = df.values.tolist()                                                      # 024 起始行2=表头后全部数据行
    import sys as _sys                                                             # 安全阀：argv1=件数 argv2=起始行(0基)
    _limit = int(_sys.argv[1]) if len(_sys.argv) > 1 else len(rows)
    _start = int(_sys.argv[2]) if len(_sys.argv) > 2 else 0
    rows = rows[_start:_start + _limit]                                            # 验第2件=`... 1 1`，不重发第1件

    step(page, '001打开发布页', lambda: page.get(PUBLISH_URL))                     # 001
    step(page, '009-023登录', lambda: do_login(page))                              # 009-023

    for i, row in enumerate(rows):
        log(f'\n======== 第{i + 1}件 ========')
        n = i + 1
        step(page, f'#{n}-025套图上传', lambda r=row: upload_images(page, r))      # 025-033
        step(page, f'#{n}-034描述', lambda r=row: fill_description(page, r))       # 034-037
        step(page, f'#{n}-038分类', lambda r=row: choose_category(page, r))        # 038-082
        step(page, f'#{n}-083价格', lambda r=row: fill_price(page, r))             # 083-089
        step(page, f'#{n}-090发货', lambda r=row: set_shipping(page, r))           # 090-104
        status = step(page, f'#{n}-105发布判定', lambda: publish_and_judge(page, cnt))  # 105-121
        log(f'[第{n}件] {status}')
        step(page, f'#{n}-122回发布页', lambda: page.get(PUBLISH_URL))             # 122 成败都跳回发布页（§3铁律）

    # 124 关闭Excel并保存：DP 只读没写回，如需把 status 写回清单列，加 df.to_excel(LIST_PATH, index=False)
    log(f'上架成功数量：{cnt["成功"]}')                                            # 125
    log(f'上架失败数量：{cnt["失败"]}')                                            # 126
    log(f'上架不明情况数量：{cnt["不明"]}')                                        # 127


if __name__ == '__main__':
    try:
        main()
    except SystemExit as e:                                                        # gate/自检的"有台词退场"
        print(e)
    except Exception:
        logging.exception('本次运行中止——复盘三问指着这里的 traceback 答')          # §3：全文进 run.log
    finally:
        logging.info(f'[复盘] 证据目录: {RUN_DIR}')
