# 咸鱼上架（Python 做步骤 · 影刀 main 做编排）

> **编排在影刀 main 画布里**：main 负责 Excel 循环、状态过滤、调用步骤、回写状态、收尾；
> 每个步骤是一个独立 CodeFlow（Python + DrissionPage），只管自己那一段页面操作。
> 192 块画布 `process3` 保留为历史参照，不再执行。

## 目录（按上架步骤划分）

```
project/modules/
├── 1.登录/         xianyu_login.py     启动/复用 9224 Edge + 登录 + 循环内复检
├── 2.上传套图/     xianyu_upload.py    目录 *.* 递归、按名升序
├── 3.填写描述/     xianyu_desc.py      contenteditable 清场后输入
├── 4.选择分类/     xianyu_category.py  分类/品牌/成色/长度/材质 五个下拉
├── 5.填写价格/     xianyu_price.py     售价 / 原价
├── 6.设置发货/     xianyu_shipping.py  四分支 + 支持自提
├── 7.发布/         xianyu_publish.py   PUBLISH|begin/click + 点击发布
├── 8.判定回写/     xianyu_verdict.py   PUBLISH|verdict 判定（不写表）
├── tool/         xianyu_common.py    路径 / 状态枚举 / 日志 / 单步入口
│                    ui_action.py        pick/click/fill/hover + wait_stable（同项目一 ui_action）
│                    xianyu_excel.py     清单读写（步骤里读行、供单步测试）
├── 测试/           fakes.py + test_*.py（纯离线，55 条）
└── README.md
```

**元素表归各步骤自己持有**：每个步骤文件顶部的 `ELEM` 只写本步骤用到的元素，
改版时只改那一个文件；`tool/ui_action.py` 只提供通用动作（对应项目一的 `model/tool/ui_action.py`）。

## 逻辑文件（8 个节点各一个 · 先读这里，再读代码）

每个节点目录下的 `logic.md` 是**人怎么判断**的说明书；该节点的 `.py` 是它的实现。
**一个节点一个逻辑文件**，不按动作拆文件；**改行为先改逻辑文件，再改代码，再同步影刀。**

| 节点 | 逻辑文件 |
|------|----------|
| 1.登录 | [logic.md](1.登录/logic.md) |
| 2.上传套图 | [logic.md](2.上传套图/logic.md) |
| 3.填写描述 | [logic.md](3.填写描述/logic.md) |
| 4.选择分类 | [logic.md](4.选择分类/logic.md) |
| 5.填写价格 | [logic.md](5.填写价格/logic.md) |
| 6.设置发货 | [logic.md](6.设置发货/logic.md) |
| 7.发布 | [logic.md](7.发布/logic.md) |
| 8.判定回写 | [logic.md](8.判定回写/logic.md) |

**写法**：每个文件先给总流程图，再按
`动作与代码对照 → 动作细节 → 对外契约 → 已知缺口与实测记录 → 测试与回归 → 对应代码` 写。
逻辑文件只写「人怎么判断」，代码细节不进；没实测的结论标「未验证」，不写成已通过。

## 影刀编排（2026-11-23 起三层，对齐项目一 v3 模式）

**三层 = main(8) → 逐行上架(51) → 单件上架(50)**：画布只做顺序、分支、重试、状态回写；
业务逻辑全在 `xianyu_*` CodeFlow。层间数据走显式 In/Out 参数（`process.run`），
Excel 对象不出「逐行上架」层。

```
main（8 块，纯编排 + 总兜底）
  打印日志 → Try：
    调用流程「逐行上架」（In: 清单路径 / 自动发布；Out: 成功数 / 失败数）
    打印汇总
  Catch：写 runtime/logs/shadowbot_error.txt + error 日志

逐行上架（51 块，Excel 的唯一持有者）
  precheck 闸门（fail>0 直接退出）
  → 打开 Excel → xianyu_login(open) → 循环行：
      状态 ≠ 待上架 → 跳过
      Try：写「上架中」+ 保存
        调用流程「单件上架」（In: row/pid/confirm_publish；Out: ok/state/verdict/step/原因/中断）
        中断=True   → 写「中断·登录失效」→ 退出循环
        verdict=success → 上架成功 / 成功数+1
        state=clicked   → 上架情况不明，待人工确认 / 失败数+1
        state=dry       → 只打日志，保持待上架（试发布不回写）
        否则            → 上架失败 / 失败数+1
      Catch：写「上架情况不明，待人工确认」（Excel 层异常时发布态无法证明，按不明处理）
  → 关闭 Excel → 导出日志 → 打印汇总

单件上架（50 块，8 步串联，自带 Try/Catch 不向调用方抛异常）
  xianyu_login(open+check) → alive=False 置「中断」并返回
  → upload / desc / category / price / shipping
      任一步 ok=False → step=该步号、原因=error 字段，直接返回
  → xianyu_publish → state=clicked/dry/click_failed
  → xianyu_verdict → verdict
  Catch：原因=str(exception)（state 保持已取得的值）
```

转录：[主流程_main.md](主流程_main.md) · [逐行上架.md](逐行上架.md) · [单件上架.md](单件上架.md)
（编辑器改动后重跑 `transcribe_canvas.py`，再 `verify.py`）。

与旧版（单 main 83 块）的口径差异，均为有意变更：
- 「上架中」提前到调用单件流程**之前**写——中断在任意一步都能从 Excel 看出本行进行到一半（对账口径不变：preflight 查「上架中」残留）。
- 逐行层 Catch 统一写「不明」而非「失败」——该层异常发生在发布态不可证明的位置，按「状态必须可证明」只认不明。
- `state=dry`（试发布）不回写任何状态，行保持「待上架」可重跑。

## 步骤契约

每个步骤 `main(args=None)`：

```python
main(None)                      # 离线自检，返回 {"step": n, ...}
main({"row": [...18 列...]})     # 真跑这一步（需浏览器已停在发布页）
main({"excel_row": 6})          # 行号由模块自己去清单里读
```

返回值统一 `{"ok": bool, "step": n, ...}`；`xianyu_verdict` 额外带 `verdict`
（`success` / `unknown`——点过发布之后不再返回 `failed`），`xianyu_publish` 带
`state`（`clicked` / `dry` / `click_failed`），`xianyu_login` 的 `check` 模式带 `alive`
（失败路径显式 `alive:false`）。

## 单步测试

```powershell
python "project/modules/1.登录/xianyu_login.py" --open   # 自动启动/复用浏览器
python "project/modules/2.上传套图/xianyu_upload.py" --row 6 --open
python "project/modules/3.填写描述/xianyu_desc.py" --row 6
python "project/modules/4.选择分类/xianyu_category.py" --row 6
python "project/modules/5.填写价格/xianyu_price.py" --row 6
python "project/modules/6.设置发货/xianyu_shipping.py" --row 6
python "project/modules/7.发布/xianyu_publish.py" --row 6                  # 只验证，不点
python "project/modules/7.发布/xianyu_publish.py" --row 6 --confirm-publish # 真发
python "project/modules/8.判定回写/xianyu_verdict.py" --open

# 离线节点测试（55 条）
python -m unittest discover -s "project/modules/测试" -t "project/modules/测试"
```

`--open` 会先把页面刷新到发布页（会清空未提交的表单）；不加则直接在当前页面操作。

## 硬性边界

- 凭据只在 `project/conf/credentials.local.json` / 环境变量，日志永不打印手机号与密码。
- 浏览器 profile 固定在 `project/runtime/profile`（含登录态，**禁止入仓**）；端口 9224。
- 成败判定只认「页面含咸鱼ID」，不看 toast；失败补点一次与画布一致。
- 发布前先写「上架中」并落盘；崩溃后残留「上架中」必须先 `reconcile.py` 对账，不自动改回「待上架」。
- **影刀 main 是真实发布**：测试用单步命令，不要直接跑 main。

## 分类段口径（2026-11-09 改版）

现网发布页在传图后出现五个独立下拉：**分类 / 品牌 / 成色 / 长度 / 材质**，
与 Excel 列索引 3 的路径段按顺序一一对应：

```
瑜伽垫 / 安踏 / 轻微使用痕迹 / 189 / TPE
 → 分类    品牌             成色       长度   材质
```

匹配用「包含」而不是相等（`安踏`→`ANTA/安踏`、`189`→`180-189cm`）。
任一目标值点不到 → 该行判失败并跳过，不会带着错分类发布。
