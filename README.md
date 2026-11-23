# 闲鱼批量上架自动化

> **混合模式**：Python（DrissionPage）做每一步页面操作，影刀 `main` 画布做编排（Excel 循环、状态过滤、回写、收尾）。
> 浏览器统一用固定 profile + 9224 端口启动/复用真实 Edge（与项目一同款方案）。
> 上游套图与文案不在本仓；本仓只做**预检 + 上架**。

---

## 流程

```
precheck（fail>0 整批停）
  ↓
影刀三层画布（2026-11-23 起对齐项目一 v3：main 只编排，Python 做步骤）：
  main（8 块）→ 逐行上架（51 块，持有 Excel 与状态回写）→ 单件上架（50 块，串联 8 步）
  逐行：打开 Excel → 循环行（状态 ≠ 待上架跳过）→ 写「上架中」并保存
        → 调用「单件上架」：
            登录复检掉线 → 中断 → 写「中断·登录失效」并退出循环
            2~6 步任一 ok=False → 返回 step+原因 → 写「上架失败」
            7.发布 → 8.判定 → verdict=success 写「上架成功」
            点过发布但不能确认 → 「上架情况不明，待人工确认」
            state=dry（试发布）→ 不回写，保持「待上架」
  → 关闭 Excel（保存）→ 导出日志
```

**上游合同**（仅此两条）：
1. `products/<商品ID>/套图/` 里有待上传的图片文件（逐文件全量上传，按文件名升序；目录内别放非图片）
2. `商品清单.xlsx` 对应行的 分类/价格/原价/发货/套图目录/描述 六列已填好

---

## 步骤模块（`project/modules/`）

| 步骤 | CodeFlow | 职责 |
|---|---|---|
| 1.登录 | `xianyu_login` | 启动/复用 9224 Edge（固定 profile）+ 登录 + 循环内复检（check） |
| 2.上传套图 | `xianyu_upload` | 目录 `*.*` 递归、按名升序 |
| 3.填写描述 | `xianyu_desc` | contenteditable 先 Ctrl+A 清场 |
| 4.选择分类 | `xianyu_category` | 分类/品牌/成色/长度/材质 五个下拉 |
| 5.填写价格 | `xianyu_price` | 售价 / 原价 |
| 6.设置发货 | `xianyu_shipping` | 包邮 / 按距离 / 一口价 / 无需邮寄 + 自提 |
| 7.发布 | `xianyu_publish` | `PUBLISH\|begin/click` + 点击发布 |
| 8.判定回写 | `xianyu_verdict` | `PUBLISH\|verdict` 判定（跳商品页=成功） |

共用：`tool/xianyu_common.py`（路径/状态/日志）、`tool/ui_action.py`（pick/click/fill/wait_stable，同项目一 `ui_action`）、`tool/xianyu_excel.py`（清单读写，供单步测试与行取值）。

**元素表归各步骤自己持有**：每个步骤文件顶部的 `ELEM` 只写本步骤用到的元素，改版只改那一个文件。

---

## 商品清单.xlsx 列定义（18 列，索引 0 起；main 按 `loop_excel[n]` 读、写 N 列状态）

| 索引 | 列名 | 读取 | 说明 |
|----|------|------|------|
| 0 | 商品ID | — | P001…，人工定位用 |
| 3 | 分类路径 | ✔ | `瑜伽垫/安踏/轻微使用痕迹/189/TPE` → 分类/品牌/成色/长度/材质 |
| 6 / 7 | 价格 / 原价 | ✔ | 售价 / 划线价 |
| 8 | 发货设置 | ✔ | 包邮 / 按距离计费 / 一口价 / 无需邮寄，可加「支持自提」 |
| 11 | 套图目录 | ✔ | `products/<ID>/套图/` |
| 12 | 描述 | ✔ | 描述兼标题（≤1500 字） |
| 13 | 状态 | ✔ 读 + 回写 | 发布前「上架中」；结果「上架成功 / 上架失败 / 上架情况不明，待人工确认」；入队口径=人工置「待上架」 |
| 14 | 失败原因 | — | 人工记录 |

---

## 运行要点（实测固化）

- 成败判定：**发布后跳 `/item?id=…` = 成功**；发布按钮仍在 = 补点一次并轮询跳转，仍不能确认 = 不明
- **点过发布之后不写「上架失败」**：失败只属于点发布之前的步骤；无法确认一律「不明」，避免人工看到「失败」重排造成重复 listing
- 分类：五个下拉按路径段顺序选；选项用「包含」匹配（`安踏`→`ANTA/安踏`、`189`→`180-189cm`）；选项出现是异步的，必须轮询
- 描述框是 contenteditable，**先 Ctrl+A 清场**再输入，否则追加两遍
- 发布前写「上架中」并落盘；崩溃后残留「上架中」先 `reconcile.py` 对账，不自动改回「待上架」
- 凭据只在 `project/conf/credentials.local.json`；浏览器 profile 在 `project/runtime/profile`（均 gitignore）
- **上架记录日志（ledger）**：每次判定写一条 `confirm`（成功/不明），只做追溯与统计，**不参与拦截**；它不感知平台侧删除，修正记录用 `ledger.py release <ID>`

---

## 单步测试

```powershell
python "project/modules/1.登录/xianyu_login.py" --open   # 自动启动/复用 9224 浏览器
python "project/modules/2.上传套图/xianyu_upload.py" --row 6 --open
python "project/modules/4.选择分类/xianyu_category.py" --row 6
python "project/modules/7.发布/xianyu_publish.py" --row 6                  # 只验证，不点
python "project/modules/7.发布/xianyu_publish.py" --row 6 --confirm-publish # 真发

# 离线节点测试
python -m unittest discover -s "project/modules/测试" -t "project/modules/测试"
```

`--open` 会先刷新到发布页（清空未提交表单）；不加则操作当前页面。

---

## 文件清单

| 文件 | 作用 |
|------|------|
| `project/modules/` | 步骤 CodeFlow（业务真源）+ 每节点 `logic.md` 逻辑文件 + common + 测试 + README |
| `project/modules/主流程_main.md` · `逐行上架.md` · `单件上架.md` | 影刀三层画布转录（8 / 51 / 50 块） |
| `project/docs/archive/咸鱼_批量上架_旧画布历史.md` | 已删除的旧画布转录（192 个指令块，仅审计） |
| `project/canvas/main.json` | `main` 画布结构化快照 |
| `project/tools/precheck.py` | L0 预检（fail / warn 两级） |
| `project/tools/preflight.py` | 跑前体检（凭据/锁/表头/残留「上架中」/台账） |
| `project/tools/ledger.py` | 上架记录日志（按商品追溯，不拦发布） |
| `project/tools/secret_scan.py` | 凭据扫描（工作区 + git 历史），已接入 `verify.py` |
| `project/tools/metrics.py` | 运行指标：`events.jsonl` + `log_parse` 汇总 → `docs/量化结果.md` |
| `project/tools/reconcile.py` | 「上架中」对账清单 + 按人裁决回填 |
| `project/tools/log_parse.py` | 影刀日志 → JSONL + 每件耗时 |
| `project/tools/verify.py` | 改动闸门：快照 + 块数 + 块号 + 两套测试 |
| `project/tools/shadowbot-canvas/` | 影刀 MCP 工具箱（画布转录 + studio-mcp 40 工具代理） |

---

## MCP：画布不只可读，也可写

`shadowbot-canvas` MCP 把编辑器 studio-mcp 的 40 个工具代理为 `sb_*`：

| 能力 | 工具 |
|------|------|
| 改画布 | `sb_flow_edit_blocks`、`sb_flow_fill_blocks`、`sb_flow_toggle_blocks` |
| 改 CodeFlow | `sb_codeflow_read` / `sb_codeflow_write` |
| 跑与观测 | `sb_app_run`、`sb_app_wait_run_finish`、`sb_app_logs` |
| 安全网 | `sb_app_copy_flow`、`sb_app_save`、`sb_app_reload`、`sb_diagnostics_snapshot` |

**⚠️ `sb_app_run main` = 真实发布**：测试用单步命令，不要直接跑 main。
