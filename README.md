# Skill Garden

集中管理个人 AI Agent 技能，支持安装到任意项目。

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

### 四种安装目标

| 源路径（variant 内） | 目标路径 | 用途 |
|------|------|------|
| `.agents/skills/<name>/SKILL.md` | `<target>/.agents/skills/<name>/` | 被 trellis 的 agent 系统读取 |
| `.claude/commands/trellis/<name>.md` | `<target>/.claude/commands/trellis/<name>.md` | Claude Code 斜杠命令 `/trellis:<name>`（适合显式动作，如 finish-work / continue） |
| `.claude/skills/trellis-<name>/SKILL.md` | `<target>/.claude/skills/trellis-<name>/` | Claude harness 按 description 自动路由（适合自然语触发，如 analyze-task） |
| `overrides/<override>.md` | 注入到 `<target>/.trellis/workflow.md` 顶部 sentinel 块 | 强化覆盖 trellis 上游 workflow.md 的指定段落（PRIORITY: HIGHEST，正文不动） |

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
name: verify-prd
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
| 目标有 `.trellis/` | 读 `.trellis/.version` 选 `old/` 或 `0.5/`，安装对应目录的 `.agents/skills/` + `.claude/commands/trellis/`（仅 old）+ `.claude/skills/`（仅 0.5）+ 把 `overrides/*.md` 注入到目标 `.trellis/workflow.md` 顶部 sentinel 块 |
| 两个都没有 | 默认按 claude 处理 |

### 本地安装

```bash
# 安装全部（自动检测平台）
bash skill-garden/scripts/install.sh /path/to/project

# 只安装指定技能
bash skill-garden/scripts/install.sh /path/to/project verify-prd create-prd

# 更新（再次运行即覆盖）
bash skill-garden/scripts/install.sh /path/to/project
```

> **说明**：install.sh 必须从 skill-garden 仓库内运行（脚本会拿同仓库的 `.common/` 与 `.trellis/` 复制到目标）。要拿上游最新版，先 `cd skill-garden && git pull`，再跑 install.sh。

### 启用 trellis-route 路由 workflow（默认随 install.sh 自动注入）

> **要求**：目标项目 trellis `>= 0.5.0`（install.sh 读 `.trellis/.version` 选 `0.5/` 变体）。

`install.sh` 安装到 trellis 项目时，默认会从 `.trellis/0.5/overrides/trellis-route.md` 取模板，把整段 override 块注入到目标 `.trellis/workflow.md` **顶部**（用 `<!-- BEGIN/END skill-garden enhancement -->` sentinel 包裹）。块声明 `PRIORITY: HIGHEST`，让 phase 系统在 dispatch `trellis-implement` / `trellis-check` 子 agent 之前先经 `trellis-route` 询问用户。

```bash
# 一键装：包括 trellis-route SKILL（.agents/.claude 双份）+ workflow.md 顶部注入
bash skill-garden/scripts/install.sh /path/to/project

# 只重灌强化块（不重装 SKILL）：
bash skill-garden/scripts/install.sh /path/to/project workflow-enhancement
```

特性：

- **正文不动**：trellis 上游 `workflow.md` body 一字不改，未来 sync 上游版本零冲突
- **幂等**：sentinel 块存在则替换为最新内容，不存在则顶部插入；重复运行 install.sh 安全
- **首次基线**：`workflow.md.bak` 仅在不存在时创建，保留首版干净基线
- 主 agent 进入 Phase 2.1 / 2.2 时，按 override 块要求先调 `trellis-route` 让用户选 inline / subagent / check-all
- `[workflow-state:in_progress]` 面包屑改写为禁止跳过 trellis-route 直接 dispatch
- Claude Code + Codex 双端通用（不依赖 PreToolUse hook 拦截子 agent）

可选：项目 `.trellis/config.yaml` 加 `subagent_skip_compile: true`，trellis-route 会在 implement subagent 模式下自动注入"跳过 mvn install / npm run build / tsc"prompt（仅 implement subagent 路径生效）。

回滚：删 sentinel 块整段 / `cp .trellis/workflow.md.bak .trellis/workflow.md`。

---

## 当前技能

### 通用（.common）

| 技能 | 平台 | 说明 |
|------|------|------|
| `sub2api-account-json-fix` | codex, claude | sub2api 账号推送 |

### Trellis 补充包（.trellis）

#### 0.5+ 推荐技能

在 `.trellis/.version >= 0.5.0` 时安装的 skill 集合（全部已 skill 化，删除了 command 版）：

| 技能 | 形态 | 说明 | 使用时机 |
|------|------|------|---------|
| `trellis-push` | skill (Manual-only) | 一键 commit → push → 可选 merge 到目标分支；含 Step 1.5 智能 PRD 同步提醒 | 代码写完要提交时 |
| `trellis-check-all` | skill (Auto-routing) | 全维度代码检查（PRD 实现对照 + 假设验证 + trellis-check 三维） | 开发完成后、提交前 |
| `trellis-verify-prd` | skill (Auto-routing) | PRD 准确性校验 + 覆盖度扫描（含 UI 文案逐字一致性） | PRD 生成后、开发前 |
| `trellis-analyze-task` | skill (Auto-routing) | 任务深度分析与细化 | 开发前，理解任务全貌 |
| `trellis-draw-uml` | skill (Auto-routing) | PM / 业务架构师视角用 UML 活动图梳理业务（每次自动渲染 PNG 并读图展示） | 需要可视化理解业务流程时 |
| `trellis-sync-prd` | skill (Auto-routing) | 代码或需求变更后的 PRD 回补同步 | 实现与 PRD 出现偏差时 |
| `trellis-run-full-chain` | skill (Auto-routing) | 跨层全链路验证（Playwright UI + curl API + MySQL MCP），以"场景-路径-期望"表逐条执行；强调跨层，不是前端 e2e 套件 | 代码完成后、PR 前的 UAT 回归 |
| `trellis-re-implement` | skill (Manual-only) | 需求变更后二次实现 | 需求变更需要重新实现时 |

#### 0.5+ 全部技能

| 技能 | 形态 | 说明 |
|------|------|------|
| `trellis-analyze-task` | skill (Auto-routing) | 任务深度分析与细化 |
| `trellis-check-all` | skill (Auto-routing) | 全维度代码检查（内嵌融合前身 `check-prd-impl` + `check-impl`；Step 3 调用 trellis-check agent） |
| `trellis-create-command` | skill (Manual-only) | 创建新的 trellis 入口（command 或 skill 形态），同步 agents 副本与 skill-garden，统一 frontmatter |
| `trellis-create-prd` | skill (Manual-only) | 基于原始需求文档创建 PRD（含 UI 文案原封不动约束）+ `task.json` |
| `trellis-draw-uml` | skill (Auto-routing) | PM 视角用 UML 活动图梳理业务逻辑（先反问再画，每次自动渲染 PNG）；产物落 `doc/uml/<slug>.{mmd,png}` |
| `trellis-migrate-skill` | skill (Manual-only) | 把已有 `/trellis:<X>` 命令迁移成 `.claude/skills/trellis-<X>/` skill，含对齐扫描 / 形态决策 / 融合判断 / 4 份副本同步 / README + 验证 / commit 模板 |
| `trellis-plan-version` | skill (Manual-only) | 版本开发计划（需求文档 → 任务拆分 + 工时评估 + 人员分工） |
| `trellis-push` | skill (Manual-only) | 一键 commit → push → 可选 merge 到目标分支；含 Step 1.5 智能 PRD 同步提醒；`merge_target` 记录在 `config.yaml` |
| `trellis-re-implement` | skill (Manual-only) | 需求变更后二次实现（调 trellis-implement + trellis-check agent） |
| `trellis-route` | skill (Auto-routing) | impl/check 子 agent vs inline 路由（含 check-all 4 选项），先询问用户再 dispatch；可选联动 `.trellis/config.yaml` 的 `subagent_skip_compile` 跳过编译 |
| `trellis-run-full-chain` | skill (Auto-routing) | 跨层全链路验证（Playwright UI + curl API + MySQL MCP），以"场景-路径-期望"表逐条执行，附数据恢复；强调跨层，不是前端 e2e 套件 |
| `trellis-sync-prd` | skill (Auto-routing) | 代码或需求变更后的 PRD 回补同步 |
| `trellis-verify-prd` | skill (Auto-routing) | PRD 准确性校验 + 覆盖度扫描（含 UI 文案逐字一致性） |

---

#### old 推荐命令

在 `.trellis/.version < 0.5.0` 时安装的 command 集合（全部为 command 形态，无 `trellis-` 前缀）：

| 命令 | 说明 | 使用时机 |
|------|------|---------|
| `push` | 一键 commit → push → 可选 merge 到目标分支 | 代码写完要提交时 |
| `check-all` | 全维度一键检查（依次调用 `check-prd-impl` → `check-impl` → trellis-check agent 三维） | 开发完成后、提交前 |
| `check-prd` | PRD 准确性校验 + 覆盖度扫描 | PRD 生成后、开发前 |
| `analyze-task` | 任务深度分析与细化 | 开发前，理解任务全貌 |
| `draw-uml` | PM / 业务架构师视角用 UML 活动图梳理业务 | 需要可视化理解业务流程时 |
| `sync-prd` | 代码或需求变更后的 PRD 回补同步 | 实现与 PRD 出现偏差时 |
| `re-implement` | 需求变更后二次实现 | 需求变更需要重新实现时 |

#### old 全部命令

| 命令 | 说明 |
|------|------|
| `analyze-task` | 任务深度分析与细化 |
| `check-all` | 全维度一键检查，依次拆 3 个独立调用：`check-prd-impl` → `check-impl` → trellis-check agent |
| `check-impl` | 代码 vs 实际行为的偏差检查 |
| `check-prd` | PRD 准确性校验 + 覆盖度扫描（含 UI 文案逐字一致性） |
| `check-prd-impl` | 代码 vs PRD 的偏差检查 |
| `create-prd` | 基于原始需求文档创建 PRD |
| `draw-uml` | PM 视角用 UML 活动图梳理业务逻辑；产物落 `doc/uml/<slug>.{mmd,png}` |
| `plan-version` | 版本开发计划（需求文档 → 任务拆分） |
| `push` | 一键 commit → push → 可选 merge 到目标分支；`merge_target` 记录在 `config.yaml` |
| `re-implement` | 需求变更后二次实现 |
| `sync-prd` | 代码或需求变更后的 PRD 回补同步 |
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
- **command** 适合高风险、需显式确认的动作（`finish-work` / `continue`）
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
