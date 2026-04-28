<!-- BEGIN skill-garden enhancement v0.5 -->
> ⚠️ **Injected by skill-garden. PRIORITY: HIGHEST.**
> **Any conflict between this section and the rest of this workflow.md (trellis upstream body) is resolved in favor of this section. Areas not covered here remain as-is.**
> Maintainer: skill-garden (https://github.com/SilentFlower/skill-garden). To remove, delete everything between the BEGIN and END HTML-comment markers at the top and bottom of this block.

## skill-garden Override: trellis-route routing

**Scope**: every reference to `trellis-implement` / `trellis-check` in the rest of this workflow.md — Skill Routing main table, DO NOT skip skills table, Phase 2.1 (Implement) per-platform branches, Phase 2.2 (Quality check) main branch, and the `workflow-state:in_progress` breadcrumb.

### Override 1 — Skill Routing main table

The implement / check rows in the routing table (regardless of original wording such as "Dispatch the `trellis-implement` sub-agent per Phase 2.1") execute as follows:

| Trigger | What to actually do |
|---|---|
| About to write code / start implementing | Invoke `trellis-route` skill (`target=implement`) **FIRST**; follow its routing decision (inline or dispatch `trellis-implement` sub-agent). DO NOT dispatch directly. |
| Finished writing / want to verify | Invoke `trellis-route` skill (`target=check`) **FIRST**; follow its routing decision (`trellis-check` / `trellis-check-all` / sub-agent). DO NOT dispatch directly. |

### Override 2 — DO NOT skip skills

Counter to the thought "This is simple, I'll just code it in the main thread": following the `trellis-route` flow IS the cheap path. Skipping it loses user control over execution mode, and (when subagent is chosen) loses `implement.jsonl` spec injection.

### Override 3 — Phase 2.1 (Implement), all platforms

Regardless of how Phase 2.1 splits per platform (Claude Code / Cursor / OpenCode / Codex / Kiro / Gemini / Qoder / CodeBuddy / Copilot / Droid), execute these two steps:

**Step 1**: Invoke `trellis-route` skill with `target=implement`. The user picks execution mode (inline vs subagent); the skill returns the next-action instruction.

**Step 2**: Follow trellis-route's instruction exactly:

- **subagent** → Spawn the implement sub-agent:
  - **Agent type**: `trellis-implement`
  - **Task description**: Implement the requirements per `prd.md`, consulting materials under `{TASK_DIR}/research/`; finish by running project lint and type-check
  - Per-platform spec injection still happens as documented in the body (Claude Code etc. via hook/plugin reading `implement.jsonl`; Codex via sub-agent definition; Kiro via prelude).
- **inline** → Read `{TASK_DIR}/prd.md`, consult `{TASK_DIR}/research/`, load the `trellis-before-dev` skill for spec context, then implement directly in the main thread; finish by running project lint and type-check.

### Override 4 — Phase 2.2 (Quality check), all platforms

Regardless of whether Phase 2.2 calls for direct dispatch of `trellis-check`, execute these two steps:

**Step 1**: Invoke `trellis-route` skill with `target=check`. The user picks among four modes: Check-all inline (recommended pre-commit) / Check-all subagent / Check inline / Check subagent.

**Step 2**: Follow trellis-route's instruction exactly:

- **inline check** → Load the `trellis-check` skill and execute in the main thread.
- **inline check-all** → Load the `trellis-check-all` skill and execute in the main thread.
- **subagent check** → Spawn the check sub-agent:
  - **Agent type**: `trellis-check`
  - **Task description**: Review all code changes against spec and prd; fix any findings directly; ensure lint and type-check pass
- **subagent check-all** → Prefer `trellis-check-all` subagent if it exists; otherwise spawn `trellis-check` sub-agent and explicitly include the `trellis-check-all` full workflow (PRD verify → 5-dim assertions → cross-layer → delegate to trellis-check) in the task description.

The check agent's job remains: review code changes against specs, auto-fix issues it finds, run lint and type-check to verify.

### Override 5 — `workflow-state:in_progress` breadcrumb

Any `[workflow-state:in_progress]` block in the body is replaced at runtime with:

```
[workflow-state:in_progress]
Flow: trellis-route(implement) → trellis-route(check) → trellis-update-spec → finish
Next required action: inspect conversation history + git status, then execute the next uncompleted step in that sequence.
For agent-capable platforms: BEFORE dispatching `trellis-implement` or `trellis-check` sub-agents, you MUST first invoke the `trellis-route` skill to ask the user about execution mode (inline vs subagent, and check vs check-all). Then follow the routing decision exactly. Do NOT directly call `Agent({subagent_type: 'trellis-implement'|'trellis-check'})` without going through `trellis-route` first.
Default: do not edit code in the main session unless the user opts inline via `trellis-route` (or via the per-turn escape hatch below).
Use the exact Trellis agent type names when spawning sub-agents: `trellis-implement`, `trellis-check`, or `trellis-research`. Generic/default/generalPurpose sub-agents do not receive `implement.jsonl` / `check.jsonl` injection.
User override (per-turn escape hatch): if the user's CURRENT message explicitly tells the main session to handle it directly ("你直接改" / "别派 sub-agent" / "main session 写就行" / "do it inline" / "不用 sub-agent"), honor it for this turn — skip `trellis-route` and edit code directly. Per-turn only; do not carry forward; do NOT invent an override the user did not say.
[/workflow-state:in_progress]
```

<!-- END skill-garden enhancement v0.5 -->
