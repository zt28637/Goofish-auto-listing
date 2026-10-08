# SKILLS.md — 项目 Skill 索引（上架执行引擎）

> 本仓范围=**上架**（影刀 process3）。生图/文案属上游，已移出本仓；  
> 旧版列出的 `/ecom-product-images`（生图规范）已随范围收窄移除（文件可在 git 历史找回）。

---

## 自定义 Skill（全局安装，来自 skills-pack）

| Skill | 触发 | 本项目用途 |
|-------|------|------|
| `/rpa` | 影刀流程规划 | 改 process3 画布、新增平台字段、异常补救设计——**改完画布必重跑转录**（`project/tools/shadowbot-canvas/`） |
| `/playwright-skill` | 浏览器自动化 | 上架页探查/元素验证的可选路径（正式执行仍走影刀） |

---

## 内置 Skill（直接 `/` 调用）

| Skill | 本项目用途 |
|-------|------|
| `/code-review` | 审查转录工具链 / MCP 服务器代码 |
| `/verify` `/run` | 验证工具链与转录产物 |
| `/security-review` | 检查转录脱敏、Excel 数据外发风险 |
| `/update-config` `/fewer-permission-prompts` | 权限与配置维护 |

---

## 快速调用

```bash
/rpa            规划上架画布改动（分类新增一级/字段换列）
/code-review    审查 shadowbot-canvas 工具链
```
