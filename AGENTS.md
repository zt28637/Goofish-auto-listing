# AGENTS.md — AI 协作入口（上架执行引擎 · 2026-11-09 混合模式改版）

> **跨工具统一规范**。工作区：[../AGENTS.md](../AGENTS.md) · 系统记忆：[../MEMORY.md](../MEMORY.md)
> **本仓范围=上架**：把 Excel 里的行变成闲鱼在线商品。生图/文案属上游，**不在本仓**。

---

## 架构：Python 做步骤，影刀画布做编排（三层，2026-11-23 对齐项目一 v3）

```
影刀三层画布（2026-11-23 起对齐项目一 v3 模式：画布只编排，Python 做步骤）
  main（8 块）      打印 → Try：调用「逐行上架」→ 打印汇总 / Catch：写 error 文件 + 日志
  逐行上架（51 块）  precheck 闸门 → 打开 Excel → 循环行：状态过滤 → 写「上架中」
                    → 调用「单件上架」→ 按返回 verdict/state 写状态 + 保存
                    → 关闭 Excel → 导出日志
  单件上架（50 块）  登录复检（掉线置「中断」）→ 步骤 2~6 任一失败即返回 step+原因
                    → 发布 → 判定 → 返回 {ok, state, verdict, step, 原因, 中断}
        │
        ▼
project/modules/ 下的步骤 CodeFlow（Python + DrissionPage）
  1.登录（含浏览器启动/复用） 2.上传套图 3.填写描述 4.选择分类
  5.填写价格 6.设置发货 7.发布 8.判定回写
```

- **业务真源 = `project/modules/`**：每一步一个文件、一张自己的元素表 `ELEM`。
- **编排真源 = 影刀三层画布**（2026-11-23 改版）：main 只做顺序编排与总兜底；「逐行上架」持有 Excel 与状态回写；「单件上架」串联 8 步并吞掉自身异常、以 Out 参数返回结果。转录 [主流程_main.md](project/modules/主流程_main.md) · [逐行上架.md](project/modules/逐行上架.md) · [单件上架.md](project/modules/单件上架.md)。
- **层间合同**：跨流程数据只走 `process.run` 的显式 In/Out 参数（逐行层 In=`清单路径/自动发布`、Out=`成功数/失败数`；单件层 In=`row/pid/confirm_publish`、Out=`ok/state/verdict/step/原因/中断`），Excel 对象不出逐行层，全局变量禁止承载流程态。
- 旧画布 `process3`（192 个指令块）已于 2026-11-09 删除；其转录归档在 [project/docs/archive/](project/docs/archive/)，仅作审计参照。

---

## 核心约束

1. **浏览器由登录层自己保证**：`1.登录` 内的 `ensure_browser()` 用固定 profile（`project/runtime/profile`）+ 端口 **9224** 启动/复用真实 Edge（结构复用项目一 `login_browser`）；项目一占用 9223。不用无痕、不用无头。
2. **影刀客户端必须是 6.3.39**（6.4.14 移除了本地 studio-mcp，`/api/v1/mcp` 全 404，画布工具链全部失效；CLI `studio flow` 命令保留但服务端未实现）。**改代码后必须同步到影刀**：`codeflow.write` 写入对应流程 → `app.save`；改任一画布（main/逐行上架/单件上架）后必须重跑 `transcribe_canvas.py`（无参数=全部映射流程），再跑 `python project/tools/verify.py --tests`。**跑画布相关工具前，编辑器必须停在「自动化上架」应用**：studio-mcp 读的是编辑器当前打开的那个应用，开着别家应用会读到别家画布（2026-11-23 曾因此误报 main 83→16）。`sb_mcp.wrong_app()` 已上门禁，开错应用时快照/块数比对直接拒跑、闸门标「未校验」。（2026-11-23 自动升级 6.3.39→6.4.14 后接口整段消失，已回退；应用数据备份在 `ShadowBot/_backup_20261124`。）
3. **上游合同只有两条**：① `products/<商品ID>/套图/` 放好图片（逐文件全量上传，目录内不放非图片）；② `商品清单.xlsx` 行的 列3/6/7/8/11/12（分类/价格/原价/发货/套图目录/描述）填好。
4. **Excel 口径**：「逐行上架」按 `loop_excel[n]` 读、写 N 列状态（`上架中 / 上架成功 / 上架失败 / 上架情况不明，待人工确认 / 中断·登录失效`）；调用「单件上架」**之前**写「上架中」并保存（2026-11-23 提前，中断可从 Excel 直接看出）。
5. **成败判定（2026-11-17 口径）**：发布后页面跳到 `/item?id=…` = 成功；发布按钮仍在 = 补点一次并轮询跳转，仍不能确认 = 不明。**点过发布之后不写「上架失败」**——失败只属于发布前的步骤（上传/描述/分类/价格/发货/点击本身），否则会诱发人工重排→重复 listing。Catch 按「本行判定=success → 成功 / 已点发布 → 不明 / 否则 → 失败」三分支。**不靠 toast**。
6. **循环内回跳 + 登录复检**：main 每行调 `xianyu_login.main({open:true, check:true})`——先把页面导航回发布页（清掉上一件成功后的 `/item` 页和失败留下的脏表单），再判 `alive`；掉线写「中断·登录失效」并退出循环，不自动重登。`alive` 缺省按 `False` 判。
7. **凭据不入画布也不入仓**：只从 `project/conf/credentials.local.json` / 环境变量读；日志永不打印手机号与密码。
8. **上架记录日志（ledger）只做数据记录，不拦发布**（2026-11-09 定调）：`8.判定` 判定后写一条 `confirm` 记录（成功/失败/不明），供统计与事后追溯；平台侧人工删除无法被本地感知，因此**不用这份日志拦截重发**。需要修正记录时用 `ledger.py release <ID>`。防止误重发靠 Excel 状态列（只有人工置「待上架」才跑）。
9. **逻辑优先（2026-11-17）**：8 个步骤节点各有**一个** `logic.md`（一个节点一个文件，不按动作拆），是「人怎么判断」的真源；改行为先改逻辑文件，再改 `.py`，再 `codeflow.write` 同步影刀。没实测的结论标「未验证」，不写成已通过。
10. **凭据扫描入闸门（2026-11-18）**：`secret_scan.py` 扫已跟踪文件 + 全历史新增行，`verify.py` 已内置。命中就改代码/文档；**只有确认泄露才改写历史**（先备份 + 轮换密码），不要为了「看起来干净」重写。

---

## 目录结构（与磁盘一致）

```
AGENTS.md · README.md · .mcp.json（注册 shadowbot-canvas MCP）
└── project/
    ├── modules/                     # 业务真源（步骤 CodeFlow）
    │   ├── 1.登录/xianyu_login.py      # 含 ensure_browser：固定 profile + 9224
    │   ├── 2.上传套图/xianyu_upload.py
    │   ├── 3.填写描述/xianyu_desc.py
    │   ├── 4.选择分类/xianyu_category.py
    │   ├── 5.填写价格/xianyu_price.py
    │   ├── 6.设置发货/xianyu_shipping.py
    │   ├── 7.发布/xianyu_publish.py
    │   ├── 8.判定回写/xianyu_verdict.py
    │   ├── <节点>/logic.md          # 逻辑文件（一个节点一个文件）
    │   ├── tool/ (xianyu_common / ui_action / xianyu_excel)
    │   ├── 测试/ (纯离线节点测试)
    │   ├── 主流程_main.md            # main 画布转录（8 块）
    │   ├── 逐行上架.md               # process2 画布转录（51 块，Excel 持有者）
    │   ├── 单件上架.md               # process3 画布转录（50 块，8 步串联）
    │   └── README.md
    ├── docs/ 失败模式清单 / 优化路线图 / 工作日志 / 面试速查 / archive(旧画布 192 个指令块的转录)
    ├── canvas/main.json             # main 画布结构化快照
    ├── tools/ precheck / preflight / ledger / reconcile / log_parse /
    │          canvas_snapshot / check_truth_source / check_block_refs / verify / tests
    ├── tools/shadowbot-canvas/      影刀 MCP 工具箱
    ├── conf/credentials.local.json  # gitignore
    └── runtime/ 商品清单.xlsx · products/ · profile/ · logs/ · data/
```

---

## 数据流

```
上游产物（套图目录 + Excel 行填好）
  ↓
precheck（fail>0 整批停）
  ↓
影刀 main→逐行上架→单件上架：Excel 循环 → 每行调步骤 0~8（Python/DP 操作真实页面）
  ↓
闲鱼在线商品 + 状态回写 + runtime/logs/run_*/（run.log + events.jsonl）
```

---

## 快速启动

```
# 正式跑（真实发布）
影刀 → 项目二应用 → main → 运行

# 单步验证（推荐先做；登录层会自动启动/复用 9224 浏览器）
python "project/modules/1.登录/xianyu_login.py" --open
python "project/modules/4.选择分类/xianyu_category.py" --row 6

# 画布转录（改完 main 必跑）
python project/tools/shadowbot-canvas/transcribe_canvas.py   # main + 逐行上架 + 单件上架

# 闸门
python project/tools/verify.py --tests
```

---

## 平台插件扩展位

| 平台 | 校验器 | 执行器 | 状态 |
|------|--------|--------|------|
| 闲鱼 | precheck（六列非空 + fail/warn） | 影刀三层画布 + 步骤 CodeFlow | ✅ 已交付 |
| 淘宝 | 格式 + 平台规则 | 影刀 / API | ⬜ 未来 |
| 亚马逊 | Flat File | Flat File 上传 | ⬜ 未来 |
