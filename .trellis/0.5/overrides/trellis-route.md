<!-- BEGIN skill-garden enhancement v0.5 -->

## skill-garden Override: trellis-route routing

> Injected by skill-garden — **PRIORITY: HIGHEST**, wins on conflict with workflow.md upstream.
> Source: https://github.com/SilentFlower/skill-garden. Remove by deleting BEGIN..END markers.

**Scope**: every place workflow.md tells you to dispatch `trellis-implement` / `trellis-check`, or to load the `trellis-check` / `trellis-check-all` skill — that's Phase 2.1 (Implement), Phase 2.2 (Quality check), Phase 3.1 (Quality verification, pre-commit final), Skill Routing main table, and the DO-NOT-skip table.

### Override A — Always route through `trellis-route` first

Wherever the upstream tells you to dispatch / load the implement or check target, invoke the `trellis-route` skill **FIRST** with the appropriate `target` and follow whatever next-action it returns. Never call `Agent({subagent_type: 'trellis-implement'|'trellis-check'})` or load `trellis-check`/`trellis-check-all` directly — go through `trellis-route`.

**Trigger boundary** — "next action is implementation/check" fires (and you MUST invoke immediately, no deferral to next turn) at ANY of these moments:
- The last code / test / refactor action of an implement phase just completed and you are about to assess quality.
- The user asks an open-ended continuation question ("what's next?", "continue?", "shall I proceed?", "review first?", "keep going?", or any equivalent in any language) at any phase boundary.
- You catch yourself drafting a meta question to the user ("should I...?", "do you want me to...?", "X or Y?") — that's the signal to invoke trellis-route NOW instead.

`target=check` returns 4 modes (check-all/check × inline/subagent); `target=implement` returns inline or subagent. trellis-route's Step 1.7 makes a per-call context-based recommendation, then `AskUserQuestion` asks the user. Never pre-decide or skip the ask with fabricated reasons ("tool unavailable", "default inline") — SKILL.md has no fallback.

**The only action when entering Phase 2.1 / 2.2 / 3.1**: directly call `Skill({skill: "trellis-route", args: "target=implement|check"})`.

Before invoking the skill, **never** do any of these in the main conversation:
- write pre-questions like "ready to start? / shall I proceed? / I'll call it in my next message"
- state "I lean towards X" or text-preview inline/subagent options
- surface Step 1.7 recommendation rationale / Step 2 options ahead of time

Why: Step 1.7's recommendation is generated inside the skill and surfaced via Step 2's `AskUserQuestion` — the **only** prompt point. Pre-invoke chatter creates double-asking, forces users to reply in prose instead of using number shortcuts, and breaks the routing path.

### Override B — `workflow-state:in_progress` refinements

The upstream `[workflow-state:in_progress]` body already states (1) default no-inline, (2) use exact agent type names, (3) per-turn escape hatch — keep those. Two refinements on top:

- **Flow** is `trellis-route(implement) → trellis-route(check) → trellis-update-spec → finish` (replaces upstream `trellis-implement → trellis-check → ...`).
- **"per-turn" scope clarification**: the inline / sub-agent override applies ONLY to the single user message that contained the override phrase ("inline" / "do it inline" / "no sub-agent" / equivalent in any language). It does NOT auto-extend to subsequent turns just because "we're still inside the same implementation phase". On every new user turn at a phase boundary, re-evaluate via `trellis-route` — do not infer override intent from prior turns.

### Override C — Anti-defer rule

When `<workflow-state>` shows `Task: ... (in_progress)`, you are FORBIDDEN from any of these patterns at a phase boundary (implementation milestone reached / preparing to check / preparing to commit):

1. **Asking a meta continuation question instead of invoking trellis-route.**
   The check is mechanical: if your draft response would end with an open-ended "should I X or Y?" and the answer determines the next workflow phase, that response is invalid. Replace it with a direct `Skill({skill: "trellis-route", args: "target=..."})` call.

2. **Treating PRD-level PR1/PR2/PR3 multi-PR plans as Trellis phase boundaries.**
   PRs in the PRD are YOUR implementation strategy for code review readability. They are NOT `trellis-implement` → `trellis-check` boundaries. The `implement` phase ends only when the WHOLE task is structurally done (or at a deliberate user-requested pause). Don't trigger `trellis-route(check)` between sub-PRs unless the user explicitly asks for incremental checks.

3. **Inferring an inline override from a prior user turn.**
   "User said 'inline' two turns ago" is NOT a license to skip `trellis-route` on the current turn. Each turn at a phase boundary needs its own routing decision (which `trellis-route` will surface to the user via `AskUserQuestion`).

**Worked example of a real violation** (committed by an Opus session, 2026-05-08, before this rule existed):

> Context: just finished refactoring a 2k-line script (PR1 of a 3-PR plan listed in the PRD).
>
> ❌ What the model said:
> > "PR1 done, quality gates green, 18/18 tests pass. Want me to keep going inline with PR2, or pause for you to review first?"
>
> ✅ What the model should have said (and done):
> > Either:
> > (a) Continue PR2/PR3 inline silently (since the plan was a single implement phase and the user already said "inline" for it), or
> > (b) If pausing for any reason, invoke `Skill({skill: "trellis-route", args: "target=check"})` to surface the choice through the routing skill instead of free-form chat.
> >
> > In either case, NO meta question to the user.

If you find yourself about to violate any of the three patterns above, stop drafting and invoke `trellis-route` instead.

<!-- END skill-garden enhancement v0.5 -->
