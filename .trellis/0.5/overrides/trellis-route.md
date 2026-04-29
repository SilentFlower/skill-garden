<!-- BEGIN skill-garden enhancement v0.5 -->

## skill-garden Override: trellis-route routing

> Injected by skill-garden — **PRIORITY: HIGHEST**, wins on conflict with workflow.md upstream.
> Source: https://github.com/SilentFlower/skill-garden. Remove by deleting BEGIN..END markers.

**Scope**: every place workflow.md tells you to dispatch `trellis-implement` / `trellis-check`, or to load the `trellis-check` / `trellis-check-all` skill — that's Phase 2.1 (Implement), Phase 2.2 (Quality check), Phase 3.1 (Quality verification, pre-commit final), Skill Routing main table, and the DO-NOT-skip table.

### Override A — Always route through `trellis-route` first

Wherever the upstream tells you to dispatch / load the implement or check target, invoke the `trellis-route` skill **FIRST** with the appropriate `target` and follow whatever next-action it returns. Never call `Agent({subagent_type: 'trellis-implement'|'trellis-check'})` or load `trellis-check`/`trellis-check-all` directly — go through `trellis-route`.

`target=check` returns 4 modes (check-all/check × inline/subagent); `target=implement` returns inline or subagent. trellis-route's Step 1.7 makes a per-call context-based recommendation, then `AskUserQuestion` asks the user. Never pre-decide or skip the ask with fabricated reasons ("tool unavailable", "default inline") — SKILL.md has no fallback.

**The only action when entering Phase 2.1 / 2.2 / 3.1**: directly call `Skill({skill: "trellis-route", args: "target=implement|check"})`.

Before invoking the skill, **never** do any of these in the main conversation:
- write pre-questions like "ready to start? / shall I proceed? / I'll call it in my next message"
- state "I lean towards X" or text-preview inline/subagent options
- surface Step 1.7 recommendation rationale / Step 2 options ahead of time

Why: Step 1.7's recommendation is generated inside the skill and surfaced via Step 2's `AskUserQuestion` — the **only** prompt point. Pre-invoke chatter creates double-asking, forces users to reply in prose instead of using number shortcuts, and breaks the routing path.

### Override B — `workflow-state:in_progress` refinements

The upstream `[workflow-state:in_progress]` body already states (1) default no-inline, (2) use exact agent type names, (3) per-turn escape hatch — keep those. One refinement on top:

- **Flow** is `trellis-route(implement) → trellis-route(check) → trellis-update-spec → finish` (replaces upstream `trellis-implement → trellis-check → ...`).

<!-- END skill-garden enhancement v0.5 -->
