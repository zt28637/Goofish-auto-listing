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
├── 测试/           fakes.py + test_*.py（纯离线，43 条）
└── README.md
```

**元素表归各步骤自己持有**：每个步骤文件顶部的 `ELEM` 只写本步骤用到的元素，
改版时只改那一个文件；`tool/ui_action.py` 只提供通用动作（对应项目一的 `model/tool/ui_action.py`）。

## 影刀 main 的编排（54 块）

```
precheck 闸门（fail>0 直接退出）
→ 打开 Excel（商品清单.xlsx）
→ 调用 xianyu_login     （args={open:true}：确保 9224 浏览器 + 打开发布页 + 登录）
→ 循环 Excel 行：
    状态 ≠ 待上架        → 继续下一行
    登录复检（check）    → 掉线则写「中断·登录失效」并退出循环
    Try：
      调用 xianyu_upload / xianyu_desc / xianyu_category
      分类失败           → 写「上架失败」→ 继续下一行
      调用 xianyu_price / xianyu_shipping
      写「上架中」+ 保存
      调用 xianyu_publish（args={row, pid}）
      调用 xianyu_verdict（args={pid}）→ 按 verdict 写 成功/失败/不明 + 保存
    Catch：写「上架失败」+ 保存
→ 关闭 Excel（保存）
→ 导出运行日志
```

转录：[../主流程_main.md](../主流程_main.md)（编辑器改动后必须重跑 `transcribe_canvas.py main`）。

## 步骤契约

每个步骤 `main(args=None)`：

```python
main(None)                      # 离线自检，返回 {"step": n, ...}
main({"row": [...18 列...]})     # 真跑这一步（需浏览器已停在发布页）
main({"excel_row": 6})          # 行号由模块自己去清单里读
```

返回值统一 `{"ok": bool, "step": n, ...}`；`xianyu_verdict` 额外带 `verdict`
（`success` / `failed` / `unknown`），`xianyu_login` 的 `check` 模式带 `alive`。

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

# 离线节点测试（43 条）
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
