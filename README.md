# Skill Garden

集中管理个人 AI Agent 技能，支持本地和远程安装到任意项目。

## 目录结构

```
skill-garden/
├── .common/                                    # 通用技能（按平台分目录）
│   ├── .codex/skills/<name>/                   #   Codex 技能 → <target>/.codex/skills/
│   │   └── SKILL.md
│   └── .claude/skills/<name>/                  #   Claude 技能 → <target>/.claude/skills/
│       └── SKILL.md
├── .trellis/                                   # Trellis 强化补充包
│   ├── .agents/skills/<name>/                  #   Agent 技能（带 frontmatter）→ <target>/.agents/skills/
│   │   └── SKILL.md
│   └── .claude/commands/trellis/               #   斜杠命令（无 frontmatter）→ <target>/.claude/commands/trellis/
│       └── <name>.md
└── scripts/
    └── install.sh                              # 安装脚本
```

> **Note**: `.cursor/commands/` 目录已不再维护，统一使用 `.claude/commands/`。

### .trellis 内两份文件的关系

同一个技能在 `.trellis/` 下有两份文件，内容一致但格式不同：

| 文件 | 格式 | 用途 |
|------|------|------|
| `.agents/skills/<name>/SKILL.md` | 带 YAML frontmatter | 被 trellis 的 agent 系统读取 |
| `.claude/commands/trellis/<name>.md` | 无 frontmatter，纯 markdown | 被 Claude Code 注册为 `/trellis:<name>` 斜杠命令 |

SKILL.md 的 frontmatter 格式：

```yaml
---
name: check-prd
description: "PRD Check — 准确性校验 + 覆盖度扫描"
---
# 命令内容...
```

`.claude/commands/trellis/<name>.md` 就是去掉 `---...---` 后的内容。

---

## 安装

### 安装前置检测

install.sh 会自动检测目标项目的类型，只安装到匹配的目录：

| 检测条件 | 安装内容 |
|---------|---------|
| 目标有 `.codex/` | 安装 `.common/.codex/skills/` |
| 目标有 `.claude/` | 安装 `.common/.claude/skills/` |
| 目标有 `.trellis/` | 安装 `.trellis/.agents/skills/` + `.trellis/.claude/commands/trellis/` |
| 两个都没有 | 默认按 claude 处理 |

### 本地安装

```bash
# 安装全部（自动检测平台）
bash skill-garden/scripts/install.sh /path/to/project

# 只安装指定技能
bash skill-garden/scripts/install.sh /path/to/project check-prd create-prd

# 更新（再次运行即覆盖）
bash skill-garden/scripts/install.sh /path/to/project
```

### 远程安装（首次）

```bash
bash install.sh --repo git@github.com:<user>/skill-garden.git /path/to/project
```

skill-garden 会被 clone 到 `~/.skill-garden`，然后复制技能到目标项目。

### 远程更新

```bash
bash ~/.skill-garden/scripts/install.sh /path/to/project
```

自动 pull 最新后覆盖安装。

---

## 当前技能

### 通用（.common）

| 技能 | 平台 | 说明 |
|------|------|------|
| `sub2api-account-json-fix` | codex, claude | sub2api 账号推送 |

### Trellis 补充包（.trellis）

#### 推荐命令

日常开发中最常用的 5 个命令：

| 命令 | 说明 | 使用时机 |
|------|------|---------|
| `check-all` | 全维度一键检查（正确性 → 假设验证 → 完整性 → 规范性） | 开发完成后、提交前 |
| `check-prd` | PRD 准确性校验 + 覆盖度扫描（含 UI 文案逐字一致性） | PRD 生成后、开发前 |
| `analyze-task` | 任务深度分析与细化 | 开发前，理解任务全貌 |
| `sync-prd` | 代码或需求变更后的 PRD 回补同步 | 实现与 PRD 出现偏差时 |
| `re-implement` | 需求变更后二次实现 | 需求变更需要重新实现时 |

#### 全部技能

| 技能 | 说明 | 备注 |
|------|------|------|
| `check-all` | 全维度代码检查（prd-impl → impl → cross-layer → check） | 包含下面两个 check |
| `check-prd-impl` | 对照 PRD 检查实现 — 找出需求级 BUG | 已包含在 `check-all` Step 1 |
| `check-impl` | 实现后假设验证（API 契约、组件上下文、数据历史、数据流） | 已包含在 `check-all` Step 2 |
| `check-prd` | PRD 准确性校验 + 覆盖度扫描（含 UI 文案逐字一致性） | 独立使用，校验 PRD 本身 |
| `create-prd` | 基于原始需求文档创建 PRD（含 UI 文案原封不动约束） | — |
| `analyze-task` | 任务深度分析与细化 | — |
| `plan-version` | 版本开发计划（需求文档 → 任务拆分） | — |
| `re-implement` | 需求变更后二次实现 | — |
| `sync-prd` | 代码或需求变更后的 PRD 回补同步 | — |

---

## 新增技能

### 新增通用技能

1. 在 `.common/.codex/skills/<name>/` 和/或 `.common/.claude/skills/<name>/` 下创建目录
2. 写 `SKILL.md`（格式取决于平台要求）
3. 不需要的平台可以只建一侧

### 新增 Trellis 技能

1. 在 `.trellis/.agents/skills/<name>/` 下创建 `SKILL.md`（带 frontmatter）：

```yaml
---
name: <name>
description: "<简要描述>"
---
# 命令标题

命令内容...
```

2. 在 `.trellis/.claude/commands/trellis/` 下创建 `<name>.md`（去掉 frontmatter 的同内容文件）

3. 确保两份文件的**正文内容完全一致**，仅 frontmatter 有无的区别
