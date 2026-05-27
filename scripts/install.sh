#!/usr/bin/env bash
set -euo pipefail

# skill-garden 安装脚本
#
# 用法:
#   bash install.sh [--scope trellis|common|all] [--repo <git-url-or-local-path>] /path/to/project [skill-name...]
#
# --scope 决定装哪类包(默认 trellis):
#   trellis   只装 .trellis/ 强化包(需要目标项目是 trellis 项目);默认值
#   common    只装 .common/ 通用技能(目标项目按是否有 .claude / .codex 自动适配)
#   all       两者都装
#
# 脚本会把 --repo 指向的仓库 clone 到一次性 mktemp 目录,复制技能/override
# 到目标项目,然后 trap 自动删除 temp 目录 —— 零持久缓存。
#
# 远程一行安装:
#   bash <(curl -fsSL <raw-url>/install.sh) --repo git@github.com:user/skill-garden.git /target
#
# 本地开发模式(指 --repo 到本地 working clone,clone 出来的是已 commit 状态):
#   bash install.sh --repo /path/to/skill-garden-checkout /target
#
# 配 SKILL_GARDEN_REPO 环境变量可省略 --repo。

REPO_URL="${SKILL_GARDEN_REPO:-}"
TARGET_DIR=""
SKILL_NAMES=()
SCOPE="trellis"   # 默认:向后兼容(trellis 是主线场景)

usage() {
  cat >&2 <<'EOF'
用法: install.sh [选项] <target-project-dir> [skill-name...]

把 skill-garden 仓库里的技能/override 临时 clone 后复制到目标项目,
完成即删 temp 目录,不留任何缓存。

操作:
  - 全部安装/更新: 不指定 skill-name
  - 指定技能名:    只安装/更新指定的技能(支持去 trellis- 前缀匹配)

选项:
  --scope <kind>  装哪类包,默认 trellis:
                    trellis  只装 .trellis 强化包(需目标项目是 trellis 项目)
                    common   只装 .common 通用技能(按目标项目有无 .claude/.codex 自动适配)
                    all      两者都装
  --repo <url>    git 仓库地址(必需,或设置 SKILL_GARDEN_REPO 环境变量)
                  也可指向本地 working clone 路径,clone 时只取已 commit 状态
  --help          显示帮助

示例:
  # 远程一行装好(默认装 trellis 包)
  bash <(curl -fsSL <raw>/install.sh) --repo git@github.com:user/skill-garden.git /target

  # 配过 SKILL_GARDEN_REPO 后省 --repo
  export SKILL_GARDEN_REPO=git@github.com:user/skill-garden.git
  bash <(curl -fsSL <raw>/install.sh) /target

  # 只装通用技能(.common)
  bash install.sh --scope common --repo <url> /target

  # 全装(trellis + common)
  bash install.sh --scope all --repo <url> /target

  # 本地开发:指向自己的 working clone
  bash install.sh --repo /path/to/skill-garden /target

  # 只安装指定技能(--scope 仍生效,限制候选范围)
  bash install.sh --scope all --repo <url> /target craft-rpa trellis-push

  # 仅注入 workflow.md 强化块(只在 --scope=trellis|all 时生效)
  bash install.sh --repo <url> /target workflow-enhancement

环境变量:
  SKILL_GARDEN_REPO  git 仓库地址(等价 --repo,便于 .bashrc 配一次免敲)
EOF
}

ensure_dir() { mkdir -p "$1"; }

# 复制文件/目录,已有则覆盖
install_one() {
  local src="$1" dst="$2"
  ensure_dir "$(dirname "$dst")"
  if [[ -L "$dst" ]]; then
    rm "$dst"
  fi
  if [[ -d "$src" ]]; then
    rm -rf "$dst" 2>/dev/null || true
    cp -r "$src" "$dst"
  else
    cp "$src" "$dst"
  fi
  echo "  ✓ $(basename "$dst")"
}

# 是否应该处理这个技能
# 支持 trellis- 前缀去除匹配:指定 analyze-task 也会命中 trellis-analyze-task skill
should_install() {
  local name="$1"
  [[ ${#SKILL_NAMES[@]} -eq 0 ]] && return 0
  local stripped="${name#trellis-}"
  for f in "${SKILL_NAMES[@]}"; do
    [[ "$f" == "$name" || "$f" == "$stripped" ]] && return 0
  done
  return 1
}

# ── 解析参数 ──
while [[ $# -gt 0 ]]; do
  case "$1" in
    --scope) SCOPE="$2"; shift 2 ;;
    --repo)  REPO_URL="$2"; shift 2 ;;
    --help)  usage; exit 0 ;;
    -*)      echo "未知选项: $1" >&2; usage; exit 2 ;;
    *)
      if [[ -z "$TARGET_DIR" ]]; then
        TARGET_DIR="$1"
      else
        SKILL_NAMES+=("$1")
      fi
      shift
      ;;
  esac
done

if [[ -z "$TARGET_DIR" ]]; then
  usage
  exit 2
fi

case "$SCOPE" in
  trellis|common|all) ;;
  *)
    echo "❌ --scope 必须是 trellis / common / all,当前: $SCOPE" >&2
    exit 2
    ;;
esac

# 派生两个开关,后面的安装段用这两个判
INSTALL_TRELLIS=false
INSTALL_COMMON=false
[[ "$SCOPE" == "trellis" || "$SCOPE" == "all" ]] && INSTALL_TRELLIS=true
[[ "$SCOPE" == "common"  || "$SCOPE" == "all" ]] && INSTALL_COMMON=true

TARGET_DIR="$(cd "$TARGET_DIR" && pwd -P)"

# ══════════════════════════════════
# 1) 临时 clone skill-garden 到 mktemp 目录
# ══════════════════════════════════
if [[ -z "$REPO_URL" ]]; then
  echo "❌ 缺 --repo 参数(或 SKILL_GARDEN_REPO 环境变量)" >&2
  echo "   bash install.sh --repo <git-url-or-path> $TARGET_DIR" >&2
  echo "   或者 export SKILL_GARDEN_REPO=<git-url> 后省略 --repo" >&2
  exit 2
fi

GARDEN="$(mktemp -d -t skill-garden.XXXXXX)"
trap 'rm -rf "$GARDEN"' EXIT
echo "临时 clone $REPO_URL"
echo "  → $GARDEN(装完自动删)"
git clone --depth 1 "$REPO_URL" "$GARDEN" >/dev/null 2>&1 || {
  echo "❌ git clone 失败:$REPO_URL" >&2
  exit 2
}

if [[ ! -f "$GARDEN/README.md" || ! -d "$GARDEN/.trellis" ]]; then
  echo "❌ clone 出来的目录不像 skill-garden(缺 README.md 或 .trellis/):$REPO_URL" >&2
  exit 2
fi

# ── install.sh 自更新检查(防止本地缓存的旧脚本运行老逻辑)──
#
# 为何要做:使用方可能从 /tmp/skill-garden 等本地缓存目录直接调 install.sh,
# 那里的脚本可能是几小时前的旧版(清理 regex / 注入位置已演进)。`--repo` 只
# 决定 override 数据源,不更新 install.sh 自身代码 —— 必须 exec 远程版本才能
# 用上最新逻辑。AI agent 尤其容易踩这个坑(看到 /tmp 已有就直接复用)。
#
# 跳过条件:curl bootstrap (`bash <(curl ...)`) 时 $0 是 /dev/fd/... 进程替换,
# 没有真实文件路径,本身就是远程最新版;本地脚本与远程一致时 cmp 返回 0 也跳过。
# 防循环:`SKILL_GARDEN_BOOTSTRAPPED` 环境变量在 re-exec 时设置一次,远程版本
# 进入时此变量已非空,自然不再 re-exec。
if [[ -z "${SKILL_GARDEN_BOOTSTRAPPED:-}" ]]; then
  SELF_PATH="$(readlink -f "$0" 2>/dev/null || echo "$0")"
  GARDEN_INSTALL="$GARDEN/scripts/install.sh"
  if [[ -f "$SELF_PATH" && -f "$GARDEN_INSTALL" ]] && ! cmp -s "$SELF_PATH" "$GARDEN_INSTALL"; then
    echo "⚠ 检测到本地 install.sh 与远程不一致,切换到远程最新版本继续 ..."
    export SKILL_GARDEN_BOOTSTRAPPED=1
    REEXEC_ARGS=("--scope" "$SCOPE" "--repo" "$REPO_URL" "$TARGET_DIR")
    [[ ${#SKILL_NAMES[@]} -gt 0 ]] && REEXEC_ARGS+=("${SKILL_NAMES[@]}")
    exec bash "$GARDEN_INSTALL" "${REEXEC_ARGS[@]}"
  fi
fi

echo "目标: $TARGET_DIR"
echo "scope: $SCOPE (trellis=$INSTALL_TRELLIS, common=$INSTALL_COMMON)"
echo ""

# ══════════════════════════════════
# 2) 安装 .common(通用技能) —— 仅当 INSTALL_COMMON=true
# ══════════════════════════════════
if [[ "$INSTALL_COMMON" == true ]]; then
  COMMON_CODEX="$GARDEN/.common/.codex/skills"
  COMMON_CLAUDE="$GARDEN/.common/.claude/skills"

  # 检测目标项目支持哪些平台
  HAS_CODEX=false
  HAS_CLAUDE=false
  [[ -d "$TARGET_DIR/.codex" ]] && HAS_CODEX=true
  [[ -d "$TARGET_DIR/.claude" ]] && HAS_CLAUDE=true

  # 如果两个都没有,默认按 claude 处理(大多数项目)
  if [[ "$HAS_CODEX" == false && "$HAS_CLAUDE" == false ]]; then
    HAS_CLAUDE=true
  fi

  if [[ "$HAS_CODEX" == true && -d "$COMMON_CODEX" ]]; then
    for skill_dir in "$COMMON_CODEX"/*/; do
      [[ ! -d "$skill_dir" ]] && continue
      name="$(basename "$skill_dir")"
      should_install "$name" || continue
      echo "[$name] common/codex → .codex/skills/$name/"
      install_one "$skill_dir" "$TARGET_DIR/.codex/skills/$name"
    done
  elif [[ -d "$COMMON_CODEX" ]]; then
    echo "跳过 common/codex 技能(目标项目无 .codex/ 目录)"
  fi

  if [[ "$HAS_CLAUDE" == true && -d "$COMMON_CLAUDE" ]]; then
    for skill_dir in "$COMMON_CLAUDE"/*/; do
      [[ ! -d "$skill_dir" ]] && continue
      name="$(basename "$skill_dir")"
      should_install "$name" || continue
      echo "[$name] common/claude → .claude/skills/$name/"
      install_one "$skill_dir" "$TARGET_DIR/.claude/skills/$name"
    done
  elif [[ -d "$COMMON_CLAUDE" ]]; then
    echo "跳过 common/claude 技能(目标项目无 .claude/ 目录)"
  fi
else
  echo "跳过 .common 安装 (--scope=$SCOPE)"
fi

# ══════════════════════════════════
# 3) 安装 .trellis(强化补充包) —— 仅当 INSTALL_TRELLIS=true
# ══════════════════════════════════
if [[ "$INSTALL_TRELLIS" == true ]]; then
  # 检测目标项目是否为 trellis 项目
  if [[ -d "$TARGET_DIR/.trellis" ]]; then
    IS_TRELLIS=true
  else
    IS_TRELLIS=false
  fi

  # 根据目标项目 .trellis/.version 选择补充包版本目录
  #   >= 0.6.0(含 0.6.0-beta.x、未来 1.x) → .trellis/0.6/(精简版:9 个核心 skill)
  #   = 0.5.x                              → .trellis/0.5/(完整版:13 个 skill)
  #   其他情况(含缺失/无法解析/< 0.5)        → .trellis/old/
  TRELLIS_VARIANT="old"
  TRELLIS_VERSION=""
  if [[ "$IS_TRELLIS" == true && -f "$TARGET_DIR/.trellis/.version" ]]; then
    TRELLIS_VERSION="$(tr -d '[:space:]' < "$TARGET_DIR/.trellis/.version")"
    V_MAJOR="$(echo "$TRELLIS_VERSION" | cut -d. -f1)"
    V_MINOR="$(echo "$TRELLIS_VERSION" | cut -d. -f2 | sed 's/[^0-9].*//')"
    if [[ "$V_MAJOR" =~ ^[0-9]+$ && "$V_MINOR" =~ ^[0-9]+$ ]]; then
      if (( V_MAJOR >= 1 || V_MINOR >= 6 )); then
        TRELLIS_VARIANT="0.6"
      elif (( V_MINOR >= 5 )); then
        TRELLIS_VARIANT="0.5"
      fi
    fi
  fi

  TRELLIS_AGENTS="$GARDEN/.trellis/$TRELLIS_VARIANT/.agents/skills"
  TRELLIS_CLAUDE="$GARDEN/.trellis/$TRELLIS_VARIANT/.claude/commands/trellis"
  TRELLIS_CLAUDE_SKILLS="$GARDEN/.trellis/$TRELLIS_VARIANT/.claude/skills"

  if [[ "$IS_TRELLIS" == false ]]; then
    # 检查用户是否明确指定了 trellis 技能名
    HAS_TRELLIS_REQUEST=false
    if [[ ${#SKILL_NAMES[@]} -gt 0 ]]; then
      for req_name in "${SKILL_NAMES[@]}"; do
        if [[ -d "$TRELLIS_AGENTS/$req_name" \
            || -f "$TRELLIS_CLAUDE/$req_name.md" \
            || -d "$TRELLIS_CLAUDE_SKILLS/$req_name" \
            || -d "$TRELLIS_CLAUDE_SKILLS/trellis-$req_name" ]]; then
          HAS_TRELLIS_REQUEST=true
          break
        fi
      done
    fi

    if [[ "$HAS_TRELLIS_REQUEST" == true ]]; then
      echo "⚠ 目标项目不是 trellis 项目(未找到 .trellis/ 目录)"
      echo "  trellis 增强包需要 trellis 框架才能生效,跳过安装"
      echo ""
    elif [[ -d "$TRELLIS_AGENTS" || -d "$TRELLIS_CLAUDE" || -d "$TRELLIS_CLAUDE_SKILLS" ]]; then
      echo "跳过 trellis 增强包(目标项目非 trellis 项目)"
      echo ""
    fi
  else
    # 确认目标目录与 trellis 项目结构匹配
    echo "trellis 项目版本: ${TRELLIS_VERSION:-未知}, 使用补充包: .trellis/$TRELLIS_VARIANT/"

    # 3a) .agents/skills/
    if [[ -d "$TRELLIS_AGENTS" ]]; then
      for skill_dir in "$TRELLIS_AGENTS"/*/; do
        [[ ! -d "$skill_dir" ]] && continue
        name="$(basename "$skill_dir")"
        should_install "$name" || continue
        echo "[$name] trellis/agents → .agents/skills/$name/"
        install_one "$skill_dir" "$TARGET_DIR/.agents/skills/$name"
      done
    fi

    # 3b) .claude/commands/trellis/
    if [[ -d "$TRELLIS_CLAUDE" ]]; then
      for cmd_file in "$TRELLIS_CLAUDE"/*.md; do
        [[ ! -f "$cmd_file" ]] && continue
        name="$(basename "$cmd_file" .md)"
        should_install "$name" || continue
        echo "[$name] trellis/commands → .claude/commands/trellis/$name.md"
        install_one "$cmd_file" "$TARGET_DIR/.claude/commands/trellis/$name.md"
      done
    fi

    # 3c) .claude/skills/ — Claude harness 自动路由的 skill
    if [[ -d "$TRELLIS_CLAUDE_SKILLS" ]]; then
      for skill_dir in "$TRELLIS_CLAUDE_SKILLS"/*/; do
        [[ ! -d "$skill_dir" ]] && continue
        name="$(basename "$skill_dir")"
        should_install "$name" || continue
        echo "[$name] trellis/skills → .claude/skills/$name/"
        install_one "$skill_dir" "$TARGET_DIR/.claude/skills/$name"
      done
    fi

    # 3d) workflow.md 注入 Phase Index 尾部的 skill-garden 章节(幂等,备份 .bak)
    WF_ENHANCE="$GARDEN/.trellis/$TRELLIS_VARIANT/overrides/trellis-route.md"
    WF_DST="$TARGET_DIR/.trellis/workflow.md"
    if [[ -f "$WF_ENHANCE" && -f "$WF_DST" ]] && should_install "workflow-enhancement"; then
      echo "[workflow-enhancement] inject → .trellis/workflow.md (Phase Index 尾部 skill-garden 章节 + workflow-state guard)"
      python3 - "$WF_ENHANCE" "$WF_DST" <<'PYEOF'
import sys, re, shutil
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
# sentinel / heading 必须各自独占一行;散文内字面量不会被误匹配
SKILL_GARDEN_SECTION_RE = re.compile(
    r"^#{2,3} skill-garden Override: trellis-route routing[^\n]*\n+"
    r"^<!-- BEGIN skill-garden enhancement[^\n]*-->\n.*?"
    r"^<!-- END skill-garden enhancement[^\n]*-->\n*",
    re.DOTALL | re.MULTILINE,
)
SENTINEL_RE = re.compile(
    r"^<!-- BEGIN skill-garden enhancement[^\n]*-->\n.*?^<!-- END skill-garden enhancement[^\n]*-->\n*",
    re.DOTALL | re.MULTILINE,
)
STATE_SENTINEL_RE = re.compile(
    r"^<!-- BEGIN skill-garden workflow-state trellis-route[^\n]*-->\n.*?^<!-- END skill-garden workflow-state trellis-route[^\n]*-->\n*",
    re.DOTALL | re.MULTILINE,
)
NO_TASK_SENTINEL_RE = re.compile(
    r"^<!-- BEGIN skill-garden workflow-state no-task-gate[^\n]*-->\n.*?^<!-- END skill-garden workflow-state no-task-gate[^\n]*-->\n*",
    re.DOTALL | re.MULTILINE,
)
PLANNING_SENTINEL_RE = re.compile(
    r"^<!-- BEGIN skill-garden workflow-state planning-handoff[^\n]*-->\n.*?^<!-- END skill-garden workflow-state planning-handoff[^\n]*-->\n*",
    re.DOTALL | re.MULTILINE,
)
PUSH_PROGRESS_RECOVERY_SENTINEL_RE = re.compile(
    r"^<!-- BEGIN skill-garden workflow-state push-progress-recovery[^\n]*-->\n.*?^<!-- END skill-garden workflow-state push-progress-recovery[^\n]*-->\n*",
    re.DOTALL | re.MULTILINE,
)
IN_PROGRESS_SNAPSHOT_SENTINEL_RE = re.compile(
    r"^<!-- BEGIN skill-garden workflow-state in-progress-push-snapshot[^\n]*-->\n.*?^<!-- END skill-garden workflow-state in-progress-push-snapshot[^\n]*-->\n*",
    re.DOTALL | re.MULTILINE,
)
PHASE1_RE = re.compile(r"(?m)^## Phase 1: Plan[^\n]*$")
PHASE_INDEX_RE = re.compile(r"^(## Phase Index[^\n]*\n)", re.MULTILINE)
NO_TASK_BLOCK_RE = re.compile(
    r"(?ms)^(\[workflow-state:no_task\]\n)(.*?)(^\[/workflow-state:no_task\])"
)
PLANNING_BLOCK_RE = re.compile(
    r"(?ms)^(\[workflow-state:planning\]\n)(.*?)(^\[/workflow-state:planning\])"
)
IN_PROGRESS_BLOCK_RE = re.compile(
    r"(?ms)^(\[workflow-state:in_progress\]\n)(.*?)(^\[/workflow-state:in_progress\])"
)
IN_PROGRESS_INLINE_BLOCK_RE = re.compile(
    r"(?ms)^(\[workflow-state:in_progress-inline\]\n)(.*?)(^\[/workflow-state:in_progress-inline\])"
)

block = src.read_text(encoding="utf-8").rstrip() + "\n\n"
no_task_block = """<!-- BEGIN skill-garden workflow-state no-task-gate v0.5 -->
FINAL NO-TASK GUARD (skill-garden):
Creating/resuming a task ≠ permission to implement inline.
After PRD ready and task started, next impl action = `trellis-route(implement)`.
Don't infer opt-out from "small/urgent/unclear" — opt-out requires an explicit phrase in the current message (see C below).
<!-- END skill-garden workflow-state no-task-gate v0.5 -->

"""
planning_block = """<!-- BEGIN skill-garden workflow-state planning-handoff v0.5 -->
FINAL PLANNING GUARD (skill-garden):
Planning is not implementation permission.
Complete prd.md + context first.
After in_progress, next action = `trellis-route(implement)`, not direct edits.
<!-- END skill-garden workflow-state planning-handoff v0.5 -->

"""
push_progress_block = """<!-- BEGIN skill-garden workflow-state push-progress-recovery v0.6 -->
PUSH PROGRESS RECOVERY (skill-garden):
If you haven't already relayed recovery in this session, scan
`.trellis/tasks/*/task.json` for entries where status="in_progress" AND a
`last_push_snapshot` field is present (schema: snapshot_at / branch /
pushed_commits / completed_steps / partial_step / next_step / notes).
For each match, surface to the user:
  「发现未完成任务 <title>:上次 push 完成到 <completed_steps>,下一步 <next_step>。要继续吗?」
If multiple match, list them with `snapshot_at` so the user can pick.
Then suggest `python3 ./.trellis/scripts/task.py start <task_path>` to
re-bind the active-task pointer before resuming work.
Skip this hint if (a) you've already relayed recovery this session, or
(b) no in_progress task carries `last_push_snapshot`.
<!-- END skill-garden workflow-state push-progress-recovery v0.6 -->

"""
in_progress_block = """
<!-- BEGIN skill-garden workflow-state trellis-route v0.5 -->
FINAL ROUTE GUARD (skill-garden):
This guard is intentionally appended after upstream in_progress breadcrumbs and overrides earlier direct-dispatch defaults in this same <workflow-state>.
At Phase 2.1/2.2/3.1, invoke `trellis-route(implement|check)` first.
Do NOT spawn `trellis-implement` / `trellis-check` directly from the main session unless `trellis-route` just selected a subagent mode.
If `trellis-route` selected inline mode, load `trellis-before-dev` / `trellis-check` / `trellis-check-all` as applicable and execute in the main session.
ANTI-DEFER: at phase boundaries, never ask meta questions ("X or Y?", "continue?", "what's next?") — invoke `trellis-route(check)` instead.
<!-- END skill-garden workflow-state trellis-route v0.5 -->

"""
push_snapshot_block = """<!-- BEGIN skill-garden workflow-state in-progress-push-snapshot v0.6 -->
IN-PROGRESS PUSH SNAPSHOT (skill-garden):
The active task's task.json may carry a `last_push_snapshot` field (schema:
snapshot_at / branch / pushed_commits / completed_steps / partial_step /
next_step / notes). Before starting new work this turn, read that field; if
present, briefly relay `partial_step` + `next_step` so the user knows you
recognize the paused state instead of restarting from scratch. Skip if you
have already relayed this snapshot earlier in the session, or if the field
is absent.
<!-- END skill-garden workflow-state in-progress-push-snapshot v0.6 -->

"""
text = dst.read_text(encoding="utf-8")

bak = Path(str(dst) + ".bak")
if not bak.exists():
    shutil.copy(dst, bak)
    backup_note = "(已创建 workflow.md.bak)"
else:
    backup_note = "(保留已有 workflow.md.bak)"

clean = SKILL_GARDEN_SECTION_RE.sub("", text)
clean = SENTINEL_RE.sub("", clean)
clean = STATE_SENTINEL_RE.sub("", clean)
clean = NO_TASK_SENTINEL_RE.sub("", clean)
clean = PLANNING_SENTINEL_RE.sub("", clean)
clean = PUSH_PROGRESS_RECOVERY_SENTINEL_RE.sub("", clean)
clean = IN_PROGRESS_SNAPSHOT_SENTINEL_RE.sub("", clean)

m1 = PHASE1_RE.search(clean)
if m1:
    idx = m1.start()
    phase_new = clean[:idx].rstrip() + "\n\n" + block + "\n" + clean[idx:]
    action = "插入到 ## Phase Index 末尾(## Phase 1: Plan 前)"
else:
    m = PHASE_INDEX_RE.search(clean)
    if m:
        idx = m.end()
        phase_new = clean[:idx] + "\n" + block + clean[idx:]
        action = "插入到 ## Phase Index 之后 (fallback: 未找到 ## Phase 3: Finish)"
    else:
        phase_new = block + clean
        action = "注入顶部 (fallback: 未找到 Phase 3 / Phase Index 锚点)"

state_actions = []
nm = NO_TASK_BLOCK_RE.search(phase_new)
if nm:
    phase_new = NO_TASK_BLOCK_RE.sub(
        lambda m: m.group(1) + m.group(2).rstrip() + "\n" + no_task_block + push_progress_block + m.group(3),
        phase_new,
        count=1,
    )
    state_actions.append("[workflow-state:no_task]")
else:
    state_actions.append("未找到 [workflow-state:no_task]")

pm = PLANNING_BLOCK_RE.search(phase_new)
if pm:
    phase_new = PLANNING_BLOCK_RE.sub(
        lambda m: m.group(1) + m.group(2).rstrip() + "\n" + planning_block + m.group(3),
        phase_new,
        count=1,
    )
    state_actions.append("[workflow-state:planning]")
else:
    state_actions.append("未找到 [workflow-state:planning]")

sm = IN_PROGRESS_BLOCK_RE.search(phase_new)
if sm:
    new = IN_PROGRESS_BLOCK_RE.sub(
        lambda m: m.group(1) + m.group(2).rstrip() + in_progress_block + push_snapshot_block + m.group(3),
        phase_new,
        count=1,
    )
    state_actions.append("[workflow-state:in_progress]")
else:
    new = phase_new
    state_actions.append("未找到 [workflow-state:in_progress]")

sim = IN_PROGRESS_INLINE_BLOCK_RE.search(new)
if sim:
    new = IN_PROGRESS_INLINE_BLOCK_RE.sub(
        lambda m: m.group(1) + m.group(2).rstrip() + "\n\n" + push_snapshot_block + m.group(3),
        new,
        count=1,
    )
    state_actions.append("[workflow-state:in_progress-inline]")
else:
    state_actions.append("未找到 [workflow-state:in_progress-inline]")
new = new.rstrip() + "\n"
state_action = ",并已更新 " + " / ".join(state_actions)

if new == text:
    print(f"  ✓ workflow.md 强化块已是最新,无需改动{backup_note}")
else:
    dst.write_text(new, encoding="utf-8")
    print(f"  ✓ workflow.md 强化块已{action}{state_action}{backup_note}")
PYEOF
    fi
  fi
else
  echo "跳过 .trellis 安装 (--scope=$SCOPE)"
fi

echo ""
echo "安装完成。"
