---
name: trellis-route
description: |
  Route trellis-implement / trellis-check execution mode by asking the user to choose inline or subagent.
  For check, additionally choose between trellis-check (lightweight) and trellis-check-all (comprehensive,
  default pre-commit). Invoked from Phase 2.1 / 2.2 of the routing-aware workflow. Skip in non-trellis
  projects (no .trellis/). Not for other subagents (trellis-research / trellis-debug).
---

# Trellis 路由器：implement / check 执行模式选择

主 agent 进入 Phase 2.1 / 2.2 时调用本 skill，询问用户选择执行模式（inline / subagent / check-all）后输出执行指令。

---

## Step 1: 确认 target

调用方通常已经在上下文里给了 `target=implement` 或 `target=check`（来自 workflow.md Phase 2.1 / 2.2 step）。如果不确定，先短问用户。

## Step 2: 询问用户

调用 `AskUserQuestion`。

### target = implement

- **question**: "本次 implement 走 inline 还是 subagent？"
- **header**: "Impl 模式"
- **options**:
  1. label "Inline（推荐）", description "主 agent 直接执行，更快，共享上下文"
  2. label "Subagent", description "Dispatch 子 agent，隔离独立思考，较慢"

### target = check

- **question**: "本次 check 走哪种模式？"
- **header**: "Check 模式"
- **options**（check-all 默认推荐）:
  1. label "Check-all inline（推荐）", description "全面检查（PRD 对照 + 5 维 + spec），主 agent 执行"
  2. label "Check-all subagent", description "全面检查，dispatch 子 agent"
  3. label "Check inline", description "轻量检查（lint/type/spec），主 agent 执行"
  4. label "Check subagent", description "轻量检查，dispatch 子 agent"

## Step 2.5: 读 subagent_skip_compile（仅 implement + subagent 时）

```bash
if [ -f .trellis/config.yaml ]; then
  grep -E "^\s*subagent_skip_compile:\s*true\b" .trellis/config.yaml > /dev/null && echo true || echo false
fi
```

为 `true` 时，Step 3 的 implement subagent 指令会附加"跳过编译"prompt 段。其他路径不读此配置。

## Step 3: 输出执行指令

本 skill 不调用 Skill / Agent 工具，而是输出指令让主 agent 在下一轮执行。

### 路由表

| 用户选择 | 主 agent 应执行 |
|---------|----------------|
| **inline implement** | `Skill({skill: "trellis-before-dev"})` 加载 spec → 读 prd.md → 主线程实施 → 跑 lint/type-check |
| **subagent implement** | `Agent({subagent_type: "trellis-implement"})`；若 `subagent_skip_compile=true`，dispatch prompt 附加"跳过 mvn install / npm run build / tsc 等耗时编译类检查（已由主 agent 验证或最终统一执行）" |
| **inline check** | `Skill({skill: "trellis-check"})` |
| **inline check-all** | `Skill({skill: "trellis-check-all"})` |
| **subagent check** | `Agent({subagent_type: "trellis-check"})` |
| **subagent check-all** | 优先 `Agent({subagent_type: "trellis-check-all"})`；不存在时 fallback `Agent({subagent_type: "trellis-check"})` + dispatch prompt 含 trellis-check-all 全流程要求（PRD 对照 → 5 维断言 → 跨层 → 委托 trellis-check 收尾） |

### 输出模板

```markdown
路由决定：<inline/subagent> <implement | check | check-all>

接下来主 agent 应当：
- <路由表里对应的工具调用形式>
- [若 implement subagent 且 subagent_skip_compile=true：附加"跳过编译"prompt 段]

不要：
- <要避免的工具调用>
```

---

## 核心原则

1. **决策与执行分离**：本 skill 只输出指令，下一轮由主 agent 调工具
2. **严格执行用户选择**：路由结论一旦输出，主 agent 必须按指令执行，不可"出于谨慎"再换路径
3. **config 联动仅 implement subagent 路径**：`subagent_skip_compile` 仅在 target=implement + 选 subagent 时读取并注入 prompt

---

## 反模式

- ❌ 本 skill 内部直接调用 `Agent` / `Skill` 工具（违反"决策与执行分离"）
- ❌ check-all 选项被错误降级为普通 trellis-check（必须优先 trellis-check-all skill / subagent）
- ❌ 给 check 任何模式附加"跳过编译"指令（check 的核心职责就是跑编译/typecheck）
- ❌ 询问后忽视用户答案默认 subagent

---

## 边界

- **非 trellis 项目**（无 `.trellis/`）：输出"非 trellis 项目，跳过路由"，不阻断流程
- **config.yaml 缺失或字段缺失**：视为 false，不附加跳过编译指令
