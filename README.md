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
│   └── 0.6/                                  #   ≥ 0.6:精简版 10 个 skill + Patch 目录
└── scripts/
    ├── install.sh                            # 一键安装(读目标 .trellis/.version 智能选 variant)
    └── apply-trellis-patches.py              # 0.6 Patch 声明执行器
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

## Trellis Patch

`--scope=trellis|all` 且目标项目是 Trellis 0.6 时，`install.sh` 会在复制强化资产前统一执行 Patch Engine：

- `overrides/patches/<target>/<name>/patch.json`：按目标组织单个 `insert / replace / remove` 声明，selector、baseline 和 content 与声明放在同一叶子目录。
- `overrides/bundles/*.json`：只定义安装别名与 Patch 组合，不承载修改逻辑。
- required Patch 先全量预检；任一目标漂移时，在 common/Trellis 资产复制前失败且零写入。
- 成功后写入 managed marker、备份首次原文到 `.trellis/.backup-flower/<目标相对路径>`，并记录可追溯 provenance。
- 旧 transform marker、workflow sentinel 和 skill additive override 由 Patch 自身迁移；0.6 不再维护第二套注入协议。

Workflow hub、五个 workflow state、Update-Spec、Finish-Work、共享 hook，以及 Codex/Claude 平台配置都走同一执行链。Markdown、Python、JSON、YAML 和 TOML 的结构差异由受控 selector adapter 处理，而不是由安装器分支直接改文件。

0.6 的 finish-work guard 明确 `session_auto_commit` 只管 `task.py archive` / `add_session.py` 对自身 bookkeeping 文件(`.trellis/tasks/**` 归档、`.trellis/workspace/**` journal)的提交,对代码提交没有任何控制权:无论开关为 true 还是 false,代码提交都走 Phase 3.4、经用户确认后才提交,绝不因 `session_auto_commit: true` 而自动提交代码或跳过确认;`false` 时 archive / journal 仅落盘,不补做 `chore(task): archive ...` / `chore: record journal` 提交,只报告 `.trellis/tasks/**` / `.trellis/workspace/**` 脏文件供人工处理。

Trellis 0.5 / old 仍沿用各自原有的 `overrides/trellis-route.md` 注入方式。0.6 不再保留单独的 `overrides/trellis-route.md`，routing 规则统一归入 0.6 workflow hub Patch。

特性：required 全量预检、非目标原文保持、managed marker 幂等、首次备份集中到 `.trellis/.backup-flower/`、Claude Code + Codex 双端通用。独立安装器使用 `scripts/apply-trellis-patches.py`，协议与 flower-trellis 的 JS consumer 保持一致。

```bash
# 只重灌 workflow 与 intent routing Patch Bundle（不重装 SKILL）
bash install.sh --repo <url> /target workflow-enhancement

# 上一命令的 intent routing 别名
bash install.sh --repo <url> /target task-intent
bash install.sh --repo <url> /target intent-routing

# 0.6 中只重灌 Finish-Work Patch Bundle，不刷新 workflow.md
bash install.sh --repo <url> /target finish-work-enhancement

# 0.6 中只重灌 Update-Spec Patch Bundle，不刷新 workflow.md
bash install.sh --repo <url> /target update-spec-enhancement
```

回滚：从 `.trellis/.backup-flower/<目标相对路径>` 恢复首次原文。不要只删 Patch marker，因为 `remove` marker 也是防止旧原文回流的幂等 tombstone。

### Compiled Targets

`compiled-targets/<trellis-version>/full/` 保存 Skill-Garden 全部 Bundle/Patch 应用到 Claude + Codex canonical Trellis 项目后的确定性审阅结果：

- `plan.json`：catalog hash、qualified operation 顺序、目标 hash、missing/optional 与 conflict 结果。
- `targets/`：按原相对路径保存 `.trellis`、`.agents`、`.claude`、`.codex` 下实际进入计划的最终文件。
- changed target 在最终文件旁保存 `<target>.diff` sidecar，使用三行上下文 unified diff；未变化 target 不生成 sidecar。

生成器会在写盘前拒绝最终文件与 sidecar 的同名或文件/目录前缀冲突，避免真实 `.diff` target 被审阅文件覆盖。

`full` 表示选择全部 Skill-Garden Bundle/Patch，不表示初始化全部 Trellis 平台。其它平台组合由 Flower 集成矩阵临时验证，不在仓库中保存重复 files/diffs。

生成器直接复用独立 Python Patch consumer：

```bash
python3 scripts/generate-compiled-targets.py --trellis-bin /path/to/trellis
python3 scripts/generate-compiled-targets.py --check --trellis-bin /path/to/trellis
```

传入 JavaScript `trellis` bin 时，生成器会使用 PATH 中的 `node`；也可通过 `--node-bin` 显式指定。生成产物不是安装输入或恢复源，修改 Patch 后必须刷新并通过 check。

---

## 当前技能

### 通用(`.common`,`--scope=common|all`)

| 技能 | 平台 | 说明 |
|------|------|------|
| `open-idea` | codex / claude | 跨平台唤起 IntelliJ IDEA 打开项目目录，支持 WSL 调 Windows IDEA |
| `aliyun-sls-query` | codex / claude | 使用 AK/SK 直连阿里云 SLS 查询日志与指标，包含零依赖签名脚本与排障经验 |
| `craft-rpa` | codex / claude | 浏览器交互录制 + AI 友好流程参考生成(RPA 改造素材),自带 Playwright recorder + run.sh + jsonl-to-trace |
| `craft-slides` | codex / claude | 基于 Slidev 端到端做演示:大纲 → slides.md → 预览 → 导出 PDF/PPTX/PNG,自带 slidev.sh + 语法速查 + 模板 |
| `humanize-writing` | codex / claude | 中文文本润色与去 AI 腔改写,压缩空话、套话和机械句式 |
| `torrent-analyze` | codex / claude | 自包含磁链验车工具，直接查询 whatslink API、解析 hash、缓存结果，并可选生成截图拼图、模糊和字体渲染 |

### Trellis 0.6+ (`--scope=trellis|all`,10 个核心 skill)

按 `.trellis/.version ≥ 0.6.0` 安装,全部 skill 化(skill 双副本:`.agents/` + `.claude/skills/trellis-<name>/`),并通过 Bundle 自动应用 workflow hub、Finish-Work 和 Update-Spec Patch:

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

Release operations inference 由 0.6 Finish-Work Patch 提供,不复制、不 fork、不维护
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
