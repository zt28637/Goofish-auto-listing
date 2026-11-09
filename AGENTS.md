# AGENTS.md — AI 协作入口（上架执行引擎 · 2026-11-09 混合模式改版）

> **跨工具统一规范**。工作区：[../AGENTS.md](../AGENTS.md) · 系统记忆：[../MEMORY.md](../MEMORY.md)
> **本仓范围=上架**：把 Excel 里的行变成闲鱼在线商品。生图/文案属上游，**不在本仓**。

---

## 架构：Python 做步骤，影刀 main 做编排

```
影刀 main（54 块画布）
  precheck 闸门 → 打开 Excel → 调用 xianyu_login（启动/复用浏览器 + 登录）
  → 循环行：状态过滤 → 登录复检 → 调用步骤 2~8 → 写状态 + 保存
  → 关闭 Excel → 导出日志
        │
        ▼
project/modules/ 下的步骤 CodeFlow（Python + DrissionPage）
  1.登录（含浏览器启动/复用） 2.上传套图 3.填写描述 4.选择分类
  5.填写价格 6.设置发货 7.发布 8.判定回写
```

- **业务真源 = `project/modules/`**：每一步一个文件、一张自己的元素表 `ELEM`。
- **编排真源 = 影刀 `main` 画布**：循环、筛选、状态回写都在画布；转录 [project/modules/主流程_main.md](project/modules/主流程_main.md)。
- 旧画布 `process3`（192 个指令块）已于 2026-11-09 删除；其转录归档在 [project/docs/archive/](project/docs/archive/)，仅作审计参照。

---

## 核心约束

1. **浏览器由登录层自己保证**：`1.登录` 内的 `ensure_browser()` 用固定 profile（`project/runtime/profile`）+ 端口 **9224** 启动/复用真实 Edge（结构复用项目一 `login_browser`）；项目一占用 9223。不用无痕、不用无头。
2. **改代码后必须同步到影刀**：`codeflow.write` 写入对应流程 → `app.save`；改 `main` 画布后必须重跑 `transcribe_canvas.py main`，再跑 `python project/tools/verify.py --tests`。
3. **上游合同只有两条**：① `products/<商品ID>/套图/` 放好图片（逐文件全量上传，目录内不放非图片）；② `商品清单.xlsx` 行的 列3/6/7/8/11/12（分类/价格/原价/发货/套图目录/描述）填好。
4. **Excel 口径**：影刀 main 按 `loop_excel[n]` 读、写 N 列状态（`上架中 / 上架成功 / 上架失败 / 上架情况不明，待人工确认 / 中断·登录失效`）；发布前写「上架中」并保存。
5. **成败判定**：发布后页面跳到 `/item?id=…` = 成功（2026-11-09 实测）；发布按钮仍在 = 失败并补点一次；其余 = 不明。**不靠 toast**。
6. **循环内登录复检**：main 每行调 `xianyu_login.main({check:true})`；掉线写「中断·登录失效」并退出循环，不自动重登。
7. **凭据不入画布也不入仓**：只从 `project/conf/credentials.local.json` / 环境变量读；日志永不打印手机号与密码。
8. **上架记录日志（ledger）只做数据记录，不拦发布**（2026-11-09 定调）：`8.判定` 判定后写一条 `confirm` 记录（成功/失败/不明），供统计与事后追溯；平台侧人工删除无法被本地感知，因此**不用这份日志拦截重发**。需要修正记录时用 `ledger.py release <ID>`。防止误重发靠 Excel 状态列（只有人工置「待上架」才跑）。

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
    │   ├── tool/ (xianyu_common / ui_action / xianyu_excel)
    │   ├── 测试/ (纯离线节点测试)
    │   ├── 主流程_main.md            # main 画布转录（54 块）
    │   └── README.md
    ├── docs/ 失败模式清单 / 优化路线图 / 工作日志 / 面试速查 / archive(旧画布 192 个指令块的转录)
    ├── canvas/main.json             # main 画布结构化快照
    ├── tools/ precheck / preflight / ledger / reconcile / log_parse /
    │          canvas_snapshot / check_truth_source / check_block_refs / verify / tests
    ├── tools/shadowbot-canvas/      画布转录工具链
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
影刀 main：Excel 循环 → 每行调步骤 0~8（Python/DP 操作真实页面）
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
python project/tools/shadowbot-canvas/transcribe_canvas.py main

# 闸门
python project/tools/verify.py --tests
```

---

## 平台插件扩展位

| 平台 | 校验器 | 执行器 | 状态 |
|------|--------|--------|------|
| 闲鱼 | precheck（六列非空 + fail/warn） | 影刀 main + 步骤 CodeFlow | ✅ 已交付 |
| 淘宝 | 格式 + 平台规则 | 影刀 / API | ⬜ 未来 |
| 亚马逊 | Flat File | Flat File 上传 | ⬜ 未来 |
