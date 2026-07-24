#!/usr/bin/env python3
"""生成或校验 Skill-Garden 的 canonical Trellis Patch 最终产物。"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_GARDEN_ROOT = SCRIPT_DIR.parent
OVERRIDES_DIR = SKILL_GARDEN_ROOT / ".trellis/0.6/overrides"
DEFAULT_OUTPUT_ROOT = SKILL_GARDEN_ROOT / "compiled-targets"
RUNNER_FILE = SCRIPT_DIR / "apply-trellis-patches.py"
SEMVER_DIR_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
CANONICAL_INIT_ARGS = (
    "init",
    "--claude",
    "--codex",
    "--yes",
    "--no-monorepo",
    "--user",
    "patch-target-compiler",
)


class CompiledTargetError(RuntimeError):
    """表示 canonical fixture、生成目录或漂移检查无法安全继续。"""


def _load_patch_runner() -> ModuleType:
    """加载 Skill-Garden 正式 Python Patch consumer。

    Returns:
        已加载的 `apply-trellis-patches.py` 模块。

    Raises:
        CompiledTargetError: consumer 无法加载。
    """
    spec = importlib.util.spec_from_file_location("skill_garden_patches", RUNNER_FILE)
    if spec is None or spec.loader is None:
        raise CompiledTargetError(f"无法加载 Patch consumer:{RUNNER_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_command(value: str | None, label: str) -> Path:
    """把显式路径或 PATH 命令解析为普通文件。

    Args:
        value: 显式路径或命令名。
        label: 错误信息中的命令名称。

    Returns:
        已解析的绝对文件路径。

    Raises:
        CompiledTargetError: 命令缺失或不是普通文件。
    """
    if not value:
        raise CompiledTargetError(f"缺少 {label}")
    candidate = Path(value).expanduser()
    resolved = candidate.resolve() if candidate.exists() else None
    if resolved is None:
        found = shutil.which(value)
        resolved = Path(found).resolve() if found else None
    if resolved is None or not resolved.is_file():
        raise CompiledTargetError(f"{label} 不存在或不是普通文件:{value}")
    return resolved


def _trellis_command(trellis_bin: str | None, node_bin: str | None) -> list[str]:
    """构造 canonical fixture 使用的 Trellis 执行命令。

    Args:
        trellis_bin: Trellis 可执行文件或 JavaScript bin。
        node_bin: JavaScript bin 使用的 Node executable。

    Returns:
        可直接交给 `subprocess.run` 的命令前缀。

    Raises:
        CompiledTargetError: Trellis 或 Node executable 无法解析。
    """
    trellis = _resolve_command(
        trellis_bin or os.environ.get("TRELLIS_BIN") or shutil.which("trellis"),
        "Trellis executable",
    )
    if trellis.suffix != ".js":
        return [str(trellis)]
    node = _resolve_command(
        node_bin or os.environ.get("NODE_BIN") or shutil.which("node"),
        "Node executable",
    )
    return [str(node), str(trellis)]


def _create_canonical_fixture(command: list[str], target: Path) -> None:
    """初始化 Claude + Codex canonical Trellis 项目。

    Args:
        command: Trellis 执行命令前缀。
        target: 已存在的空临时目录。

    Returns:
        无返回值。

    Raises:
        CompiledTargetError: Trellis init 执行失败。
    """
    result = subprocess.run(
        [*command, *CANONICAL_INIT_ARGS],
        cwd=target,
        env={**os.environ, "NO_COLOR": "1"},
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or str(result.returncode)
        raise CompiledTargetError(f"canonical Trellis init 失败:{detail}")


def _summary(diagnostics: list[dict[str, Any]]) -> dict[str, int]:
    """汇总结构化诊断数量。

    Args:
        diagnostics: Patch policy diagnostics。

    Returns:
        errors、warnings 与 info 数量。
    """
    return {
        "errors": sum(item["severity"] == "error" for item in diagnostics),
        "warnings": sum(item["severity"] == "warning" for item in diagnostics),
        "info": sum(item["severity"] == "info" for item in diagnostics),
    }


def _serialize_plan(
    version: str,
    plan: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    """移除运行时路径和内存原文，生成稳定审阅计划。

    Args:
        version: canonical fixture 的 Trellis 版本。
        plan: Python consumer 返回的完整预检计划。
        report: compatibility/conflict 汇总。

    Returns:
        可稳定 JSON 序列化的公开计划。
    """
    return {
        "schemaVersion": 1,
        "trellisVersion": version,
        "mode": "full",
        "profile": {
            "id": "claude-codex",
            "platforms": ["claude", "codex"],
            "roots": [".trellis", ".agents", ".claude", ".codex"],
        },
        "catalogHash": plan["catalogHash"],
        "catalogs": plan["catalogs"],
        "selectedBundles": plan["selectedBundles"],
        "selectedPatches": plan["selectedPatches"],
        "operationOrder": plan["operationOrder"],
        "catalogOperations": plan["catalogOperations"],
        "targets": [
            {
                "target": item["target"],
                "beforeHash": item["before_hash"],
                "afterHash": item["after_hash"],
                "changed": item["changed"],
                "originalExists": item["original_exists"],
                "operations": item["operation_entries"],
            }
            for item in plan["files"]
        ],
        "results": [
            {
                "id": item["id"],
                "catalog": item["catalog"],
                "qualifiedId": item["qualifiedId"],
                "patch": item["patch"],
                "qualifiedPatch": item["qualifiedPatch"],
                "bundle": item["bundle"],
                "bundles": item["bundles"],
                "target": item["target"],
                "status": item["status"],
                "required": item["required"],
                **({"reason": item["reason"]} if item.get("reason") else {}),
            }
            for item in plan["results"]
        ],
        "conflicts": {
            "version": report["version"],
            "summary": report["summary"],
            "diagnostics": report["diagnostics"],
        },
    }


def _write_text(root: Path, relative: str, value: str) -> None:
    """在生成根内写入 UTF-8 文本。

    Args:
        root: 生成树根目录。
        relative: POSIX 相对路径。
        value: 文件内容。

    Returns:
        无返回值。
    """
    target = root.joinpath(*relative.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")


def _assert_target_output_paths(plan: dict[str, Any]) -> None:
    """拒绝最终文件与 `.diff` sidecar 的路径冲突。

    Args:
        plan: Python consumer 返回的完整预检计划。

    Returns:
        无返回值。

    Raises:
        CompiledTargetError: 输出路径同名或形成文件/目录前缀冲突。
    """
    owners: dict[str, str] = {}
    for item in plan["files"]:
        target = item["target"]
        candidates = [(f"targets/{target}", f"target:{target}")]
        if item["changed"]:
            candidates.append((f"targets/{target}.diff", f"diff:{target}"))
        for relative, owner in candidates:
            previous = owners.get(relative)
            if previous is not None:
                raise CompiledTargetError(
                    f"compiled target 输出路径冲突:{relative}:{previous}:{owner}"
                )
            owners[relative] = owner
    ordered = sorted(owners)
    for current, following in zip(ordered, ordered[1:]):
        if following.startswith(f"{current}/"):
            raise CompiledTargetError(
                "compiled target 文件/目录路径冲突:"
                f"{current}:{owners[current]}:{following}:{owners[following]}"
            )


def _unified_diff(target: str, original: str | None, next_value: str) -> str:
    """生成带稳定逻辑标签的三行上下文 unified diff。

    Args:
        target: 目标 POSIX 相对路径。
        original: 原始内容；新文件为 None。
        next_value: 最终内容。

    Returns:
        Git 可读的稳定 unified diff。
    """
    before = [] if original is None else original.splitlines(keepends=True)
    after = next_value.splitlines(keepends=True)
    body_parts: list[str] = []
    for line in difflib.unified_diff(
        before,
        after,
        fromfile="/dev/null" if original is None else f"a/{target}",
        tofile=f"b/{target}",
        n=3,
        lineterm="\n",
    ):
        body_parts.append(line)
        if not line.endswith(("\n", "\r")):
            # difflib 保留输入行尾；这里补标准标记，避免删除行与新增行粘连。
            body_parts.append("\n\\ No newline at end of file\n")
    body = "".join(body_parts)
    if body and not body.endswith("\n"):
        body += "\n"
    return f"diff --git a/{target} b/{target}\n{body}"


def _list_files(root: Path) -> list[str]:
    """列出普通文件并拒绝生成树中的软链或特殊节点。

    Args:
        root: 待检查目录。

    Returns:
        排序后的 POSIX 相对文件路径。

    Raises:
        CompiledTargetError: 发现软链或特殊节点。
    """
    if not root.exists():
        return []
    files: list[str] = []
    for item in sorted(root.rglob("*")):
        relative = item.relative_to(root).as_posix()
        if item.is_symlink():
            raise CompiledTargetError(f"compiled targets 不允许软链:{relative}")
        if item.is_dir():
            continue
        if not item.is_file():
            raise CompiledTargetError(f"compiled targets 不允许特殊文件:{relative}")
        files.append(relative)
    return files


def _assert_output_boundary(output_root: Path) -> None:
    """校验可替换目录只包含合法 Trellis 版本子目录。

    Args:
        output_root: compiled targets 输出根。

    Returns:
        无返回值。

    Raises:
        CompiledTargetError: 输出根名称、类型或版本项非法。
    """
    if output_root.name != "compiled-targets":
        raise CompiledTargetError(f"输出根名称必须为 compiled-targets:{output_root}")
    if not output_root.exists():
        return
    if output_root.is_symlink() or not output_root.is_dir():
        raise CompiledTargetError(f"compiled targets 根必须是普通目录:{output_root}")
    for item in output_root.iterdir():
        if item.is_symlink() or not item.is_dir() or not SEMVER_DIR_RE.fullmatch(item.name):
            raise CompiledTargetError(f"compiled targets 根包含非法版本项:{item.name}")


def _compare_trees(expected: Path, actual: Path) -> list[str]:
    """逐文件逐字节比较两棵 generated tree。

    Args:
        expected: 本次重新生成的期望树。
        actual: 已提交或待校验的实际树。

    Returns:
        稳定排序的漂移描述。
    """
    expected_files = _list_files(expected)
    actual_files = _list_files(actual)
    expected_set = set(expected_files)
    actual_set = set(actual_files)
    drift: list[str] = []
    for relative in expected_files:
        if relative not in actual_set:
            drift.append(f"缺失:{relative}")
        elif (expected / relative).read_bytes() != (actual / relative).read_bytes():
            drift.append(f"变更:{relative}")
    for relative in actual_files:
        if relative not in expected_set:
            drift.append(f"多余:{relative}")
    return drift


def _replace_output(staging: Path, output_root: Path) -> list[str]:
    """用 staging 原子边界替换已有 generated tree。

    Args:
        staging: 已完整生成的临时目录。
        output_root: 目标 compiled targets 根。

    Returns:
        不影响新产物有效性的清理警告。

    Raises:
        CompiledTargetError: 备份冲突或替换失败。
    """
    _assert_output_boundary(output_root)
    backup = output_root.with_name(f"{output_root.name}.backup-{os.getpid()}")
    if backup.exists():
        raise CompiledTargetError(f"compiled targets 备份路径已存在:{backup}")
    backed_up = False
    try:
        if output_root.exists():
            output_root.rename(backup)
            backed_up = True
        staging.rename(output_root)
    except OSError as error:
        if not output_root.exists() and backed_up and backup.exists():
            backup.rename(output_root)
        raise CompiledTargetError(f"替换 compiled targets 失败:{error}") from error
    if not backed_up:
        return []
    try:
        shutil.rmtree(backup)
    except OSError as error:
        # 新树已经完整换入，清理旧备份失败不能再把已提交结果报告成生成失败。
        return [f"旧 compiled targets 备份清理失败:{backup}:{error}"]
    return []


def _build_tree(root: Path, fixture: Path, version: str, plan: dict[str, Any], report: dict[str, Any]) -> None:
    """构建 canonical plan、最终文件和 changed-only diff。

    Args:
        root: staging 根目录。
        fixture: 已应用 Patch 的 canonical Trellis 项目。
        version: Trellis 版本。
        plan: Python consumer 计划。
        report: compatibility/conflict 报告。

    Returns:
        无返回值。
    """
    _assert_target_output_paths(plan)
    full_root = root / version / "full"
    _write_text(
        full_root,
        "plan.json",
        f"{json.dumps(_serialize_plan(version, plan, report), ensure_ascii=False, indent=2)}\n",
    )
    for item in plan["files"]:
        target = item["target"]
        final_value = fixture.joinpath(*target.split("/")).read_text(encoding="utf-8")
        _write_text(full_root, f"targets/{target}", final_value)
        if item["changed"]:
            _write_text(
                full_root,
                f"targets/{target}.diff",
                _unified_diff(target, item["original"], final_value),
            )


def generate_compiled_targets(
    *,
    check: bool = False,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    trellis_bin: str | None = None,
    node_bin: str | None = None,
) -> dict[str, Any]:
    """生成或校验 Skill-Garden canonical compiled targets。

    Args:
        check: 是否只比较已提交结果而不替换目录。
        output_root: 名称必须为 `compiled-targets` 的输出根。
        trellis_bin: Trellis executable 或 JavaScript bin。
        node_bin: JavaScript Trellis bin 使用的 Node executable。

    Returns:
        version、files、changedTargets 与可选 warnings 汇总。

    Raises:
        CompiledTargetError: 初始化、Patch、目录边界或漂移检查失败。
    """
    output_root = output_root.expanduser().resolve()
    output_root.parent.mkdir(parents=True, exist_ok=True)
    _assert_output_boundary(output_root)
    command = _trellis_command(trellis_bin, node_bin)
    runner = _load_patch_runner()
    staging = Path(
        tempfile.mkdtemp(prefix=".compiled-targets-staging-", dir=output_root.parent)
    )
    try:
        with tempfile.TemporaryDirectory(prefix="skill-garden-compiled-") as temp:
            fixture = Path(temp)
            _create_canonical_fixture(command, fixture)
            version = (fixture / ".trellis/.version").read_text(encoding="utf-8").strip()
            policy = runner.load_patch_policy(OVERRIDES_DIR)
            compatibility = runner.evaluate_patch_compatibility(
                version,
                policy["compatibility"],
            )
            compatibility_report = {
                "version": compatibility["version"],
                "diagnostics": compatibility["diagnostics"],
                "summary": _summary(compatibility["diagnostics"]),
            }
            runner.assert_no_patch_conflict_errors(compatibility_report)
            plan = runner.prepare_patches(OVERRIDES_DIR, fixture)
            report = runner.build_patch_conflict_report(version, plan, policy)
            runner.assert_no_patch_conflict_errors(report)
            runner.apply_prepared(fixture, plan)
            _build_tree(staging, fixture, version, plan, report)
            summary = {
                "version": version,
                "files": len(_list_files(staging)),
                "changedTargets": sum(item["changed"] for item in plan["files"]),
            }
        if check:
            drift = _compare_trees(staging, output_root)
            if drift:
                raise CompiledTargetError(
                    "compiled targets 漂移:\n"
                    + "\n".join(drift)
                    + "\n请运行 npm run patch:targets"
                )
            return summary
        summary["warnings"] = _replace_output(staging, output_root)
        return summary
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """解析维护脚本参数。

    Args:
        argv: 不含程序名的参数。

    Returns:
        argparse 结果。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只校验已提交结果")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--trellis-bin")
    parser.add_argument("--node-bin")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """执行 canonical compiled target 生成或漂移检查。

    Args:
        argv: 不含程序名的参数；默认读取 `sys.argv[1:]`。

    Returns:
        进程退出码。
    """
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        summary = generate_compiled_targets(
            check=args.check,
            output_root=args.output_root,
            trellis_bin=args.trellis_bin,
            node_bin=args.node_bin,
        )
        action = "无漂移" if args.check else "已生成"
        print(
            f"✓ Skill-Garden compiled targets {action}:Trellis {summary['version']}，"
            f"{summary['files']} 个文件，{summary['changedTargets']} 个变更 target"
        )
        for warning in summary.get("warnings", []):
            print(f"⚠ {warning}", file=sys.stderr)
        return 0
    except Exception as error:
        print(f"❌ Skill-Garden compiled targets 失败:{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
