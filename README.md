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
│   └── 0.6/                                  #   ≥ 0.6:精简版 9 个 skill + workflow override
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
- 目标有 `.trellis/` → 按 `.trellis/.version` 读 0.6 / 0.5 / old,装对应 variant 的 `.agents/` + `.claude/skills/`(+`commands/`,old 才有)+ 注入 `overrides/*` 到 `workflow.md`

**install.sh 自更新**:本地缓存的旧脚本启动时 `cmp` 自身与远程,不一致则 `exec` 远程版本继续。AI agent 从本地路径调用也不会踩到老逻辑。

---

## trellis-route override 注入

`--scope=trellis|all` 且目标项目是 trellis(≥ 0.5)时,`install.sh` 默认把 `overrides/trellis-route.md` 作为独立 `## skill-garden Override` 章节注入 `.trellis/workflow.md`(Phase 3 后,fallback 到 Phase Index 后),并在 `[workflow-state:no_task]` / `planning` / `in_progress]` 末尾追加 `FINAL ... GUARD` sentinel。

特性:幂等(已有则替换)、最小侵入(不改上游正文)、备份首版 `workflow.md.bak`、Claude Code + Codex 双端通用。

```bash
# 只重灌 override + workflow-state guard(不重装 SKILL)
bash install.sh --repo <url> /target workflow-enhancement
```

回滚:删 sentinel 块整段,或 `cp .trellis/workflow.md.bak .trellis/workflow.md`。

---

## 当前技能

### 通用(`.common`,`--scope=common|all`)

| 技能 | 平台 | 说明 |
|------|------|------|
| `sub2api-account-json-fix` | codex / claude | sub2api 账号 JSON 批量补全 + 推送 |
| `craft-rpa` | codex / claude | 浏览器交互录制 + AI 友好流程参考生成(RPA 改造素材),自带 Playwright recorder + run.sh + jsonl-to-trace |

### Trellis 0.6+ (`--scope=trellis|all`,9 个核心 skill)

按 `.trellis/.version ≥ 0.6.0` 安装,全部 skill 化(skill 双副本:`.agents/` + `.claude/skills/trellis-<name>/`),自动注入 `trellis-route` override 到 workflow:

| 技能 | 形态 | 何时用 |
|------|------|--------|
| `trellis-extract-prd` | Auto | 任务开发前、有正式需求文档,严格提取 PRD |
| `trellis-verify-task` | Auto | 三件套生成后,校验准确性 + 覆盖度 + 跨层一致性 |
| `trellis-check-all` | Auto | 开发完、提交前,全维度代码检查(三件套对照 + 假设验证 + trellis-check) |
| `trellis-run-full-chain` | Auto | PR 前 UAT 回归,跨层全链路(UI + API + DB) |
| `trellis-draw-uml` | Auto | 需要可视化业务流程,自动渲染 PNG 并展示 |
| `trellis-route` | Auto | Phase 2.1/2.2 由 workflow override 自动触发,询问 inline / subagent |
| `trellis-push` | Manual | 一键 commit + push + 可选 merge,含 `last_push_snapshot` 任务进度快照 |
| `trellis-plan-version` | Manual | 新版本启动,需求 → 任务拆分 + 工时评估 + 人员分工 |
| `trellis-create-command` | Manual | 给项目加新 trellis 入口(command / skill),同步 agents + skill-garden 副本 |

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
