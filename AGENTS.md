# AGENTS.md — AI 协作入口（上架执行引擎 · 定稿 2026-10-09）

> **跨工具统一规范**。工作区：[../AGENTS.md](../AGENTS.md) · 系统记忆：[../MEMORY.md](../MEMORY.md)
> **本仓范围=上架**：影刀把 Excel 里的行变成闲鱼在线商品。生图/文案属上游，**不在本仓、本 Agent 不负责、勿在此新增相关内容**。

---

## Agent 层级

```text
L0 系统记忆  ../MEMORY.md              跨项目偏好 · 决策 · 踩坑
L1 全局      skills-pack/rpa/           RPA Skill + USER-CONFIG
L2 工作区    ../AGENTS.md
L3 本项目    AGENTS.md + README.md + project/
```

---

## 核心约束

1. **电商通用上架 · 闲鱼已落地**：影刀操作真实网页（goofish.com/publish，Edge），个人实名免费发布。
2. **画布即真源**：唯一流程 = 影刀 `process3「咸鱼_批量上架」`（127 块）；文档口径以 `project/modules/咸鱼_批量上架.md` 转录为准。**影刀画布改动后必重跑转录工具链**（`project/tools/shadowbot-canvas/` 或 MCP `shadowbot-canvas`）覆盖该 .md，文档与画布不许分叉。
3. **上游合同只有两条**：① `products/<商品ID>/套图/` 放好图片（流程逐文件全量上传、按文件名升序、不挑扩展名→目录内不放非图片文件）；② `商品清单.xlsx` 行的 列3/6/7/8/11/12（分类/价格/原价/发货/套图目录/描述）已填好。怎么生图和写文案不归本仓管。
4. **影刀对 Excel 只读列 3/6/7/8/11/12、只保存不写回**：状态列(13)/失败原因(14) 由人工管理，流程不读不写；**循环 = 全部数据行（第 2 行起），不按状态过滤**——跑前人工确认队列。
5. **成败判定与容错口径不可改**（均为实测结论，详见 README「运行要点」）：判「页面含咸鱼ID元素」=成功（toast 不可信）；级联/动态元素先滚动到视口中上部；多选脏值循环 `{BACKSPACE}` 清空再重勾；成败两路都跳回发布页。

---

## 目录结构（与磁盘一致）

```
AGENTS.md · README.md · .mcp.json（注册 shadowbot-canvas MCP）
└── project/
    ├── modules/
    │   └── 咸鱼_批量上架.md        # 影刀画布 127 块全量转录（studio-mcp 生成，密钥已脱敏）
    ├── tools/shadowbot-canvas/     # 画布转录工具链（可复用到项目一/四）
    │   ├── sb_mcp.py               # 影刀编辑器本地 studio-mcp 客户端（列流程/取块原文）
    │   ├── extract_sb_catalog.py   # 从编辑器 DLL 提取内置指令中文目录 → sb_blocks_zh.json
    │   ├── transcribe_canvas.py    # 覆盖式转录画布 .md（python transcribe_canvas.py [flow_id]）
    │   ├── transcribe_flows.py     # v1：全应用流程清单转录
    │   └── sb_canvas_mcp.py        # MCP 封装（sb_list_flows / sb_get_canvas / sb_transcribe_canvas / sb_refresh_catalog）
    └── runtime/
        ├── 商品清单.xlsx            # 唯一 Excel（18 列定义见 README；影刀只消费 6 列）
        ├── products/<商品ID>/       # 套图/（上传源）+ 原图/（留档）
        ├── data/ · logs/            # 预留
        └── （上游遗留文件如 生图记录.json/旧图归档 不在本仓职责内）
.claude/SKILLS.md · .workbuddy/      # Skill 索引 · 工具运行态（后者已 gitignore）
```

---

## 数据流

```
上游产物（套图目录 + Excel 行填好）
  ↓
【影刀 process3 · 127 块】（README「画布分区细节」表）
  打开发布页/登录 → 循环行：
    套图上传(11) → 描述(12) → 分类级联(3，幂等跳级+BACKSPACE清脏值+先滚动)
    → 价格(6/7) → 发货(8) → 发布 → 判定（成功/失败补点/不明人工确认）→ 跳回发布页
  收尾：保存 Excel → 打印 成功/失败/不明 三项统计
  ↓
闲鱼在线商品 + 运行日志
```

---

## 快速启动

```
# 上架（单件=一行，N 行=小批量）
影刀 → 项目二应用 → process3「咸鱼_批量上架」→ 运行（Excel/products 路径已写死在块 003/004）

# 画布转录再生成（改完影刀流程后必跑）
启动影刀编辑器并停在目标应用页 → python project/tools/shadowbot-canvas/transcribe_canvas.py
```

---

## 平台插件扩展位

| 平台 | 校验器 | 执行器 | 状态 |
|------|--------|--------|------|
| 闲鱼 | 上游交付检查（六列非空） | 影刀 process3 | ✅ 已交付 |
| 淘宝 | 格式 + 平台规则 | 影刀 / API | ⬜ 未来 |
| 亚马逊 | Flat File | Flat File 上传 | ⬜ 未来 |

核心流水线不变，新增平台只加「校验器 + 执行器」；上游合同（Excel + 套图目录）可原样复用。
