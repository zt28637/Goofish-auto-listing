# N8 判定回写层 · 逻辑文件

> 一个节点一个文件。实现契约：[../README.md](../README.md) · 画布转录：[../主流程_main.md](../主流程_main.md)（059–078 块）

---

## 1. 这个节点是干什么的

- **一句话**：点过发布之后，只回答一个问题——**能不能证明发出去了**。能证明 = `success`；不能证明 = `unknown`。
- **没它会怎样**：
  - 把「点了但没跳转」误判成失败 → 人工重排 → 重复 listing；
  - 把「没点成」误判成成功 → Excel 写成功、平台没有 → 假成功。
- **它不负责**：不点发布（归 N7）、不写 Excel（画布写）、不查重（ledger 只记录）。
- **边界**：**点过发布之后不再返回 `failed`**（2026-11-17 口径）。失败只属于点发布之前的步骤。

---

## 2. 总流程

```text
画布 059 调用 {pid} → judge(page, pid)
  │
  ├─ 当前 URL 含 /item ？
  │   └─ 是 → success（第一锚）
  │
  ├─ 页头「咸鱼ID」元素在？（3s）
  │   └─ 是 → success（旧锚兜底）
  │
  ├─ 发布按钮还在？（2s）
  │   ├─ 是 → 补点一次 → 轮询 /item 5s
  │   │        ├─ 跳了 → success
  │   │        └─ 没跳 → unknown
  │   └─ 否 → 继续
  │
  └─ 以上都不成立 → unknown
  │
  └─ 每条判定只落一次：PUBLISH|verdict 事件 + ledger confirm
  │
  └─ 画布 060：本行判定 = 判定结果.get('verdict', 'unknown')
       ├─ success → 写「上架成功」
       └─ 否则     → 写「上架情况不明，待人工确认」
     Catch（068–078）三分支：
       ├─ 本行判定=success → 上架成功
       ├─ 已点发布        → 不明
       └─ 否则            → 上架失败
```

---

## 3. 动作细节

### 3.1 判定主流程

```text
judge(page, pid, retry=True)
├─ "/item" in page.url → _done(success)          ← 第一锚
├─ page.ele(咸鱼ID, 3s) → _done(success)         ← 旧锚兜底
├─ page.ele(发布, 2s) ？
│   ├─ 是 → 补点（见 3.2）
│   └─ 否 → 继续
└─ _done(unknown)                                ← 什么都不认识，不猜
```

| 结论 | 判据 | 说明 |
|------|------|------|
| `success` | URL 含 `/item` | 第一锚，2026-11-09 实测 |
| `success` | 咸鱼ID元素在 | 旧锚兜底 |
| `unknown` | 其余全部 | 包括「按钮在、补点没跳」「页面不认识」 |

> **为什么 URL 是第一锚**：发布成功会直接跳 `/item?id=<商品ID>`，比页头元素更稳定。
> **为什么不看 toast**：toast 弹窗已实测不可判（`MEMORY.md` §3）。

**失败怎么办**：

| 现象 | 判据 | 返回 | 画布写入 |
|------|------|------|----------|
| 补点点击抛错 | `click()` 异常 | `unknown` | 不明 |
| 补点后不跳转 | 5s 轮询无 `/item` | `unknown` | 不明 |
| 页面完全不认识 | 三锚都不成立 | `unknown` | 不明 |
| `judge` 自身异常 | `main` 捕获 | `unknown` + `ok=false` | Catch：已点发布 → 不明 |

> **不允许「猜失败」**：把不确定写成失败，会让人工重排并制造重复 listing；「不明」才是可执行的中间态。

### 3.2 补点与轮询

```text
发布按钮在
├─ retry=False → 记日志「按口径不补点」→ unknown
├─ click(发布)
│   ├─ 抛错 → 记日志「补点失败」→ unknown
│   └─ 成功 → 继续
└─ _poll_item(5s, 步长 0.5s)
    ├─ URL 含 /item → success
    └─ 超时       → unknown
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `retry` | 是否补点 | `True` |
| 轮询窗口 | `RETRY_WAIT` | 5.0s |
| 轮询步长 | `step` | 0.5s |

> **只补一次**：连续补点会在网络抖动时制造重复提交。5s 是给异步跳转的窗口，不是重试次数。
> 2026-11-17 起不再「固定等 2s 就判失败」，跳转慢只会落到「不明」（失败模式 G7）。

### 3.3 状态映射与台账

```text
_done(pid, result)
├─ event("PUBLISH|verdict", pid, result)
├─ _record(pid, result) → ledger.confirm(pid, success/failed/unknown, run_id)
└─ return result

apply(state, rn, pid, write_wb, write_ws, led, dry_run)   ← 代码侧参考答案
├─ state == "dry" → 返回 "dry"，不写
├─ 映射：success→上架成功  failed→上架失败  其它→上架情况不明，待人工确认
├─ 非 dry_run：excel.set_status(...) + led.confirm(...)
└─ event("count_"+state) → 返回 status
```

| verdict | 中文状态 | 是否允许 |
|---------|----------|----------|
| `success` | 上架成功 | ✅ |
| `failed` | 上架失败 | 仅发布前步骤；`judge()` 不返回 |
| `unknown` | 上架情况不明，待人工确认 | ✅ |
| `dry` | —（不写） | 单步验证 |

> 枚举必须与画布完全一致（`common` 注释：手改错字即失配）。
> 台账 `confirm` 只做统计与追溯，**不参与重发拦截**；平台侧人工删除本地感知不到。

---

## 4. 对外契约

| 场景 | `verdict` | 画布写入 |
|------|-----------|----------|
| URL 跳到 `/item` | `success` | 上架成功 |
| 咸鱼ID元素在 | `success` | 上架成功 |
| 发布按钮在 + 补点后跳转 | `success` | 上架成功 |
| 发布按钮在 + 补点后仍不跳 | `unknown` | 上架情况不明，待人工确认 |
| 什么都判断不了 | `unknown` | 上架情况不明，待人工确认 |
| `main` 自身异常 | `unknown`（显式） | 不明——**绝不能缺 `verdict` 键** |

> **`failed` 不在这里出现**：代码里保留了 `failed` 分支（`apply` / 台账兼容旧记录），但 `judge()` 不会返回它。

---

## 5. 已知缺口与实测记录

**判定锚点**：

| 锚 | 结论 | 证据 | 日期 |
|----|------|------|------|
| URL 跳到 `/item` | **第一锚** | 真机实测；代码注释 | 2026-11-09 |
| 页头「咸鱼ID」元素 | 旧锚兜底 | 元素表 + `test_success_anchor` | 2026-11-09 |
| 发布按钮仍在 | 不能证明没发 → 补点后只认成功/不明 | 代码 + 失败模式 G3/G7 | 2026-11-17 |
| toast | **不可信**，不作判据 | `MEMORY.md` §3 | 2026-10-07 |

**2026-11-17 口径变更（E23）**：

- 点过发布之后**不再写「上架失败」**：`judge()` 只返回 `success` / `unknown`。
- 补点后轮询 `/item` 最长 5s，不再固定等 2s 判死。
- `main` 异常分支也返回 `verdict:"unknown"`，画布不会因缺键 `KeyError` 被兜成「上架失败」。
- Catch 三分支：`本行判定=success` → 成功；`已点发布` → 不明；否则 → 失败。

**台账**：

| 结论 | 证据 |
|------|------|
| 台账只记录、不拦发布 | `AGENTS.md` §核心约束 8；2026-11-09 定调 |
| `confirm` 统一存中文结果，`state()` 兼容旧英文 | 工作日志 2026-11-17 |
| 修正记录用 `ledger.py release <ID>` | `AGENTS.md` 同上 |

**已知缺口**：

| 编号 | 问题 | 等级 | 现状 |
|------|------|------|------|
| G4 | 平台异步审核 → 事后下架，本地仍记成功 | ⚪ | 未做定期对账 |
| G8 | 点击前后网络中断 → 只能到 `unknown` | 🟡 | 这就是「不明」的存在理由 |
| G9 | 本地记成功 ≠ 平台在线 | ⚪ | 未做抽样核验 |
| — | `click_failed` 是否可能「点了但抛错」 | 🟡 | 当前按没点处理，待验证 |

**未验证**：

- [ ] 发布成功到 URL 跳转的实际耗时分布（决定 5s 是否够）。
- [ ] 平台审核后下架的商品，能否用「我的发布」页面对账（G9）。
- [ ] 点过发布但页面回到新表单（无 `/item`、按钮在）时，补点的实际行为。

---

## 6. 测试与回归

| 用例 | 断言 |
|------|------|
| `test_success_anchor` | 咸鱼ID元素在 → success |
| `test_success_by_item_url` | URL 含 `/item` → success |
| `test_unknown_anchor` | 三锚都不成立 → unknown |
| `test_clicked_but_unconfirmed_is_unknown` | 按钮在、不跳 → unknown |
| `test_retry_click_then_navigates_is_success` | 补点后跳转 → success |
| `test_no_retry_after_click_is_unknown` | `retry=False` 且按钮在 → unknown |
| `test_main_error_still_returns_unknown_verdict` | 异常也带 `verdict:"unknown"` |
| `test_success_records_ledger` | success 写台账 |
| `test_success` / `test_failed` / `test_unknown` | `apply` 三种映射 |
| `test_dry_writes_nothing` | dry 不写表不写台账 |

```powershell
python -m unittest discover -s "project/modules/测试" -t "project/modules/测试"
python "project/modules/8.判定回写/xianyu_verdict.py" --pid P001
```

---

## 7. 对应代码

- 文件：[xianyu_verdict.py](xianyu_verdict.py)
- 只看：`judge()` / `_done()` / `_record()` / `_poll_item()` / `apply()` / `RETRY_WAIT`
- 台账：[../../tools/ledger.py](../../tools/ledger.py)
- 状态常量：[../tool/xianyu_common.py](../tool/xianyu_common.py)
