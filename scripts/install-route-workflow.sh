#!/usr/bin/env bash
# install-route-workflow.sh
#
# 把 trellis-route 路由步骤注入目标项目的 .trellis/workflow.md。
#
# 行为：
# - 6 处精确字符串 patch，对应 Skill Routing 主表 / DO NOT skip 表 /
#   Phase 2.1 三平台分支 / Phase 2.2 主分支 / workflow-state:in_progress
# - 幂等：开始检测 'trellis-route' 字眼，已存在则直接退出
# - 备份：原文件复制为 workflow.md.bak
# - 失败前不写入：任一锚点找不到 → 报错退出，不留半改文件
#
# 用法：
#   bash install-route-workflow.sh <target-project-dir>
#
# 前置条件：
#   - 目标项目已 trellis init（含 .trellis/workflow.md）
#   - 同时需要安装 trellis-route SKILL（用 install.sh 装）
#   - 推荐 trellis >= 0.5

set -euo pipefail

usage() {
  cat >&2 <<'EOF'
用法: install-route-workflow.sh <target-project-dir>

把 trellis-route 路由步骤注入目标项目 .trellis/workflow.md（6 处 patch）。
幂等：已含 trellis-route 则跳过。备份原文件为 workflow.md.bak。

也请确保 trellis-route SKILL 已通过 scripts/install.sh 装到目标项目。
EOF
}

if [ $# -ne 1 ] || [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
  usage
  exit 1
fi

TARGET="$1"

if [ ! -d "$TARGET" ]; then
  echo "❌ 目标目录不存在: $TARGET" >&2
  exit 1
fi

python3 - "$TARGET" <<'PYTHON_PATCH'
import sys
from pathlib import Path

target = Path(sys.argv[1])

# 版本检查：仅支持 trellis >= 0.5.0
import re
version_file = target / ".trellis" / ".version"
if not version_file.is_file():
    sys.exit(f"❌ {version_file} 不存在 — 目标可能不是 trellis 项目，或缺 .version 文件")
version = version_file.read_text(encoding="utf-8").strip()
m = re.match(r'^(\d+)\.(\d+)', version)
if not m:
    sys.exit(f"❌ 无法解析 .version: {version!r}")
major, minor = int(m.group(1)), int(m.group(2))
if (major, minor) < (0, 5):
    sys.exit(f"❌ trellis-route workflow patch 仅支持 trellis >= 0.5.0；目标版本: {version}")
print(f"✓ trellis 版本: {version}（>= 0.5.0 ✓）")

wf = target / ".trellis" / "workflow.md"

if not wf.is_file():
    sys.exit(f"❌ {wf} 不存在 — 目标可能不是 trellis 项目")

content = wf.read_text(encoding="utf-8")

if "trellis-route" in content:
    print(f"✓ {wf} 已含 'trellis-route' 字眼，跳过 patch（幂等）")
    sys.exit(0)

# ============================================================
# 6 段 patch：每段是 (描述, 原文, 新文) 三元组
# ============================================================

PATCH_1_OLD = "| About to write code / start implementing | Dispatch the `trellis-implement` sub-agent per Phase 2.1 |"
PATCH_1_NEW = "| About to write code / start implementing | Invoke `trellis-route` skill (target=implement) FIRST; follow its routing decision (inline or dispatch `trellis-implement` sub-agent) |"

PATCH_2_OLD = "| Finished writing / want to verify | Dispatch the `trellis-check` sub-agent per Phase 2.2 |"
PATCH_2_NEW = "| Finished writing / want to verify | Invoke `trellis-route` skill (target=check) FIRST; follow its routing decision (`trellis-check` / `trellis-check-all` / sub-agent) |"

PATCH_3_OLD = "| \"This is simple, I'll just code it in the main thread\" | Dispatching `trellis-implement` is the cheap path; skipping it tempts you to write code in the main thread and lose spec context — sub-agents get `implement.jsonl` injected, you don't |"
PATCH_3_NEW = "| \"This is simple, I'll just code it in the main thread\" | Following the `trellis-route` flow is the cheap path; skipping it loses user control over execution mode and (when subagent is chosen) loses `implement.jsonl` spec injection |"

PATCH_4_OLD = """[Claude Code, Cursor, OpenCode, Gemini, Qoder, CodeBuddy, Copilot, Droid]

Spawn the implement sub-agent:

- **Agent type**: `trellis-implement`
- **Task description**: Implement the requirements per prd.md, consulting materials under `{TASK_DIR}/research/`; finish by running project lint and type-check

The platform hook/plugin auto-handles:
- Reads `implement.jsonl` and injects the referenced spec files into the agent prompt
- Injects prd.md content

[/Claude Code, Cursor, OpenCode, Gemini, Qoder, CodeBuddy, Copilot, Droid]

[Codex]

Spawn the implement sub-agent:

- **Agent type**: `trellis-implement`
- **Task description**: Implement the requirements per prd.md, consulting materials under `{TASK_DIR}/research/`; finish by running project lint and type-check

The Codex sub-agent definition auto-handles the context load requirement:
- Reads `.trellis/.current-task`, `prd.md`, and `info.md` if present
- Reads `implement.jsonl` and requires the agent to load each referenced spec file before coding

[/Codex]

[Kiro]

Spawn the implement sub-agent:

- **Agent type**: `trellis-implement`
- **Task description**: Implement the requirements per prd.md, consulting materials under `{TASK_DIR}/research/`; finish by running project lint and type-check

The platform prelude auto-handles the context load requirement:
- Reads `implement.jsonl` and injects the referenced spec files into the agent prompt
- Injects prd.md content

[/Kiro]"""

PATCH_4_NEW = """[Claude Code, Cursor, OpenCode, Gemini, Qoder, CodeBuddy, Copilot, Droid]

**Step 1**: Invoke `trellis-route` skill with `target=implement`. The user will choose execution mode (inline vs subagent), and the skill will output the next-action instruction.

**Step 2**: Follow trellis-route's instruction exactly:

- If routing decision is **subagent** → Spawn the implement sub-agent:
  - **Agent type**: `trellis-implement`
  - **Task description**: Implement the requirements per prd.md, consulting materials under `{TASK_DIR}/research/`; finish by running project lint and type-check
  - The platform hook/plugin auto-handles: reads `implement.jsonl` and injects the referenced spec files into the agent prompt; injects prd.md content
- If routing decision is **inline** → Read `{TASK_DIR}/prd.md`, consult `{TASK_DIR}/research/`, load the `trellis-before-dev` skill for spec context, then implement directly in the main thread; finish by running project lint and type-check

[/Claude Code, Cursor, OpenCode, Gemini, Qoder, CodeBuddy, Copilot, Droid]

[Codex]

**Step 1**: Invoke `trellis-route` skill with `target=implement`. The user will choose execution mode (inline vs subagent), and the skill will output the next-action instruction.

**Step 2**: Follow trellis-route's instruction exactly:

- If routing decision is **subagent** → Spawn the implement sub-agent:
  - **Agent type**: `trellis-implement`
  - **Task description**: Implement the requirements per prd.md, consulting materials under `{TASK_DIR}/research/`; finish by running project lint and type-check
  - The Codex sub-agent definition auto-handles the context load requirement: reads `.trellis/.current-task`, `prd.md`, and `info.md` if present; reads `implement.jsonl` and requires the agent to load each referenced spec file before coding
- If routing decision is **inline** → Read `{TASK_DIR}/prd.md`, consult `{TASK_DIR}/research/`, load the `trellis-before-dev` skill for spec context, then implement directly in the main thread; finish by running project lint and type-check

[/Codex]

[Kiro]

**Step 1**: Invoke `trellis-route` skill with `target=implement`. The user will choose execution mode (inline vs subagent), and the skill will output the next-action instruction.

**Step 2**: Follow trellis-route's instruction exactly:

- If routing decision is **subagent** → Spawn the implement sub-agent:
  - **Agent type**: `trellis-implement`
  - **Task description**: Implement the requirements per prd.md, consulting materials under `{TASK_DIR}/research/`; finish by running project lint and type-check
  - The platform prelude auto-handles the context load requirement: reads `implement.jsonl` and injects the referenced spec files into the agent prompt; injects prd.md content
- If routing decision is **inline** → Read `{TASK_DIR}/prd.md`, consult `{TASK_DIR}/research/`, load the `trellis-before-dev` skill for spec context, then implement directly in the main thread; finish by running project lint and type-check

[/Kiro]"""

PATCH_5_OLD = """[Claude Code, Cursor, OpenCode, Codex, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid]

Spawn the check sub-agent:

- **Agent type**: `trellis-check`
- **Task description**: Review all code changes against spec and prd; fix any findings directly; ensure lint and type-check pass

The check agent's job:
- Review code changes against specs
- Auto-fix issues it finds
- Run lint and typecheck to verify

[/Claude Code, Cursor, OpenCode, Codex, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid]"""

PATCH_5_NEW = """[Claude Code, Cursor, OpenCode, Codex, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid]

**Step 1**: Invoke `trellis-route` skill with `target=check`. The user will choose between four modes: Check-all inline (recommended pre-commit) / Check-all subagent / Check inline / Check subagent.

**Step 2**: Follow trellis-route's instruction exactly:

- If routing decision is **inline check** → Load the `trellis-check` skill and execute in the main thread
- If routing decision is **inline check-all** → Load the `trellis-check-all` skill and execute in the main thread
- If routing decision is **subagent check** → Spawn the check sub-agent:
  - **Agent type**: `trellis-check`
  - **Task description**: Review all code changes against spec and prd; fix any findings directly; ensure lint and type-check pass
- If routing decision is **subagent check-all** → Prefer `trellis-check-all` subagent if exists; otherwise spawn `trellis-check` sub-agent and explicitly include `trellis-check-all` full workflow (PRD verify → 5-dim assertions → cross-layer → delegate to trellis-check) in the task description

The check agent's job:
- Review code changes against specs
- Auto-fix issues it finds
- Run lint and typecheck to verify

[/Claude Code, Cursor, OpenCode, Codex, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid]"""

PATCH_6_OLD = """[workflow-state:in_progress]
Flow: trellis-implement → trellis-check → trellis-update-spec → finish
Next required action: inspect conversation history + git status, then execute the next uncompleted step in that sequence.
For agent-capable platforms; dispatch `trellis-implement` for implementation and dispatch `trellis-check` before reporting completion.
[/workflow-state:in_progress]"""

PATCH_6_NEW = """[workflow-state:in_progress]
Flow: trellis-route(implement) → trellis-route(check) → trellis-update-spec → finish
Next required action: inspect conversation history + git status, then execute the next uncompleted step in that sequence.
For agent-capable platforms: BEFORE dispatching `trellis-implement` or `trellis-check` sub-agents, you MUST first invoke the `trellis-route` skill to ask the user about execution mode (inline vs subagent, and check vs check-all). Then follow the routing decision exactly. Do NOT directly call `Agent({subagent_type: 'trellis-implement'|'trellis-check'})` without going through `trellis-route` first.
[/workflow-state:in_progress]"""

PATCHES = [
    ("1. Skill Routing 主表 implement 行", PATCH_1_OLD, PATCH_1_NEW),
    ("2. Skill Routing 主表 check 行", PATCH_2_OLD, PATCH_2_NEW),
    ("3. DO NOT skip skills 表第一行", PATCH_3_OLD, PATCH_3_NEW),
    ("4. Phase 2.1 Implement 三平台分支", PATCH_4_OLD, PATCH_4_NEW),
    ("5. Phase 2.2 Quality check 主分支", PATCH_5_OLD, PATCH_5_NEW),
    ("6. workflow-state:in_progress 面包屑", PATCH_6_OLD, PATCH_6_NEW),
]

# ============================================================
# 第一遍：dry-run 验证所有锚点存在
# ============================================================
missing = []
for desc, old, _ in PATCHES:
    if old not in content:
        missing.append(desc)

if missing:
    print("❌ 以下锚点找不到（workflow.md 可能版本不匹配或已被改过）：", file=sys.stderr)
    for desc in missing:
        print(f"   - {desc}", file=sys.stderr)
    print("\n请先 sync 上游 workflow.md 到 trellis >= 0.5 干净状态，再跑本脚本。", file=sys.stderr)
    sys.exit(2)

# ============================================================
# 第二遍：备份 + 应用
# ============================================================
bak = wf.with_name(wf.name + ".bak")
bak.write_text(content, encoding="utf-8")
print(f"✓ 备份 → {bak}")

new_content = content
for desc, old, new in PATCHES:
    new_content = new_content.replace(old, new, 1)
    print(f"✓ {desc}")

wf.write_text(new_content, encoding="utf-8")

count = new_content.count("trellis-route")
print(f"\n✓ 完成：{wf} 现包含 {count} 处 'trellis-route'")
print(f"  回滚: cp {bak} {wf}")
print(f"\n提示：还需安装 trellis-route SKILL，运行：")
print(f"  bash <skill-garden>/scripts/install.sh {target} trellis-route")
PYTHON_PATCH
