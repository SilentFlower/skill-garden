<!-- BEGIN skill-garden enhancement v0.5 -->

## skill-garden Override: trellis-route routing

> Injected by skill-garden — **PRIORITY: HIGHEST**, wins on conflict with workflow.md upstream.
> Source: https://github.com/SilentFlower/skill-garden. Remove by deleting BEGIN..END markers.

**Scope**: every place workflow.md tells you to dispatch `trellis-implement` / `trellis-check`, or to load the `trellis-check` / `trellis-check-all` skill — that's Phase 2.1 (Implement), Phase 2.2 (Quality check), Phase 3.1 (Quality verification, pre-commit final), Skill Routing main table, and the DO-NOT-skip table.

### Override A — Always route through `trellis-route` first

Wherever the upstream tells you to dispatch / load the implement or check target, invoke the `trellis-route` skill **FIRST** with the appropriate `target` and follow whatever next-action it returns. Never call `Agent({subagent_type: 'trellis-implement'|'trellis-check'})` or load `trellis-check`/`trellis-check-all` directly — go through `trellis-route`.

`target=check` returns 4 modes (check-all/check × inline/subagent); `target=implement` returns inline or subagent. trellis-route's Step 1.7 makes a per-call context-based recommendation, then `AskUserQuestion` asks the user. Never pre-decide or skip the ask with fabricated reasons ("tool unavailable", "default inline") — SKILL.md has no fallback.

**进入 Phase 2.1 / 2.2 / 3.1 时的唯一动作**：直接 `Skill({skill: "trellis-route", args: "target=implement|check"})`。

调 skill **之前**禁止在主对话里：
- 写"开干吗 / 准备好了吗 / 我下一条再调"等预询问
- 陈述"我倾向 X" 或文字预览 inline/subagent 选项
- 提前展示 Step 1.7 推荐理由 / Step 2 选项

理由：Step 1.7 推荐由 skill 内部生成、通过 Step 2 `AskUserQuestion` 呈现——这是**唯一**询问点。前置加戏会造成双重询问、用户被迫用文字回答而非数字快捷键，破坏路径。

### Override B — `workflow-state:in_progress` refinements

The upstream `[workflow-state:in_progress]` body already states (1) default no-inline, (2) use exact agent type names, (3) per-turn escape hatch — keep those. One refinement on top:

- **Flow** is `trellis-route(implement) → trellis-route(check) → trellis-update-spec → finish` (replaces upstream `trellis-implement → trellis-check → ...`).

<!-- END skill-garden enhancement v0.5 -->
