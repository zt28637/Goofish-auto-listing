# N2 套图层 · 逻辑文件

> 一个节点一个文件。实现契约：[../README.md](../README.md) · 画布转录：[../主流程_main.md](../主流程_main.md)（025–030 块）

---

## 1. 这个节点是干什么的

- **一句话**：把 `products/<商品ID>/套图/` 里的图片，按文件名顺序一次性交给发布页的文件选择框。
- **没它会怎样**：商品无图或图不全——闲鱼不允许无图发布，或发出去是「假商品」。
- **它不负责**：不生成图片、不压缩、不校验平台规格、不判断上传是否完成（见 §5）。
- **边界**：只认 Excel 列 12（`套图目录`）；目录为空直接熔断，不静默跳过。

---

## 2. 总流程

```text
上传套图（画布 025 调用 {row: list(loop_excel)}）
  │
  ├─ 读 Excel 索引 11（套图目录）
  │
  ├─ 枚举：Path(folder).rglob("*.*") → 按完整路径字符串升序
  │   ├─ 0 个文件 → RuntimeError「套图目录是空的」
  │   └─ ≥1 个文件 → 逐个写 upload_file 事件
  │
  ├─ 上传：找 input[type=file] → input(files) 一次设全 → 等 1s
  │
  └─ 返回 {"ok": true, "step": 2}
        └─ 任何异常 → {"ok": false, "step": 2, "error": "..."}
             └─ 画布 026–029：写「上架失败」→ 保存 → 继续下一行（此时还没点发布）
```

---

## 3. 动作细节

### 3.1 枚举套图目录

```text
folder = str(cell(row, 11))
├─ 空 / 目录不存在 → rglob 为空 → 熔断
├─ files = sorted(str(p) for p in Path(folder).rglob("*.*"))
│   ├─ 空 → RuntimeError("套图目录是空的：<folder>")
│   └─ 非空 → 写 upload_dir + 每个文件一条 upload_file
└─ 返回 files
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `folder` | Excel 0 基索引 11（第 12 列 `套图目录`） | 无，空即失败 |
| 匹配 | `*.*` 递归，不挑扩展名 | — |
| 排序 | 完整路径字符串升序 | `sorted()` |

**判断标准**：列表非空 = 可上传；空 = 熔断（空目录/路径错/目录不存在同一处理）。

**失败怎么办**：`files == []` → `ok=false, error="套图目录是空的：..."`，停本行，画布写「上架失败」。

> **空目录必须熔断**：空上传会让页面「看起来正常」，是假成功的温床；预检也会报 `IMG_BAD`。
> 命名建议 `01_`、`02_` 两位前缀——字符串排序在 `1, 10, 2` 上会错（失败模式 B7）。

### 3.2 上传

```text
_wait_publish_ready(page)              ← 2026-11-24 加：URL 含 goofish.com/publish 时
  轮询 document.readyState=complete（≤30s）；非发布页/测试 Mock 立即返回
pick(page, ELEM, "文件上传", timeout=20)
├─ 候选 1：css:input[type=file]      （2026-11-18 起升为主候选）
├─ 候选 2：tag:input@@type=file      （旧主候选，保留兜底）
└─ 全不中 → RuntimeError → ok=false

uploader.input(files)   ← 一次设全（不是逐个弹框）
sleep(1)
```

**判断标准**：上传框找到且 `input()` 不抛错 = 成功。只判断「文件已交给控件」，**不判断平台是否接收完成**。

> **2026-11-24 实测（三处口径）**：元素明明存在（`accept=image/...`）却「两候选全落空」，根因是**页面未就绪**——登录层 `goto(发布页)` 返回时 DOM 还在导航，20s 内找不到。修法=上传前等 `document.readyState=complete`。判据必须**先确认是发布页**再轮询，否则测试里的 Mock page 会让循环空转（初版即因此把节点测试跑成 MemoryError）。

**失败怎么办**：

| 现象 | 判据 | 后果 |
|------|------|------|
| 上传框找不到 | 两条候选都落空 | `ok=false`，停本行 |
| 控件拒绝路径 | `input()` 抛错 | 同上 |
| 上传异步未完成 | 无法判断 | **不判**，后续步骤可能因缺图失败 |
| 张数不足 | 无法判断 | **不校验**（F1） |

> **不要照搬影刀画布语义**：影刀逐个弹框是「累加」，DP `input(files)` 是「一次设全」。若改成逐个 `input([f])`，后一次会覆盖前一次（失败模式 F6）。

---

## 4. 对外契约

| 项 | 现状 |
|----|------|
| 返回值 | `{"ok": bool, "step": 2, "error": "..."}` |
| 输入列 | 0 基索引 11（第 12 列 `套图目录`） |
| 事件 | `upload_dir`、`upload_file`（每个文件一条） |
| 页面元素 | `文件上传`：`tag:input@@type=file` → `css:input[type=file]` |

---

## 5. 已知缺口与实测记录

**已验证**：

| 结论 | 证据 |
|------|------|
| 目录/排序/空目录熔断 | 代码 + `test_sorts_files` / `test_rejects_empty_folder` |
| 首次真实上架走本层成功 | `docs/工作日志.md` E18（2026-11-09） |
| 非图片文件由预检 `IMG_BAD` 拦截 | `project/tools/precheck.py` |

**已知缺口**：

| 编号 | 问题 | 等级 | 现状 |
|------|------|------|------|
| F1 | 上传张数不校验 → 少图静默发布 | 🔴 | 未做 |
| F2 | 上传异步未完成就继续 | 🟡 | 固定 `sleep(1)` |
| B5 | 目录混入非图片 | 🟡 | 预检兜底 |
| B6 | 格式/尺寸/体积超限 | 🟡 | 预检白名单未加 |
| B7 | `1, 10, 2` 排序 | 🟡 | 约定上游 `01_` 前缀 |
| — | 主候选 `tag:input@@type=file` 未命中，第 2 候选 `css:input[type=file]` 命中 | 🟢 | 自愈生效（2026-11-17 实测） |

**未验证**：

- [ ] 一次传 N 张后，页面缩略图数量 == 文件数（F1 的观测方法）。
- [ ] 中文/空格/`#` 文件名在真实上传框下是否被拒（F7）。
- [ ] 目录内混入 `manifest.json` 时页面表现。

---

## 6. 测试与回归

| 用例 | 断言 |
|------|------|
| `test_rejects_empty_folder` | 空目录抛 `RuntimeError` |
| `test_sorts_files` | 返回顺序按字符串升序 |

```powershell
python -m unittest discover -s "project/modules/测试" -t "project/modules/测试"
python "project/modules/2.上传套图/xianyu_upload.py" --row 6 --open
```

---

## 7. 对应代码

- 文件：[xianyu_upload.py](xianyu_upload.py)
- 只看：`upload_images()` / `ELEM`
- 不用看：`ui_action.pick` 内部重试
