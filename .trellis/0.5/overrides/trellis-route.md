<!-- BEGIN skill-garden enhancement v0.5 -->

## skill-garden Override: trellis-route routing

> Injected by skill-garden — **PRIORITY: HIGHEST**, wins on conflict with workflow.md upstream.
> Source: https://github.com/SilentFlower/skill-garden. Remove by deleting BEGIN..END markers.

**Scope**: every place workflow.md tells you to dispatch `trellis-implement` / `trellis-check`, or to load the `trellis-check` / `trellis-check-all` skill — that's Phase 2.1 (Implement), Phase 2.2 (Quality check), Phase 3.1 (Quality verification, pre-commit final), Skill Routing main table, and the DO-NOT-skip table.

### Override A — Always route through `trellis-route` first

Wherever the upstream tells you to dispatch / load the implement or check target, invoke the `trellis-route` skill **FIRST** with the appropriate `target` and follow whatever next-action it returns. Never call `Agent({subagent_type: 'trellis-implement'|'trellis-check'})` or load `trellis-check`/`trellis-check-all` directly — go through `trellis-route`.

`target=check` returns one of four modes: Check-all inline (recommended pre-commit, **default for Phase 3.1**) / Check-all subagent / Check inline / Check subagent. `target=implement` returns inline or subagent.

### Override B — `workflow-state:in_progress` refinements

The upstream `[workflow-state:in_progress]` body already states (1) default no-inline, (2) use exact agent type names, (3) per-turn escape hatch — keep those. Two refinements on top:

- **Flow** is `trellis-route(implement) → trellis-route(check) → trellis-update-spec → finish` (replaces upstream `trellis-implement → trellis-check → ...`).
- The per-turn escape hatch ("你直接改" / "do it inline" / etc.), when triggered, **also skips `trellis-route`** — go straight inline.

<!-- END skill-garden enhancement v0.5 -->
