#!/usr/bin/env bash
# install-route-workflow.sh
#
# 把 skill-garden override block 注入目标项目 .trellis/workflow.md 顶部，
# 让 trellis 上游 body 完全保持原状，override block 享有 PRIORITY: HIGHEST。
#
# 行为：
# - 读 .trellis/0.5/overrides/trellis-route.md 作为 override 模板
# - 在目标 workflow.md **顶部**插入整块 override（含 BEGIN/END HTML 注释 marker）
# - 上游 body 一字不动，未来 sync 上游 workflow.md 完全无冲突
# - 幂等：检测到 BEGIN marker 已存在则直接退出
# - 版本检查：要求目标 .trellis/.version >= 0.5.0
# - 备份：原 workflow.md 复制为 workflow.md.bak
#
# 用法：
#   bash install-route-workflow.sh <target-project-dir>
#
# 前置：
#   - 目标项目已 trellis init（含 .trellis/workflow.md 和 .trellis/.version）
#   - 同时需要安装 trellis-route SKILL（用 install.sh 装）

set -euo pipefail

usage() {
  cat >&2 <<'EOF'
用法: install-route-workflow.sh <target-project-dir>

把 skill-garden trellis-route override block 插入目标 .trellis/workflow.md 顶部。
- 上游 body 不动，未来 sync 上游零冲突
- 幂等：已含 BEGIN marker 则跳过
- 备份：原文件复制为 workflow.md.bak
- 仅支持 trellis >= 0.5.0

也请确保 trellis-route SKILL 已通过 scripts/install.sh 装到目标项目。
EOF
}

if [ $# -ne 1 ] || [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
  usage
  exit 1
fi

TARGET="$1"

if [ ! -d "$TARGET" ]; then
  echo "❌ 目标目录不存在: $TARGET" >&2
  exit 1
fi

# 推断 skill-garden 根（脚本所在目录的父目录）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OVERRIDE_FILE="$SCRIPT_DIR/../.trellis/0.5/overrides/trellis-route.md"

python3 - "$TARGET" "$OVERRIDE_FILE" <<'PYTHON_PATCH'
import sys
import re
from pathlib import Path

target = Path(sys.argv[1])
override_path = Path(sys.argv[2])

# ============================================================
# 1. 版本检查：仅支持 trellis >= 0.5.0
# ============================================================
version_file = target / ".trellis" / ".version"
if not version_file.is_file():
    sys.exit(f"❌ {version_file} 不存在 — 目标可能不是 trellis 项目，或缺 .version 文件")

version = version_file.read_text(encoding="utf-8").strip()
m = re.match(r'^(\d+)\.(\d+)', version)
if not m:
    sys.exit(f"❌ 无法解析 .version: {version!r}")

major, minor = int(m.group(1)), int(m.group(2))
if (major, minor) < (0, 5):
    sys.exit(f"❌ trellis-route override 仅支持 trellis >= 0.5.0；目标版本: {version}")

print(f"✓ trellis 版本: {version}（>= 0.5.0 ✓）")

# ============================================================
# 2. workflow.md 存在
# ============================================================
wf = target / ".trellis" / "workflow.md"
if not wf.is_file():
    sys.exit(f"❌ {wf} 不存在 — 目标可能不是 trellis 项目")

# ============================================================
# 3. override 模板存在
# ============================================================
if not override_path.is_file():
    sys.exit(f"❌ override 模板缺失: {override_path}（skill-garden 安装不完整？）")

# ============================================================
# 4. 幂等：检测目标是否已含 override block
# ============================================================
BEGIN_MARKER = "<!-- BEGIN skill-garden enhancement v0.5 -->"
END_MARKER = "<!-- END skill-garden enhancement v0.5 -->"

content = wf.read_text(encoding="utf-8")

if BEGIN_MARKER in content:
    print(f"✓ {wf} 已含 skill-garden override block，跳过 patch（幂等）")
    sys.exit(0)

# ============================================================
# 5. 备份
# ============================================================
override = override_path.read_text(encoding="utf-8")

# 校验模板完整性
if BEGIN_MARKER not in override or END_MARKER not in override:
    sys.exit(f"❌ override 模板损坏 — BEGIN/END marker 缺失: {override_path}")

bak = wf.with_name(wf.name + ".bak")
bak.write_text(content, encoding="utf-8")
print(f"✓ 备份 → {bak}")

# ============================================================
# 6. 在文件顶部插入 override block
# ============================================================
# 确保 override 末尾有换行 + 一个空行，与原 body 之间清晰分隔
override_normalized = override.rstrip("\n") + "\n\n"
new_content = override_normalized + content

wf.write_text(new_content, encoding="utf-8")

# ============================================================
# 7. 验证
# ============================================================
verify = wf.read_text(encoding="utf-8")
if BEGIN_MARKER not in verify or END_MARKER not in verify:
    sys.exit("❌ 插入后验证失败 — BEGIN/END marker 未找到，可能写入异常")

print(f"\n✓ 完成：{wf} 顶部已插入 trellis-route override block")
print(f"  ├── 上游 body 一字不动，未来 sync 上游零冲突")
print(f"  └── 回滚: cp {bak} {wf}")
print(f"\n提示：还需安装 trellis-route SKILL，运行：")
print(f"  bash <skill-garden>/scripts/install.sh {target} trellis-route")
PYTHON_PATCH
