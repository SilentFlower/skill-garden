# Skill Garden

集中管理 AI Agent 技能,通过 URL bootstrap 安装到任意项目(mktemp 临时 clone,零持久缓存)。

```
skill-garden/
├── .common/                                  # 通用技能(按平台)
│   ├── .codex/skills/<name>/                 #   → <target>/.codex/skills/
│   └── .claude/skills/<name>/                #   → <target>/.claude/skills/
├── .trellis/                                 # Trellis 强化补充包(按版本)
│   ├── old/                                  #   < 0.5 (fallback)
│   ├── 0.5/                                  #   0.5.x:完整版 13 个 skill
│   └── 0.6/                                  #   ≥ 0.6:精简版 10 个 skill + workflow/skill override
└── scripts/install.sh                        # 一键安装(读目标 .trellis/.version 智能选 variant)
```

---

## 安装

`install.sh` clone 仓库到 mktemp、复制技能到目标项目、自动删 temp —— 零持久缓存。

```bash
# 远程一行装(默认 --scope=trellis)
bash <(curl -fsSL <raw-url>/install.sh) --repo git@github.com:<user>/skill-garden.git /target

# 配过环境变量后省 --repo
export SKILL_GARDEN_REPO=git@github.com:<user>/skill-garden.git
bash <(curl -fsSL <raw-url>/install.sh) /target

# 只装通用技能(.common)
bash install.sh --scope common --repo <url> /target

# 全装(trellis + common)
bash install.sh --scope all --repo <url> /target

# 只装指定技能(支持去 trellis- 前缀匹配)
bash install.sh --scope all --repo <url> /target craft-rpa trellis-push

# 本地开发(指向自己的 working clone,只取已 commit 状态)
bash install.sh --repo /path/to/skill-garden-checkout /target
```

**`--scope` 决定装哪类**:`trellis`(默认)/ `common` / `all`。`bash install.sh --help` 看完整。

**安装目标自动适配**:
- 目标有 `.codex/` → 装 `.common/.codex/`
- 目标有 `.claude/` → 装 `.common/.claude/`
- 目标有 `.trellis/` → 按 `.trellis/.version` 读 0.6 / 0.5 / old,装对应 variant 的 `.agents/` + `.claude/skills/`(+`commands/`,old 才有)+ 注入 `overrides/*`

**install.sh 自更新**:本地缓存的旧脚本启动时 `cmp` 自身与远程,不一致则 `exec` 远程版本继续。AI agent 从本地路径调用也不会踩到老逻辑。

---

## Trellis workflow override 注入

`--scope=trellis|all` 且目标项目是 trellis(≥ 0.5)时,`install.sh` 会幂等注入 workflow override 到 `.trellis/workflow.md`。

Trellis 0.6 使用 `overrides/workflow.md` 作为 `## Phase Index` 顶部的集中 hub,统一承载 routing gate、finish-work bookkeeping guard、push progress recovery / snapshot。`overrides/workflow-states/*.md` 分别维护 `[workflow-state:no_task]` / `planning` / `in_progress` / `in_progress-inline` 的短 sentinel,安装后每个状态只保留一个合并后的 skill-garden sentinel,不再分散追加多块 override。

0.6 的 finish-work guard 明确 `session_auto_commit` 只管 `task.py archive` / `add_session.py` 对自身 bookkeeping 文件(`.trellis/tasks/**` 归档、`.trellis/workspace/**` journal)的提交,对代码提交没有任何控制权:无论开关为 true 还是 false,代码提交都走 Phase 3.4、经用户确认后才提交,绝不因 `session_auto_commit: true` 而自动提交代码或跳过确认;`false` 时 archive / journal 仅落盘,不补做 `chore(task): archive ...` / `chore: record journal` 提交,只报告 `.trellis/tasks/**` / `.trellis/workspace/**` 脏文件供人工处理。

Trellis 0.5 / old 仍沿用各自原有的 `overrides/trellis-route.md` 注入方式。0.6 不再保留单独的 `overrides/trellis-route.md`,routing 规则统一归入 0.6 workflow hub。

特性:幂等(已有则替换)、最小侵入(不改上游正文)、备份首版 `workflow.md.bak`、Claude Code + Codex 双端通用。

```bash
# 只重灌 workflow override + workflow-state sentinel(不重装 SKILL)
bash install.sh --repo <url> /target workflow-enhancement

# 0.6 中只重灌 finish-work skill override,不刷新 workflow.md
bash install.sh --repo <url> /target finish-work-enhancement
```

回滚:删除 `<!-- BEGIN skill-garden overrides ... -->` hub 和各状态块里的 skill-garden sentinel,或 `cp .trellis/workflow.md.bak .trellis/workflow.md`。

## Trellis skill override 注入

Trellis 0.6 还支持 `overrides/skills/<skill>.md`:安装时把其中的 `BEGIN/END` 增量块注入到目标项目已有的 skill / command,不复制、不维护整份 Trellis 原生入口。

当前只有 `overrides/skills/trellis-finish-work.md`,用于在 `trellis-finish-work` 归档前加入英文 `Release Operations Inference Step`。它会注入已有的 `.agents/skills/trellis-finish-work/SKILL.md`、`.claude/skills/trellis-finish-work/SKILL.md` 和 `.claude/commands/trellis/finish-work.md`;目标不存在则跳过。

特性:幂等(已有同名块先替换)、最小侵入(只注入一段 override)、备份首版 `<target>.flower-skill-garden.bak`。`finish-work-enhancement` 只刷新这段 skill override。

回滚:删除目标文件里的 `<!-- BEGIN skill-garden skill override trellis-finish-work ... -->` 块,或从 `.flower-skill-garden.bak` 恢复。

---

## 当前技能

### 通用(`.common`,`--scope=common|all`)

| 技能 | 平台 | 说明 |
|------|------|------|
| `open-idea` | codex / claude | 跨平台唤起 IntelliJ IDEA 打开项目目录，支持 WSL 调 Windows IDEA |
| `sub2api-account-json-fix` | codex / claude | sub2api 账号 JSON 批量补全 + 推送 |
| `craft-rpa` | codex / claude | 浏览器交互录制 + AI 友好流程参考生成(RPA 改造素材),自带 Playwright recorder + run.sh + jsonl-to-trace |
| `craft-slides` | codex / claude | 基于 Slidev 端到端做演示:大纲 → slides.md → 预览 → 导出 PDF/PPTX/PNG,自带 slidev.sh + 语法速查 + 模板 |
| `humanize-writing` | codex / claude | 中文文本润色与去 AI 腔改写,压缩空话、套话和机械句式 |
| `torrent-analyze` | codex / claude | 自包含磁链验车工具，直接查询 whatslink API、解析 hash、缓存结果，并可选生成截图拼图、模糊和字体渲染 |

### Trellis 0.6+ (`--scope=trellis|all`,10 个核心 skill)

按 `.trellis/.version ≥ 0.6.0` 安装,全部 skill 化(skill 双副本:`.agents/` + `.claude/skills/trellis-<name>/`),自动注入集中式 workflow override hub 和 finish-work skill override:

| 技能 | 形态 | 何时用 |
|------|------|--------|
| `trellis-extract-prd` | Auto | 任务开发前、有正式需求文档,严格提取 PRD |
| `trellis-verify-task` | Auto | 三件套生成后,校验准确性 + 覆盖度 + 跨层一致性 |
| `trellis-check-all` | Auto | 开发完、提交前,全维度代码检查(三件套对照 + 假设验证 + trellis-check) |
| `trellis-run-full-chain` | Auto | PR 前 UAT 回归,跨层全链路(UI + API + DB) |
| `trellis-visualize` | Auto | 把架构、流程、业务规则和状态流转生成离线 HTML/SVG 图解,兼容旧 UML / 活动图诉求 |
| `trellis-route` | Auto | Phase 2.1/2.2 由 workflow override 自动触发,询问 inline / subagent |
| `trellis-push` | Manual | 一键 commit + push + 可选 merge,含 `last_push_snapshot` 任务进度快照 |
| `trellis-release` | Manual | 正式上线前核对任务文档、`release.md` 和 git 证据,生成版本 / 批次上线操作单 |
| `trellis-plan-version` | Manual | 新版本启动,需求 → 任务拆分 + 工时评估 + 人员分工 |
| `trellis-create-command` | Manual | 给项目加新 trellis 入口(command / skill),同步 agents + skill-garden 副本 |

Release operations inference 由 0.6 finish-work skill override 提供,不复制、不 fork、不维护
Trellis 原生 `trellis-finish-work` skill。用户显式运行 finish-work 前,agent 会根据任务文档、提交和
文件名信号智能判断是否需要记录上线事项;识别到 SQL、配置、批处理 / 部署脚本 / 数据修复、
外部系统 / 依赖平台上线等事项时,写入 `<task>/release.md`;明确无事项时不创建文件。
`trellis-release` 负责在正式上线前重新核对任务文档、已有 `release.md` 和 git 证据,
输出 `.trellis/releases/YYYY-MM-DD-<release-slug>.md`,不执行任何上线操作。

### Trellis 0.5 / old

按 `.trellis/.version` 自动适配,详细清单见 `.trellis/0.5/README.md` 或 `bash install.sh --help`。0.5 多 4 个 skill(`analyze-task` / `migrate-skill` / `re-implement` / `sync-prd`),old 是无 `trellis-` 前缀的 command 形态。

---

## 新增技能

### 通用(`.common`)

1. 在 `.common/.codex/skills/<name>/` 和/或 `.common/.claude/skills/<name>/` 下建目录
2. 写 `SKILL.md`(YAML frontmatter + 正文)
3. 不需要的平台可只建一侧

### Trellis(`.trellis/<variant>`)

**形态二选一**:
- **command**:高风险显式动作(`finish-work` / `continue`),`.claude/commands/trellis/<name>.md`(无 frontmatter,仅 old 用)
- **skill**:自然语触发(`trellis-analyze-task` / `trellis-check-all`),`.claude/skills/trellis-<name>/SKILL.md`(带 frontmatter,name = `trellis-<name>`)

**所有 trellis 技能必须**同时写一份 `.agents/skills/<name>/SKILL.md`(给 trellis agent 系统),正文与 `.claude/` 副本一致,仅 frontmatter 的 `name` / `description` 可按入口微调。

frontmatter 格式:

```yaml
---
name: <name>
description: "<简要描述,Auto-routing 需精确到自然语触发>"
---
# 命令标题
```

新建 trellis 入口推荐用 `/trellis-create-command` skill,会自动同步 4 份副本 + skill-garden 包。
