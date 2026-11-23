# N1 登录层 · 逻辑文件

> 一个节点一个文件：本文件写登录层「人怎么判断」；代码是它的实现。
> 实现契约：[../README.md](../README.md) · 画布转录：[../主流程_main.md](../主流程_main.md)（010 / 019–024 块）

---

## 1. 这个节点是干什么的

- **一句话**：只做一件事——维护「可以发」的状态：端口 9224 上有可用的真实 Edge，且闲鱼账号处于登录态。
- **没它会怎样**：
  - 发布页打开是登录页，后面 2–8 步全部找不到元素，整批失败。
  - 程序不知道已经掉线，继续在未登录浏览器上跑，白跑一轮。
  - 每件都要人工先登录，做不到批量。
- **它不负责**：不上传、不填表、不点发布、不判定成败（归 N2–N8）；也不自动过滑块 / 扫码 / 人脸。
- **边界**：只回答「现在能不能发」；不能发就停，不硬跑、不自动重登。

---

## 2. 总流程

```text
调用 xianyu_login.main(args)
  │
  ├─ 无 args → 离线自检：返回 step/name/元素清单，不碰浏览器
  │
  ├─ 1. 启动 / 复用（ensure_browser）
  │   9224 端口通？
  │   ├─ 通 → attach 验活 → 复用
  │   └─ 不通 → 固定 profile 启动 Edge → 等端口
  │        ├─ 启动后等 1s → goto 打开发布页
  │        ├─ 导航断连/超时 → _attach 重连并重试（最多 2 次）
  │        └─ 仍失败 → {"ok":false, "alive":false} → 停
  │
  ├─ args.open=true → goto 导航到发布页（清掉上一件的 /item 页或脏表单）
  │
  ├─ args.check=true → 2. 复检（check_alive）→ 返回 {"ok":true, "alive":bool}
  │
  └─ 否则 → 3. 登录（ensure_login）
       ├─ 已登录 → {"ok":true, "detail":"already"}
       ├─ 走密码登录 → 成功 → {"ok":true, "detail":"login"}
       └─ 300s 内未完成 → {"ok":false, "detail":"login_timeout"}
```

---

## 3. 动作与代码对照

| 动作 | 代码函数 | 什么时候发生 |
|------|----------|--------------|
| 启动 / 复用浏览器 | `ensure_browser()` | 画布 010（整批前）、019（每行前） |
| 登录 | `ensure_login()` / `is_logged_in()` / `login_doc()` | 整批开始，未登录时 |
| 循环内复检 | `check_alive()` | 每行开始前（`{open:true, check:true}`） |
| 凭据与安全 | `load_credentials()` / `_set_clipboard()` | 只在需要登录时 |
| 入口 | `main(args)` | 单步测试 / 画布调用 |

---

## 4. 动作细节

### 4.1 启动 / 复用浏览器

```text
9224 端口通？
├─ 通 → attach ChromiumPage("127.0.0.1:9224") → 读 page.url
│        ├─ 成功 → 复用 {"launched": false}
│        └─ 抛错 → ok=false（端口已开但不可控）
└─ 不通 → 固定 profile 启动 Edge
     ├─ msedge.exe 存在 → 指定路径（不存在则由 DP 找默认）
     ├─ runtime/profile → set_user_data_path
     ├─ set_local_port(9224) + 反自动化 + 非无头
     ├─ 启动成功 → 打开 PUBLISH_URL → 等 2s → {"launched": true}
     └─ 启动抛错 → ok=false
```

| 项 | 值 |
|----|----|
| 端口 | `GOOFISH_RPA_PORT` 或 9224（项目一占 9223） |
| profile | `<repo>/project/runtime/profile`，**禁止入仓** |
| Edge 路径 | `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` |
| 返回 | `{ok, launched, detail, port, profile}` |

**判断标准**：只判断「浏览器可控」，不判断登录态。端口通且能读到 `page.url` = 复用成功；能构造 `ChromiumPage(co)` 且打开发布页 = 启动成功。

**冷启动断连（2026-11-17 修复）**：Edge 恢复旧标签页会让首个 `page` 被顶掉（`PageDisconnectedError`）或卡在 `stopLoading`。`goto()` 在失败后 `_attach()` 重连并重试（最多 2 次）；`main` 与 `common.step_browser` 的 `open` 都走同一个 `goto()`，且必须使用其返回值（重连后是新句柄）。

**失败怎么办**：

| 现象 | 返回 | 停不停 |
|------|------|--------|
| 端口已开但 attach 失败 | `ok=false, detail="端口已开但 attach 失败：<类型>"` | 停 |
| Edge 启动失败 | `ok=false, detail="启动失败：<类型>: <消息>"` | 停 |
| profile 不可写 | `makedirs` 的 `OSError` 被吞，最终由启动结果决定 | 由启动结果决定 |

> `launched=false` 既可能是复用成功，也可能是失败——必须看 `ok` / `detail`。

### 4.2 登录

```text
ensure_login(page)
├─ 等 doc_loaded(15s)
├─ is_logged_in？
│   ├─ goofish cookie 有 unb 或 _nk_* → already
│   └─ 描述框可见 → already
├─ login_doc(10s)：登录 iframe 存在且「密码登录」tab 可见？
│   ├─ 没有 → 视为已登录（乐观）→ already
│   └─ 有 → 密码登录
│        ├─ 短信 tab → 点「密码登录」→ 重取 iframe
│        ├─ 点手机号框 → 键入手机号 + TAB
│        ├─ 密码写剪贴板 → Ctrl+V
│        ├─ 勾《隐私政策》（失败只记日志）
│        ├─ 点「登录」
│        ├─ 出现「快速进入」→ 点它 → 等 2s
│        └─ 最长 300s 轮询：登录 iframe 消失 = 成功
│             ├─ 消失 → login
│             └─ 超时 → login_timeout（不自动重登）
```

**判断标准**：

| 结论 | 判据 |
|------|------|
| 已登录 | cookie 有 `unb`/`_nk_*`，**或** 描述框可见 |
| 登录成功 | 登录 iframe 消失 |
| 登录超时 | 300s 内 iframe 一直在 |
| 不需要登录 | 10s 内找不到登录 iframe |

**已知乐观边界**：`login_doc()` 找不到 iframe 时按已登录处理。页面没加载完、或 iframe 改版也会走到这里——后续步骤找不到元素会自行失败兜底。

**失败怎么办**：

| 现象 | 判据 | 后果 |
|------|------|------|
| 缺凭据 | 环境变量和配置文件都没有 | `ok=false, alive=false`，停 |
| 滑块/扫码/人脸 | 300s 内 iframe 不消失 | `login_timeout`，停，不自动重登 |
| 隐私政策点不中 | 点击抛错 | 记日志，继续点登录 |
| 快速进入点不中 | 点击抛错 | 吞掉，继续轮询 |
| 剪贴板失败 | PowerShell 失败 | 记日志，仍尝试粘贴 |

### 4.3 循环内复检

```text
画布每一行：
  xianyu_login({open: true, check: true})
  ├─ 先回跳发布页（清 /item 结果页 + 脏表单）
  └─ check_alive
      ├─ 描述框可见 → alive=true
      └─ 描述框不可见
           ├─ 登录 iframe 也不可见 → alive=true（不确定，按在线继续）
           └─ 登录 iframe 可见     → alive=false（掉线）

画布 020：not 存活结果.get('alive', False) → 写「中断·登录失效」→ 保存 → 退出循环
```

| 结论 | 判据 | 后果 |
|------|------|------|
| 在线 | 描述框可见 | 继续本行 |
| 掉线 | 描述框不可见 **且** 登录 iframe 可见 | 写「中断·登录失效」，退出循环 |
| 不确定 | 两者都不可见 | 按在线继续，由后续步骤失败兜底 |

> `alive` 缺省按 `False` 判（画布块 020）；失败路径必须显式给 `alive:false`。
> `open:true` 同时是「每行清场」：上一件成功后停在 `/item`，不回跳就没有下一件的表单。

### 4.4 凭据与安全

```text
load_credentials()
├─ 环境变量 XIANYU_PHONE / XIANYU_PASSWORD（优先）
├─ 缺任一个 → project/conf/credentials.local.json
├─ 仍缺 → RuntimeError（不猜、不填默认值）
└─ 返回 (phone, password)
     └─ 密码只写剪贴板 → Ctrl+V；不逐字键入、不写日志
```

| 结论 | 判据 |
|------|------|
| 可用 | 手机号和密码都非空 |
| 不可用 | 任一为空 / 配置文件不存在 / JSON 解析失败 |

> 日志只写结论（「缺凭据」「剪贴板设置失败」），永不打印手机号/密码；`credentials.local.json` 已在 `.gitignore`。

---

## 5. 对外契约

| 场景 | 返回 |
|------|------|
| 离线自检 | `{"step":1, "name":"login", "elements":[...]}` |
| 启动失败 | `{"ok":false, "alive":false, "step":1, "error":"..."}` |
| `check` 模式 | `{"ok":true, "alive":true/false}` |
| 登录成功 | `{"ok":true, "step":1, "detail":"already"/"login", "browser":"..."}` |
| 登录超时 | `{"ok":false, "step":1, "detail":"login_timeout"}` |

---

## 6. 已知缺口与实测记录

**有出处的结论**：

| 结论 | 出处 | 日期 |
|------|------|------|
| 端口 9224、profile 固定 | `AGENTS.md` §核心约束 1 | 2026-11-09 |
| 首次真实上架（P005） | `docs/工作日志.md` E18 | 2026-11-09 |
| 每行 `open+check` | `docs/工作日志.md` E23 | 2026-11-17 |
| 描述框 = 登录态正向锚；登录 iframe = 反向锚 | 代码 + 离线用例 | 2026-11-09 |

**已知缺口**：

| # | 现象 | 影响 | 现状 |
|---|------|------|------|
| L1 | 找不到 iframe 按已登录 | 页面未加载完时可能误判 | 刻意乐观，后续步骤兜底 |
| L2 | 滑块/扫码/人脸 300s 超时 | 无人值守会停 | 口径就是交人工 |
| L3 | 剪贴板可能被覆盖 | 密码粘错 | 设置后立即粘贴 |
| L4 | 同一 profile 双实例 | 端口/profile 抢占 | 未加锁文件 |
| L5 | 改密后不更新配置 | 登录失败 | 手工同步 `credentials.local.json` |
| L6 | 冷启动首次 `--open` 可能 `PageDisconnectedError` 或 `stopLoading` 超时 | 整批起不来 | **已修（2026-11-17）**：`goto()` 失败后 `_attach()` 重连重试（最多 2 次）；冷启动复测 2 轮通过 |

**未验证**：

- [ ] 冷启动（空 profile）→ 人工扫码 → 自动继续的完整链路，尚未留带时间的记录。
- [ ] 掉线写「中断·登录失效」后重跑，Excel 状态是否正确阻止重复发布。

---

## 7. 测试与回归

| 用例 | 断言 |
|------|------|
| `test_login_doc_none_when_no_frame` | 无 iframe → None |
| `test_login_doc_returns_frame_when_tab_visible` | 密码 tab 可见 → 返回 frame |
| `test_login_doc_none_when_frame_is_stale` | 残留不可见 iframe → None |
| `test_is_logged_in_by_cookie` | `unb` / `_nk_*` → True |
| `test_is_logged_in_by_form_when_no_cookie` | 描述框可见 → True |
| `test_is_logged_out_when_neither` | 都无 → False |
| `test_check_alive_true_when_desc_visible` | 描述框在 → True |
| `test_check_alive_false_when_desc_gone_and_login_visible` | 掉线 → False |
| `test_login_failure_reports_not_alive` | 失败路径 `alive:false` |
| `test_load_credentials_env_and_missing` | 环境变量优先；缺项抛错 |
| `test_goto_retries_and_reattaches` | 首次断连 → 重连后成功，返回新句柄 |
| `test_goto_raises_after_retries` | 重连也失败 → 抛错，不假装打开成功 |

```powershell
python -m unittest discover -s "project/modules/测试" -t "project/modules/测试" -p "test_excel_login.py"
python "project/modules/1.登录/xianyu_login.py" --open
python project/tools/verify.py --tests
```

---

## 8. 对应代码

- 文件：[xianyu_login.py](xianyu_login.py)
- 只看：`main()` / `ensure_browser()` / `goto()` / `_attach()` / `ensure_login()` / `check_alive()` / `load_credentials()`
- 不用看：`ui_action` 重试细节、DrissionPage 参数
