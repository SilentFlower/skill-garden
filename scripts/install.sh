#!/usr/bin/env bash
set -euo pipefail

# skill-garden 安装脚本
#
# 用法: bash install.sh --repo <git-url-or-local-path> /path/to/project [skill-name...]
#
# 脚本会把 --repo 指向的仓库 clone 到一次性 mktemp 目录，复制技能/override
# 到目标项目，然后 trap 自动删除 temp 目录——零持久缓存。
#
# 远程一行安装：
#   bash <(curl -fsSL <raw-url>/install.sh) --repo git@github.com:user/skill-garden.git /target
#
# 本地开发模式（指 --repo 到本地 working clone，clone 出来的是已 commit 状态）：
#   bash install.sh --repo /path/to/skill-garden-checkout /target
#
# 配 SKILL_GARDEN_REPO 环境变量可省略 --repo。

REPO_URL="${SKILL_GARDEN_REPO:-}"
TARGET_DIR=""
SKILL_NAMES=()

usage() {
  cat >&2 <<'EOF'
用法: install.sh [选项] <target-project-dir> [skill-name...]

把 skill-garden 仓库里的技能/override 临时 clone 后复制到目标项目，
完成即删 temp 目录，不留任何缓存。

操作:
  - 全部安装/更新: 不指定 skill-name
  - 指定技能名:    只安装/更新指定的技能（支持去 trellis- 前缀匹配）

选项:
  --repo <url>  git 仓库地址（必需，或设置 SKILL_GARDEN_REPO 环境变量）
                也可指向本地 working clone 路径，clone 时只取已 commit 状态
  --help        显示帮助

示例:
  # 远程一行装好（curl + bash）
  bash <(curl -fsSL <raw>/install.sh) --repo git@github.com:user/skill-garden.git /target

  # 配过 SKILL_GARDEN_REPO 后省 --repo
  export SKILL_GARDEN_REPO=git@github.com:user/skill-garden.git
  bash <(curl -fsSL <raw>/install.sh) /target

  # 本地开发：指向自己的 working clone（仅取已 commit 内容）
  bash install.sh --repo /path/to/skill-garden /target

  # 只安装指定技能
  bash install.sh --repo <url> /target verify-prd create-prd

  # 仅注入 workflow.md 强化块
  bash install.sh --repo <url> /target workflow-enhancement

环境变量:
  SKILL_GARDEN_REPO  git 仓库地址（等价 --repo，便于 .bashrc 配一次免敲）
EOF
}

ensure_dir() { mkdir -p "$1"; }

# 复制文件/目录，已有则覆盖
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
# 支持 trellis- 前缀去除匹配：指定 analyze-task 也会命中 trellis-analyze-task skill
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

TARGET_DIR="$(cd "$TARGET_DIR" && pwd -P)"

# ══════════════════════════════════
# 1) 临时 clone skill-garden 到 mktemp 目录
#    （不再支持仓内模式；统一走 URL/路径 bootstrap）
# ══════════════════════════════════
if [[ -z "$REPO_URL" ]]; then
  echo "❌ 缺 --repo 参数（或 SKILL_GARDEN_REPO 环境变量）" >&2
  echo "   bash install.sh --repo <git-url-or-path> $TARGET_DIR" >&2
  echo "   或者 export SKILL_GARDEN_REPO=<git-url> 后省略 --repo" >&2
  exit 2
fi

GARDEN="$(mktemp -d -t skill-garden.XXXXXX)"
# 任何路径退出（成功 / 失败 / Ctrl-C）都清理 temp 目录
trap 'rm -rf "$GARDEN"' EXIT
echo "临时 clone $REPO_URL"
echo "  → $GARDEN（装完自动删）"
git clone --depth 1 "$REPO_URL" "$GARDEN" >/dev/null 2>&1 || {
  echo "❌ git clone 失败：$REPO_URL" >&2
  exit 2
}

if [[ ! -f "$GARDEN/README.md" || ! -d "$GARDEN/.trellis" ]]; then
  echo "❌ clone 出来的目录不像 skill-garden（缺 README.md 或 .trellis/）：$REPO_URL" >&2
  exit 2
fi

echo "目标: $TARGET_DIR"
echo ""

# ══════════════════════════════════
# 2) 安装 .common（通用技能）
# ══════════════════════════════════
COMMON_CODEX="$GARDEN/.common/.codex/skills"
COMMON_CLAUDE="$GARDEN/.common/.claude/skills"

# 检测目标项目支持哪些平台
HAS_CODEX=false
HAS_CLAUDE=false
[[ -d "$TARGET_DIR/.codex" ]] && HAS_CODEX=true
[[ -d "$TARGET_DIR/.claude" ]] && HAS_CLAUDE=true

# 如果两个都没有，默认按 claude 处理（大多数项目）
if [[ "$HAS_CODEX" == false && "$HAS_CLAUDE" == false ]]; then
  HAS_CLAUDE=true
fi

if [[ "$HAS_CODEX" == true && -d "$COMMON_CODEX" ]]; then
  for skill_dir in "$COMMON_CODEX"/*/; do
    [[ ! -d "$skill_dir" ]] && continue
    name="$(basename "$skill_dir")"
    should_install "$name" || continue
    echo "[$name] codex → .codex/skills/$name/"
    install_one "$skill_dir" "$TARGET_DIR/.codex/skills/$name"
  done
elif [[ -d "$COMMON_CODEX" ]]; then
  echo "跳过 codex 技能（目标项目无 .codex/ 目录）"
fi

if [[ "$HAS_CLAUDE" == true && -d "$COMMON_CLAUDE" ]]; then
  for skill_dir in "$COMMON_CLAUDE"/*/; do
    [[ ! -d "$skill_dir" ]] && continue
    name="$(basename "$skill_dir")"
    should_install "$name" || continue
    echo "[$name] claude → .claude/skills/$name/"
    install_one "$skill_dir" "$TARGET_DIR/.claude/skills/$name"
  done
elif [[ -d "$COMMON_CLAUDE" ]]; then
  echo "跳过 claude 技能（目标项目无 .claude/ 目录）"
fi

# ══════════════════════════════════
# 3) 安装 .trellis（强化补充包）
# ══════════════════════════════════

# 检测目标项目是否为 trellis 项目
if [[ -d "$TARGET_DIR/.trellis" ]]; then
  IS_TRELLIS=true
else
  IS_TRELLIS=false
fi

# 根据目标项目 .trellis/.version 选择补充包版本目录
#   >= 0.5.0 → .trellis/0.5/（新版：agents 更名 trellis-*、check-all 合并三维）
#   其他情况（含缺失/无法解析/旧版）→ .trellis/old/
TRELLIS_VARIANT="old"
TRELLIS_VERSION=""
if [[ "$IS_TRELLIS" == true && -f "$TARGET_DIR/.trellis/.version" ]]; then
  TRELLIS_VERSION="$(tr -d '[:space:]' < "$TARGET_DIR/.trellis/.version")"
  V_MAJOR="$(echo "$TRELLIS_VERSION" | cut -d. -f1)"
  V_MINOR="$(echo "$TRELLIS_VERSION" | cut -d. -f2 | sed 's/[^0-9].*//')"
  if [[ "$V_MAJOR" =~ ^[0-9]+$ && "$V_MINOR" =~ ^[0-9]+$ ]]; then
    if (( V_MAJOR > 0 || V_MINOR >= 5 )); then
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
    echo "⚠ 目标项目不是 trellis 项目（未找到 .trellis/ 目录）"
    echo "  trellis 增强包需要 trellis 框架才能生效，跳过安装"
    echo ""
  elif [[ -d "$TRELLIS_AGENTS" || -d "$TRELLIS_CLAUDE" || -d "$TRELLIS_CLAUDE_SKILLS" ]]; then
    echo "跳过 trellis 增强包（目标项目非 trellis 项目）"
    echo ""
  fi
else
  # 确认目标目录与 trellis 项目结构匹配
  # .agents/skills/ → trellis 的 agent 技能目录
  # .claude/commands/trellis/ → trellis 的斜杠命令目录
  # .claude/skills/ → Claude harness 自动路由的 skill
  echo "trellis 项目版本: ${TRELLIS_VERSION:-未知}, 使用补充包: .trellis/$TRELLIS_VARIANT/"

  # 3a) .agents/skills/
  if [[ -d "$TRELLIS_AGENTS" ]]; then
    for skill_dir in "$TRELLIS_AGENTS"/*/; do
      [[ ! -d "$skill_dir" ]] && continue
      name="$(basename "$skill_dir")"
      should_install "$name" || continue
      echo "[$name] agents → .agents/skills/$name/"
      install_one "$skill_dir" "$TARGET_DIR/.agents/skills/$name"
    done
  fi

  # 3b) .claude/commands/trellis/
  if [[ -d "$TRELLIS_CLAUDE" ]]; then
    for cmd_file in "$TRELLIS_CLAUDE"/*.md; do
      [[ ! -f "$cmd_file" ]] && continue
      name="$(basename "$cmd_file" .md)"
      should_install "$name" || continue
      echo "[$name] commands → .claude/commands/trellis/$name.md"
      install_one "$cmd_file" "$TARGET_DIR/.claude/commands/trellis/$name.md"
    done
  fi

  # 3c) .claude/skills/ — Claude harness 自动路由的 skill
  if [[ -d "$TRELLIS_CLAUDE_SKILLS" ]]; then
    for skill_dir in "$TRELLIS_CLAUDE_SKILLS"/*/; do
      [[ ! -d "$skill_dir" ]] && continue
      name="$(basename "$skill_dir")"
      should_install "$name" || continue
      echo "[$name] skills → .claude/skills/$name/"
      install_one "$skill_dir" "$TARGET_DIR/.claude/skills/$name"
    done
  fi

  # 3d) workflow.md 顶部注入强化块（不改原文，幂等，备份 .bak）
  WF_ENHANCE="$GARDEN/.trellis/$TRELLIS_VARIANT/overrides/trellis-route.md"
  WF_DST="$TARGET_DIR/.trellis/workflow.md"
  if [[ -f "$WF_ENHANCE" && -f "$WF_DST" ]] && should_install "workflow-enhancement"; then
    echo "[workflow-enhancement] inject → .trellis/workflow.md (顶部 sentinel 块)"
    python3 - "$WF_ENHANCE" "$WF_DST" <<'PYEOF'
import sys, re, shutil
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
BEG = "<!-- BEGIN skill-garden enhancement"
# sentinel 必须在行首，且 BEGIN 与 END 各自单独成行；
# 这样即使 admonition 散文里出现了同名字面量也不会被误匹配
END_LINE_RE = re.compile(
    r"^<!-- BEGIN skill-garden enhancement[^\n]*-->\n.*?^<!-- END skill-garden enhancement[^\n]*-->\n*",
    re.DOTALL | re.MULTILINE,
)

block = src.read_text(encoding="utf-8").rstrip() + "\n\n"
text = dst.read_text(encoding="utf-8")

# 备份原文（仅当 .bak 不存在时创建，保留首次干净基线）
bak = Path(str(dst) + ".bak")
if not bak.exists():
    shutil.copy(dst, bak)
    backup_note = "（已创建 workflow.md.bak）"
else:
    backup_note = "（保留已有 workflow.md.bak）"

if BEG in text:
    new = END_LINE_RE.sub(block, text, count=1)
    action = "替换"
else:
    new = block + text
    action = "注入顶部"

if new == text:
    print(f"  ⚠ 内容未变化（可能 sentinel 异常），保留 .bak 留底")
else:
    dst.write_text(new, encoding="utf-8")
    print(f"  ✓ workflow.md 强化块已{action}{backup_note}")
PYEOF
  fi
fi

echo ""
echo "安装完成。"
