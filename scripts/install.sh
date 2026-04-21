#!/usr/bin/env bash
set -euo pipefail

# skill-garden 安装脚本
# 远程: bash <(curl -fsSL <raw-url>/install.sh) --repo <git-url> /path/to/project
# 本地: bash skill-garden/scripts/install.sh /path/to/project

REPO_URL="${SKILL_GARDEN_REPO:-}"
CACHE_DIR="${SKILL_GARDEN_DIR:-$HOME/.skill-garden}"
TARGET_DIR=""
SKILL_NAMES=()

usage() {
  cat >&2 <<'EOF'
用法: install.sh [选项] <target-project-dir> [skill-name...]

安装/更新 skill-garden 技能到目标项目。

操作:
  - 首次安装: clone 仓库 → 复制技能文件到目标项目
  - 更新: pull 最新 → 覆盖目标项目中的技能文件
  - 指定技能名: 只安装/更新指定的技能

选项:
  --repo <url>     git 仓库地址（首次安装必须，或设置 SKILL_GARDEN_REPO）
  --dir <path>     本地缓存目录（默认: ~/.skill-garden）
  --help           显示帮助

示例:
  # 首次安装全部
  bash install.sh --repo git@github.com:user/skill-garden.git /path/to/project

  # 更新全部（已 clone 过）
  bash install.sh /path/to/project

  # 只安装指定技能
  bash install.sh /path/to/project check-prd create-prd

环境变量:
  SKILL_GARDEN_REPO  git 仓库地址
  SKILL_GARDEN_DIR   本地缓存目录（默认 ~/.skill-garden）
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
should_install() {
  local name="$1"
  [[ ${#SKILL_NAMES[@]} -eq 0 ]] && return 0
  for f in "${SKILL_NAMES[@]}"; do
    [[ "$f" == "$name" ]] && return 0
  done
  return 1
}

# ── 解析参数 ──
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)  REPO_URL="$2"; shift 2 ;;
    --dir)   CACHE_DIR="$2"; shift 2 ;;
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
# 1) 获取 skill-garden
# ══════════════════════════════════

# 如果脚本就在 skill-garden 仓库内运行，直接用
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SCRIPT_GARDEN="$(cd "$SCRIPT_DIR/.." && pwd -P)"

if [[ -f "$SCRIPT_GARDEN/README.md" && -d "$SCRIPT_GARDEN/.trellis" ]]; then
  GARDEN="$SCRIPT_GARDEN"
  echo "使用本地 skill-garden: $GARDEN"
else
  # 远程模式: clone 或 pull
  GARDEN="$CACHE_DIR"
  if [[ -d "$GARDEN/.git" ]]; then
    echo "更新: $GARDEN"
    git -C "$GARDEN" pull --ff-only 2>/dev/null || echo "  pull 失败，使用缓存继续"
  elif [[ -n "$REPO_URL" ]]; then
    echo "克隆: $REPO_URL"
    git clone "$REPO_URL" "$GARDEN"
  else
    echo "错误: 未找到 skill-garden，请指定 --repo <git-url>" >&2
    exit 2
  fi
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

if [[ "$IS_TRELLIS" == false ]]; then
  # 检查用户是否明确指定了 trellis 技能名
  HAS_TRELLIS_REQUEST=false
  if [[ ${#SKILL_NAMES[@]} -gt 0 ]]; then
    for req_name in "${SKILL_NAMES[@]}"; do
      if [[ -d "$TRELLIS_AGENTS/$req_name" || -f "$TRELLIS_CLAUDE/$req_name.md" ]]; then
        HAS_TRELLIS_REQUEST=true
        break
      fi
    done
  fi

  if [[ "$HAS_TRELLIS_REQUEST" == true ]]; then
    echo "⚠ 目标项目不是 trellis 项目（未找到 .trellis/ 目录）"
    echo "  trellis 增强包需要 trellis 框架才能生效，跳过安装"
    echo ""
  elif [[ -d "$TRELLIS_AGENTS" || -d "$TRELLIS_CLAUDE" ]]; then
    echo "跳过 trellis 增强包（目标项目非 trellis 项目）"
    echo ""
  fi
else
  # 确认目标目录与 trellis 项目结构匹配
  # .agents/skills/ → trellis 的 agent 技能目录
  # .claude/commands/trellis/ → trellis 的斜杠命令目录
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
fi

echo ""
echo "安装完成。"
