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
├── .trellis/                                   # Trellis 强化补充包（按版本分子目录）
│   ├── old/                                    #   Trellis < 0.5 (默认 fallback)
│   │   ├── .agents/skills/<name>/SKILL.md
│   │   └── .claude/commands/trellis/<name>.md
│   └── 0.5/                                    #   Trellis >= 0.5
│       ├── .agents/skills/<name>/SKILL.md                         # agent 技能
│       ├── .claude/commands/trellis/<name>.md                     # 斜杠命令（非 skill 化的保留）
│       └── .claude/skills/trellis-<name>/SKILL.md                 # Claude harness 自动路由 skill（skill 化的）
└── scripts/
    └── install.sh                              # 安装脚本（读目标 .trellis/.version 智能选 variant）
```

> **Note**: `.cursor/commands/` 目录已不再维护，统一使用 `.claude/commands/`。

### .trellis 版本 variant 说明

install.sh 会读取目标项目的 `.trellis/.version`，按语义化版本选择对应 variant：

| `.version` | 选用 variant | 备注 |
|------------|------------|------|
| `>= 0.5.0`（含 `0.5.0-beta.x`） | `.trellis/0.5/` | 新版：agents 更名 `trellis-implement/trellis-check/trellis-research`；`check-all` skill 化并融合 `check-prd-impl` + `check-impl`（3 维：PRD 实现 + 假设验证 + trellis-check）；部分指令 skill 化（放 `.claude/skills/trellis-<name>/`，不再保留 command 版） |
| 其他（含 `0.4.x`、缺失、无法解析） | `.trellis/old/` | 旧版：agents 名 `implement/check/research`，`check-all` 保留 4 维，全部保留 command 形态 |

两个 variant 的技能名集合大致相同，内容随各自目标版本的 trellis 脚手架调整。

### 三种安装目标

| 源路径（variant 内） | 目标路径 | 用途 |
|------|------|------|
| `.agents/skills/<name>/SKILL.md` | `<target>/.agents/skills/<name>/` | 被 trellis 的 agent 系统读取 |
| `.claude/commands/trellis/<name>.md` | `<target>/.claude/commands/trellis/<name>.md` | Claude Code 斜杠命令 `/trellis:<name>`（适合显式动作，如 push） |
| `.claude/skills/trellis-<name>/SKILL.md` | `<target>/.claude/skills/trellis-<name>/` | Claude harness 按 description 自动路由（适合自然语触发，如 analyze-task） |

> **原则**：一个指令要么保留 command 版、要么做成 skill 版（skill 化后删除 command 副本），避免同一入口有两种触发方式导致混淆。

### .trellis 内同名文件的关系

同一个技能在 variant 目录下有两份文件，内容一致但格式不同：

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
| 目标有 `.trellis/` | 读 `.trellis/.version` 选 `old/` 或 `0.5/`，安装对应目录的 `.agents/skills/` + `.claude/commands/trellis/` |
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

日常开发中最常用的命令：

| 命令 | 说明 | 使用时机 |
|------|------|---------|
| `push` | 一键 commit → push → 可选 merge 到目标分支 | 代码写完要提交时 |
| `check-all` | 全维度一键检查（融合 check-prd-impl + check-impl + trellis-check 三维） | 开发完成后、提交前 |
| `check-prd` | PRD 准确性校验 + 覆盖度扫描（含 UI 文案逐字一致性） | PRD 生成后、开发前 |
| `analyze-task` | 任务深度分析与细化（0.5+ 已 skill 化，触发 skill `trellis-analyze-task`） | 开发前，理解任务全貌 |
| `draw-uml` | 以 PM / 业务架构师视角用 UML 活动图梳理业务（每次自动渲染 PNG 并读图展示） | 需要可视化理解业务流程时 |
| `sync-prd` | 代码或需求变更后的 PRD 回补同步 | 实现与 PRD 出现偏差时 |
| `re-implement` | 需求变更后二次实现 | 需求变更需要重新实现时 |

#### 全部技能

| 技能 | 说明 | 备注 |
|------|------|------|
| `check-all` | 全维度代码检查（内嵌融合前身 check-prd-impl + check-impl；Step 3 调用 trellis-check） | 0.5+ skill 化为 `trellis-check-all`；old 仍为 command 并拆 3 个独立文件 |
| `check-prd` | PRD 准确性校验 + 覆盖度扫描（含 UI 文案逐字一致性） | 独立使用，校验 PRD 本身 |
| `create-prd` | 基于原始需求文档创建 PRD（含 UI 文案原封不动约束） | — |
| `analyze-task` | 任务深度分析与细化 | 0.5+ skill 化为 `trellis-analyze-task`（删除 command 版），old 仍为 command |
| `plan-version` | 版本开发计划（需求文档 → 任务拆分） | — |
| `re-implement` | 需求变更后二次实现 | — |
| `sync-prd` | 代码或需求变更后的 PRD 回补同步 | — |
| `push` | 一键 commit → push → 可选 merge 到目标分支 | merge_target 记录在 config.yaml |
| `draw-uml` | PM 视角用 UML 活动图梳理业务逻辑（先反问再画，每次自动渲染 PNG） | 产物落 `doc/uml/<slug>.{mmd,png}` |
| `create-command` | 创建新的 trellis 入口（command 或 skill 形态），同步 agents 副本与 skill-garden，法则化 frontmatter | 0.5+ skill 化为 `trellis-create-command`（替代原 0.4 的 command 版） |
| `migrate-skill` | 把已有 `/trellis:<X>` 命令迁移成 `.claude/skills/trellis-<X>/` skill，含对齐扫描 / 形态决策 / 融合判断 / 4 份副本同步 / README + 验证 / commit 模板 | 0.5+ 新增 skill，仅此 variant |

---

## 新增技能

### 新增通用技能

1. 在 `.common/.codex/skills/<name>/` 和/或 `.common/.claude/skills/<name>/` 下创建目录
2. 写 `SKILL.md`（格式取决于平台要求）
3. 不需要的平台可以只建一侧

### 新增 Trellis 技能

**Step 1. 选 variant**：新技能要加到哪个版本目录？
- 两个版本都适用 → `.trellis/old/` 和 `.trellis/0.5/` 都加
- 只适配新版 trellis → 只放 `.trellis/0.5/`
- 只兼容旧版 → 只放 `.trellis/old/`

**Step 2. 选形态**：command 还是 skill？
- **command** 适合高风险、需显式确认的动作（`push` / `re-implement` / `create-prd`）
- **skill** 适合可由自然语触发的查询/分析/检查类（`trellis-analyze-task` / `trellis-check-all`）
- **原则**：同一指令不要同时保留 command 和 skill 版（skill 化后删除 command 副本）

**Step 3. 落盘**：

每个新指令必定写入 `.agents/skills/<name>/SKILL.md`（给 trellis agent 系统用）：

```yaml
---
name: <name>
description: "<简要描述>"
---
# 命令标题

命令内容...
```

然后按形态二选一：

- **command 形态**：同时在 `.claude/commands/trellis/<name>.md` 写一份（去掉 frontmatter 的同内容文件）
- **skill 形态**：同时在 `.claude/skills/trellis-<name>/SKILL.md` 写一份（frontmatter 的 `name` 改为 `trellis-<name>`，`description` 需要精确到能让 Claude 按自然语触发；正文与 agents 版保持一致）

**Step 4. 内容一致性**：两份副本的正文内容必须完全相同，只允许 frontmatter 差异。
