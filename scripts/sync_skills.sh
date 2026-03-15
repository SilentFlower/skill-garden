#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
GARDEN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"

usage() {
  echo "用法: sync_skills.sh <target-project-dir> [skill-name...]" >&2
}

ensure_dir() {
  local path="$1"
  mkdir -p "$path"
}

link_one() {
  local source_path="$1"
  local target_path="$2"

  if [[ -L "$target_path" ]]; then
    local current
    current="$(readlink -f "$target_path")"
    if [[ "$current" == "$(readlink -f "$source_path")" ]]; then
      echo "已存在: $target_path"
      return 0
    fi
    echo "跳过: $target_path 已链接到其他位置" >&2
    return 0
  fi

  if [[ -e "$target_path" ]]; then
    echo "跳过: $target_path 已存在且不是符号链接" >&2
    return 0
  fi

  ln -s "$source_path" "$target_path"
  echo "已创建: $target_path -> $source_path"
}

collect_skill_names() {
  local codex_dir="$1"
  local claude_dir="$2"
  local names=()
  local seen=""

  if [[ -d "$codex_dir" ]]; then
    while IFS= read -r item; do
      [[ -z "$item" ]] && continue
      names+=("$item")
    done < <(find "$codex_dir" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
  fi

  if [[ -d "$claude_dir" ]]; then
    while IFS= read -r item; do
      [[ -z "$item" ]] && continue
      names+=("$item")
    done < <(find "$claude_dir" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
  fi

  printf '%s\n' "${names[@]}" | awk '!seen[$0]++'
}

if [[ $# -lt 1 ]]; then
  usage
  exit 2
fi

TARGET_ROOT="$(cd "$1" && pwd -P)"
shift

SOURCE_CODEX_SKILLS="$GARDEN_ROOT/.codex/skills"
SOURCE_CLAUDE_SKILLS="$GARDEN_ROOT/.claude/skills"
TARGET_CODEX_SKILLS="$TARGET_ROOT/.codex/skills"
TARGET_CLAUDE_SKILLS="$TARGET_ROOT/.claude/skills"

ensure_dir "$TARGET_CODEX_SKILLS"
ensure_dir "$TARGET_CLAUDE_SKILLS"

if [[ $# -gt 0 ]]; then
  mapfile -t SKILL_NAMES < <(printf '%s\n' "$@")
else
  mapfile -t SKILL_NAMES < <(collect_skill_names "$SOURCE_CODEX_SKILLS" "$SOURCE_CLAUDE_SKILLS")
fi

for skill_name in "${SKILL_NAMES[@]}"; do
  [[ -z "$skill_name" ]] && continue
  if [[ -d "$SOURCE_CODEX_SKILLS/$skill_name" ]]; then
    link_one "$SOURCE_CODEX_SKILLS/$skill_name" "$TARGET_CODEX_SKILLS/$skill_name"
  fi
  if [[ -d "$SOURCE_CLAUDE_SKILLS/$skill_name" ]]; then
    link_one "$SOURCE_CLAUDE_SKILLS/$skill_name" "$TARGET_CLAUDE_SKILLS/$skill_name"
  fi
done

