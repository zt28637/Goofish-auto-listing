# N7 发布层 · 逻辑文件

> 一个节点一个文件。实现契约：[../README.md](../README.md) · 画布转录：[../主流程_main.md](../主流程_main.md)（055–058 块）

---

## 1. 这个节点是干什么的

- **一句话**：在「上架中」已写盘之后，点一次发布按钮，并如实报告「点没点上」。
- **没它会怎样**：商品填好但没提交，Excel 写成功、平台没有——最危险的假成功。
- **它不负责**：不判断成败（归 N8）、不写状态列、不补点、不查重。
- **边界**：只负责「点」；点之前由画布写「上架中」并保存，点之后由 N8 判定。

---

## 2. 总流程

```text
画布 055–056：写「上架中」→ 保存（先落盘，崩溃后可对账）
  │
发布（画布 057 调用 {row, pid, confirm_publish: true}）
  │
  ├─ event PUBLISH|begin(pid)
  │
  ├─ dry_run？（单步默认 yes；画布传 confirm_publish=true → no）
  │   ├─ 是 → 记日志「不点发布」→ state="dry"
  │   └─ 否 → 继续
  │
  ├─ event PUBLISH|click(pid)
  ├─ ui_action.click(发布, timeout=20)
  ├─ wait.doc_loaded(15s)（失败吞掉）
  ├─ sleep(2)
  └─ state="clicked"
  │
  └─ 返回 {"ok": true, "state": "clicked"/"dry"}
        └─ 异常 → {"ok": false, "state": "click_failed"}
             └─ 画布 058：已点发布 = (state == 'clicked')
                  └─ N8 判定；Catch 三分支按「已点发布」决定写不明还是失败
```

---

## 3. 动作细节

```text
publish(page, pid, dry_run=False)
├─ event("PUBLISH|begin", pid)
├─ dry_run → log「不点发布」→ return "dry"
├─ event("PUBLISH|click", pid)          ← 点之前写，崩溃也能知道「可能点过」
├─ ui_action.click(发布, timeout=20)
│   ├─ 候选 1：xpath:/html/body/div[2]/div[2]/div[2]/button[1]
│   ├─ 候选 2：css:button[type=submit]
│   └─ 全不中/连点失败 → 抛错 → main → state="click_failed"
├─ wait.doc_loaded(15s)（异常吞掉）
├─ sleep(2)
└─ return "clicked"
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `pid` | 商品 ID，仅用于事件 | `"TEST"` |
| `confirm_publish` | 画布传 `True`；单步默认不传 | `False`（dry） |
| 发布按钮 | 两条候选 | `ELEM["发布"]` |

**判断标准**：

| 结论 | 判据 |
|------|------|
| `clicked` | `click()` 没抛错（点击动作已执行） |
| `dry` | 显式 dry_run |
| `click_failed` | `main` 捕获到异常 |

> `clicked` **不代表发布成功**——只代表「点过了」。成功与否由 N8 用 URL/元素判定。

**失败怎么办**：

| 现象 | 判据 | 返回 | 画布后果 |
|------|------|------|----------|
| 发布按钮找不到 | 两条候选落空 | `ok=false, state="click_failed"` | 按「没点成」→ 可写「上架失败」 |
| 连点被 SPA 换掉 | `click()` 重试后仍抛错 | 同上 | 同上 |
| 加载超时 | `doc_loaded` 抛错 | 吞掉，仍 `clicked` | 进入判定，由 N8 处理 |
| 页面其实没反应 | 点击成功但无跳转 | `clicked` | N8 判 `unknown`（不写失败） |

> **不在这里补点**：补点逻辑只在 N8，且补点后只认成功/不明。
> **`click_failed` 的假设**：点击抛错时认为按钮没被真正点到；若发现「点了但抛错」的路径，必须改成 `unknown` 语义，否则会诱发重复 listing。

---

## 4. 对外契约

| `state` | 含义 | 画布后果 |
|---------|------|----------|
| `clicked` | 点击动作已执行 | `已点发布=True`；之后只分成功/不明 |
| `dry` | 明确没点（单步验证） | 不算发布 |
| `click_failed` | 点击抛错 | 按「没点成」处理；Catch 可写「上架失败」 |

---

## 5. 已知缺口与实测记录

**有出处的结论**：

| 结论 | 证据 | 日期 |
|------|------|------|
| 发布按钮两条候选：长 XPath + `button[type=submit]` | 代码 `ELEM` | 2026-11-09 |
| 点之前必须已写「上架中」并落盘 | 画布 055–056；失败模式 H2 | 2026-11-07 |
| 单步默认 dry，加 `--confirm-publish` 才真点 | 代码 `main()` | 2026-11-09 |
| 点后等 `doc_loaded` + 2s 再交给判定 | 代码 | 2026-11-09 |
| 异常返回 `click_failed`，画布按「没点成」处理 | E23 改动；工作日志 | 2026-11-17 |

**结构化日志**：

| 事件 | 时机 | 用途 |
|------|------|------|
| `PUBLISH\|begin` | 进入 `publish()` | 证明「准备点」 |
| `PUBLISH\|click` | 点击前 | 证明「可能点过」；崩溃后与 N8 的 `verdict` 对账 |
| `PUBLISH\|verdict` | N8 判定后 | 唯一的结果证据 |

**已知缺口**：

| 编号 | 问题 | 等级 | 现状 |
|------|------|------|------|
| G3 | 失败后补点 → 第一次其实成功 → 重复 | 🟢 | 补点只在 N8，补点后轮询 `/item` |
| E3 | 必填项未填 → 按钮禁用 → 点击无反应 | 🟡 | 表现为 `clicked` 但 N8 判 `unknown` |
| — | `click_failed` 可能「点了但抛错」 | 🟡 | 当前假设不会 |

**未验证**：

- [ ] 按钮禁用时点击的异常类型（决定是否应把 `click_failed` 降级为 `unknown`）。
- [ ] `doc_loaded` 在 SPA 发布成功时的实际耗时分布。

---

## 6. 测试与回归

| 用例 | 断言 |
|------|------|
| `test_dry_does_not_click` | dry 不点、返回 `dry` |
| `test_real_run_clicks_once` | 真跑只点一次、返回 `clicked` |
| `test_main_failure_reports_click_failed` | 异常路径 `state="click_failed"` |

```powershell
python -m unittest discover -s "project/modules/测试" -t "project/modules/测试" -p "test_steps.py"
python "project/modules/7.发布/xianyu_publish.py" --row 6                   # 只验证
python "project/modules/7.发布/xianyu_publish.py" --row 6 --confirm-publish # 真发
```

---

## 7. 对应代码

- 文件：[xianyu_publish.py](xianyu_publish.py)
- 只看：`publish()` / `main()` / `ELEM`
- 不用看：`ui_action.click` 的重试细节
