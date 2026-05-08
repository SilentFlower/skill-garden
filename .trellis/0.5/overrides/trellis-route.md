## skill-garden Override: trellis-route routing

<!-- BEGIN skill-garden enhancement v0.5 -->

> Long-form rules complementing the per-turn breadcrumb. Source: github.com/SilentFlower/skill-garden.

**Scope**: Phase 2.1 / 2.2 / 3.1 dispatch decisions, plus the Skill Routing + DO-NOT-skip tables. Per-turn breadcrumb covers the high-level rules; this file holds the specifics that don't fit there.

### Override A — No pre-invoke chatter

`trellis-route` returns 4 modes for `target=check` (check-all/check × inline/subagent) and 2 for `target=implement`. Step 1.7's recommendation is generated INSIDE the skill and surfaced via Step 2's `AskUserQuestion` — the **only** prompt point.

Before invoking the skill, **never**:
- write pre-questions ("ready to start? / shall I proceed?")
- state "I lean towards X" or text-preview the inline/subagent options
- surface Step 1.7 rationale ahead of time

Why: pre-invoke chatter creates double-asking, forces users to reply in prose instead of using the skill's number shortcuts (1/2/3/4), and breaks the routing path.

### Override B — Anti-defer rule (long-form details)

The per-turn ANTI-DEFER summarizes; here are the three forbidden patterns in full.

1. **Asking a meta continuation question instead of invoking trellis-route.** Mechanical check: if your draft response would end with an open-ended "should I X or Y?" and the answer determines the next workflow phase, replace it with `Skill({skill: "trellis-route", args: "target=..."})`.

2. **Treating PRD-level PR1/PR2/PR3 multi-PR plans as Trellis phase boundaries.** PRs in the PRD are an implementation strategy for code-review readability — they are NOT `trellis-implement` → `trellis-check` boundaries. The `implement` phase ends when the WHOLE task is structurally done (or at a deliberate user-requested pause).

3. **Inferring an inline override from a prior user turn.** "User said 'inline' two turns ago" is NOT a license to skip `trellis-route` on the current turn. Each turn at a phase boundary needs its own routing decision.

**Worked example of a real violation** (committed by an Opus session, 2026-05-08, before this rule existed):

> Context: just finished refactoring a 2k-line script (PR1 of a 3-PR plan listed in the PRD).
>
> ❌ What the model said:
> > "PR1 done, quality gates green, 18/18 tests pass. Want me to keep going inline with PR2, or pause for you to review first?"
>
> ✅ What the model should have said (and done):
> > Either:
> > (a) Continue PR2/PR3 inline silently (since the plan was a single implement phase and the user already said "inline" for it), or
> > (b) Invoke `Skill({skill: "trellis-route", args: "target=check"})` to surface the choice through the routing skill instead of free-form chat.
> >
> > In either case, NO meta question to the user.

<!-- END skill-garden enhancement v0.5 -->
