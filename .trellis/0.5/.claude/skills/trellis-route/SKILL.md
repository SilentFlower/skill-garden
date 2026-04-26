---
name: trellis-route
description: |
  Route trellis-implement / trellis-check execution between subagent and inline mode by asking the user.
  Use BEFORE any Agent({subagent_type:'trellis-implement'|'trellis-check'}) call, or when workflow-state
  says "dispatch trellis-implement" / "dispatch trellis-check". For check, additionally chooses between
  standard trellis-check (轻量) and trellis-check-all (全面，提交前默认). Skipping wastes cold-start time
  and removes user control. For non-trellis projects (no .trellis/), skip routing. For other subagents
  (trellis-research / trellis-debug), use them directly without routing.
---

# Trellis 路由器：implement / check 执行模式选择

主 agent 准备 dispatch `trellis-implement` 或 `trellis-check` 之前，先经本 skill 询问用户选择执行模式。

---

## 适用场景

满足以下任一情况，**必须优先调本 skill** 而非直接 dispatch：

- workflow-state hook 输出 "dispatch trellis-implement" 或 "dispatch trellis-check"
- 主 agent 即将调用 `Agent({subagent_type: 'trellis-implement'})` 或 `Agent({subagent_type: 'trellis-check'})`
- 用户明示要进入 implement 或 check 阶段

**不适用**：

- trellis-research / trellis-debug 等其他子 agent → 直接 dispatch，不走本 skill
- 非 trellis 项目（无 `.trellis/` 目录） → 输出跳过提示，不阻断流程

---

## 执行步骤

### Step 1: 推断 target

| 触发信号 | target |
|---------|--------|
| workflow-state 说 "dispatch trellis-implement" | `implement` |
| workflow-state 说 "dispatch trellis-check" | `check` |
| 用户明示某个阶段 | 按用户措辞 |
| 不确定 | 先短问用户 |

### Step 2: 询问用户

调用 `AskUserQuestion`。**根据 target 不同，选项不同**：

#### target = implement

- **question**: "本次 implement 走 inline 还是 subagent？"
- **header**: "Impl 模式"
- **options**（按推荐顺序）:
  1. label "Inline（推荐）", description "主 agent 直接执行，更快，共享上下文"
  2. label "Subagent", description "Dispatch 子 agent，隔离独立思考，较慢"

#### target = check

- **question**: "本次 check 走哪种模式？"
- **header**: "Check 模式"
- **options**（按推荐顺序，check-all 默认主推）:
  1. label "Check-all inline（推荐）", description "全面检查（PRD 对照 + 5 维 + spec），主 agent 执行"
  2. label "Check-all subagent", description "全面检查，dispatch 子 agent 隔离执行"
  3. label "Check inline", description "轻量检查（lint/type/spec），主 agent 直接执行"
  4. label "Check subagent", description "轻量检查，dispatch 子 agent"

### Step 2.5: 读取 subagent 行为配置（仅当 target=implement 且选 subagent 时）

仅在以下两个条件**同时满足**时执行：

- Step 1 推断的 `target == implement`
- Step 2 用户选择 "Subagent"

读取 `.trellis/config.yaml` 中的 `subagent_skip_compile` 平铺字段：

```bash
if [ -f .trellis/config.yaml ]; then
  SKIP_COMPILE=$(grep -E "^\s*subagent_skip_compile:\s*true\b" .trellis/config.yaml 2>/dev/null && echo true || echo false)
else
  SKIP_COMPILE="false"
fi
echo "subagent_skip_compile=$SKIP_COMPILE"
```

- `SKIP_COMPILE=true` → Step 3 implement / subagent 输出**附加"跳过编译"prompt 段**
- `SKIP_COMPILE=false` 或文件/字段不存在 → 不附加
- **inline 路径 / check 任何模式 / 其他 subagent**：均跳过本步，不读取此配置

### Step 3: 输出执行指令

**本 skill 不直接调用 Skill / Agent 工具**——只做路由决策，把后续指令交给主 agent 在下一轮执行。

按用户选择输出对应指令：

#### implement / inline

> 路由决定：**inline implement**
> 接下来主 agent 应当：参考 `.claude/agents/trellis-implement.md` 中的步骤说明，按当前任务的 `prd.md` / `info.md` 在主 agent 上下文里直接实施。
> **不要**调用 `Agent({subagent_type: "trellis-implement"})`。

#### implement / subagent

> 路由决定：**subagent implement**
> 接下来主 agent 应当：调用 `Agent({subagent_type: "trellis-implement"})` dispatch 子 agent。
>
> **附加 prompt（仅当 Step 2.5 得到 `subagent_skip_compile=true`）**：在 dispatch 的 prompt 参数中加入：
> > ⚠️ 跳过 mvn install / mvn compile / npm run build / tsc 等耗时编译类检查（已由主 agent 在 dispatch 前完成或将在最终验证时统一执行）。继续按 PRD 写代码即可。

#### check / check-all inline（默认推荐）

> 路由决定：**inline check-all**（全面检查）
> 接下来主 agent 应当：调用 `Skill({skill: "trellis-check-all"})` 加载步骤并在主 agent 上下文里执行。
> **不要**调用 `Agent({subagent_type: "trellis-check"})`，也不要走轻量 trellis-check。

#### check / check-all subagent

> 路由决定：**subagent check-all**（全面检查 + 子 agent）
> 接下来主 agent 应当：
> - **优先**：若 `trellis-check-all` 已存在为 subagent_type，调用 `Agent({subagent_type: "trellis-check-all"})`
> - **Fallback**（当前 .claude/agents/ 通常无 trellis-check-all）：调用 `Agent({subagent_type: "trellis-check"})`，并在 prompt 中明确指示子 agent **按 trellis-check-all 全部流程执行**：PRD 对照 → 5 维断言（API、组件上下文、数据流、测试、跨层）→ spec 合规 → 委托 trellis-check 收尾

#### check / check inline

> 路由决定：**inline check**（轻量）
> 接下来主 agent 应当：调用 `Skill({skill: "trellis-check"})` 加载步骤并在主 agent 上下文里执行。
> **不要**调用 `Agent({subagent_type: "trellis-check"})`。

#### check / check subagent

> 路由决定：**subagent check**（轻量）
> 接下来主 agent 应当：调用 `Agent({subagent_type: "trellis-check"})` dispatch 子 agent。

---

## 输出模板

主 agent 看到本 skill 结束后应能直接读到：

```markdown
路由决定：<inline implement | subagent implement | inline check | subagent check | inline check-all | subagent check-all>

接下来主 agent 应当：
- <具体指令，包含要调用的 Skill 或 Agent 形式>

不要：
- <要避免的工具调用>
```

---

## 核心原则

1. **决策与执行分离**：本 skill 只做选择并输出指令，下一轮由主 agent 调对应 Skill / Agent 工具，不在本 skill 内调用工具
2. **零侵入 trellis 框架**：不改 `.claude/agents/`、`.claude/skills/trellis-*`、`.trellis/scripts/` 任何已有文件
3. **严格遵守用户选择**：路由结论一旦输出，主 agent 必须按指令执行，不可"出于谨慎"再换路径
4. **target 推断要稳健**：根据 workflow-state 措辞或用户措辞清晰推断；含糊则反问，不擅自决定
5. **仅适用于 implement / check**：trellis-research / trellis-debug 等其他子 agent **不**走本 skill
6. **config 联动仅在 implement subagent 路径生效**：`subagent_skip_compile` 仅在 target=implement 且选 subagent 时读取并注入 prompt；inline、check 任何模式、其他子 agent 均不读取此配置

---

## 反模式

- ❌ 主 agent 看到 workflow-state "dispatch trellis-implement" 后跳过本 skill 直接 dispatch 子 agent
- ❌ 本 skill 内部直接调用 `Agent` 或 `Skill` 工具（违反"决策与执行分离"，应只输出指令）
- ❌ 错把本 skill 当 implement / check 本身用（不要在这里写 PRD 实施或质量检查逻辑）
- ❌ 用户选了 inline 后又下意识 dispatch 子 agent（路由结论必须严格执行）
- ❌ 对 trellis-research / trellis-debug 等其他子 agent 也走本 skill（仅 implement / check 适用）
- ❌ check-all 选项被错误降级为普通 trellis-check（必须优先 trellis-check-all，仅在 subagent 不存在时 fallback 到 trellis-check + prompt 引导）
- ❌ 询问后忽视用户答案默认 subagent 或默认 check-all
- ❌ inline 模式或 check 任何模式读取 `subagent_skip_compile`（该配置仅作用于 implement subagent 路径）
- ❌ 在 check subagent 路径附加"跳过编译"指令（check 的核心职责就是跑编译/typecheck，跳过会让 check 形同虚设）

---

## 边界情况

- **非 trellis 项目**（无 `.trellis/` 目录）：输出"非 trellis 项目，跳过路由"，不阻断流程。
- **用户选 Other（自定义文本）**：按字面理解最贴近的选项；含糊则反问。
- **同轮 implement → check 连发**：每个 target 各走一次本 skill。
- **trellis-check-all subagent 不存在**：按 Step 3 中"check-all subagent / Fallback"分支处理。
- **`config.yaml` 不存在或 `subagent_skip_compile` 缺失**：视为 false，implement subagent dispatch 时不附加跳过编译指令。
