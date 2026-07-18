#!/usr/bin/env python3
"""为 skill-garden 独立安装器应用 Trellis 声明式变换。"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


SCHEMA_VERSION = 1
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
OPERATIONS = {"insert", "replace", "remove"}
TARGET_KINDS = {"workflow", "skill", "command", "hook"}
INSERT_POSITIONS = {"before", "after"}
MARKER_STYLES = {"html", "hash", "slash"}


class TransformError(RuntimeError):
    """表示声明、预检或应用阶段无法安全继续。"""


def _assert_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TransformError(f"{label} 必须是对象")
    return value


def _assert_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise TransformError(f"{label} 必须是小写连字符 ID")
    return value


def _resolve_relative(root: Path, relative: Any, label: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise TransformError(f"{label} 必须是 POSIX 相对路径")
    posix = PurePosixPath(relative)
    windows = PureWindowsPath(relative)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        raise TransformError(f"{label} 必须是 POSIX 相对路径")
    if any(part in {"", ".", ".."} for part in relative.split("/")):
        raise TransformError(f"{label} 包含不安全路径片段:{relative}")
    resolved_root = root.resolve()
    resolved = resolved_root.joinpath(*posix.parts)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise TransformError(f"{label} 逃逸根目录:{relative}") from error
    return resolved


def _assert_existing_inside(root: Path, file: Path, label: str) -> None:
    try:
        file.resolve(strict=True).relative_to(root.resolve(strict=True))
    except ValueError as error:
        raise TransformError(f"{label} 通过软链逃逸根目录:{file}") from error


def _read_source(transform_dir: Path, relative: Any, label: str) -> str:
    file = _resolve_relative(transform_dir, relative, label)
    if not file.is_file():
        raise TransformError(f"{label} 不存在:{relative}")
    _assert_existing_inside(transform_dir, file, label)
    value = file.read_text(encoding="utf-8")
    if not value:
        raise TransformError(f"{label} 不能为空:{relative}")
    return value


def _should_install(name: str, skills: list[str], aliases: list[str]) -> bool:
    if not skills:
        return True
    stripped = name.removeprefix("trellis-")
    return any(item in {name, stripped} or item in aliases for item in skills)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+$", "", value) + "\n"


def _marker_parts(
    operation_id: str,
    content: str,
    marker_style: str = "html",
) -> tuple[str, str, str, re.Pattern[str]]:
    if marker_style == "hash":
        begin = f"# BEGIN skill-garden transform {operation_id} v0.6"
        end = f"# END skill-garden transform {operation_id} v0.6"
    elif marker_style == "slash":
        begin = f"// BEGIN skill-garden transform {operation_id} v0.6"
        end = f"// END skill-garden transform {operation_id} v0.6"
    else:
        begin = f"<!-- BEGIN skill-garden transform {operation_id} v0.6 -->"
        end = f"<!-- END skill-garden transform {operation_id} v0.6 -->"
    body = re.sub(r"\s+$", "", content) + "\n" if content else ""
    block = f"{begin}\n{body}{end}"
    pattern = re.compile(re.escape(begin) + r"\n.*?" + re.escape(end), re.DOTALL)
    return begin, end, block, pattern


def _apply_operation(value: str, operation: dict[str, Any]) -> tuple[str, str]:
    managed = _marker_parts(
        operation["id"],
        operation["content"],
        operation["marker_style"],
    )
    variants = [managed]
    if operation["marker_style"] != "html":
        variants.append(_marker_parts(operation["id"], operation["content"], "html"))
    active = []
    for variant in variants:
        begin, end, _, _ = variant
        begin_count = value.count(begin)
        end_count = value.count(end)
        if begin_count != end_count:
            raise TransformError(f"managed marker 不配对:{begin_count}/{end_count}")
        if begin_count > 0:
            active.append((variant, begin_count))
    if len(active) > 1:
        raise TransformError("managed marker 同时存在多种 style")
    if active:
        (active_marker, begin_count) = active[0]
        if begin_count != operation["expected_matches"]:
            raise TransformError(
                f"managed marker 数量 {begin_count} 不等于预期 {operation['expected_matches']}"
            )
        _, _, block, _ = managed
        _, _, _, active_re = active_marker
        return active_re.sub(lambda _: block, value), "managed-marker"

    selector = operation["selector"]
    matches = value.count(selector)
    if matches != operation["expected_matches"]:
        raise TransformError(
            f"selector 匹配 {matches} 次,预期 {operation['expected_matches']} 次"
        )
    if operation["operation"] in {"replace", "remove"}:
        _, _, block, _ = managed
        return value.replace(selector, block), "selector"
    _, _, block, _ = managed
    replacement = (
        f"{block}\n{selector}"
        if operation["position"] == "before"
        else f"{selector}\n{block}"
    )
    return value.replace(selector, replacement), "selector"


def _normalize_operation(
    raw: Any,
    transform_dir: Path,
    declaration_id: str,
    seen_ids: set[str],
) -> dict[str, Any]:
    data = _assert_object(raw, f"transform {declaration_id} operation")
    operation_id = _assert_id(data.get("id"), f"transform {declaration_id} operation.id")
    if operation_id in seen_ids:
        raise TransformError(f"重复 transform operation id:{operation_id}")
    seen_ids.add(operation_id)
    operation = data.get("operation")
    if operation not in OPERATIONS:
        raise TransformError(f"transform {operation_id} operation 不支持:{operation}")
    targets = data.get("targets")
    if not isinstance(targets, list) or not targets:
        raise TransformError(f"transform {operation_id} targets 不能为空")
    selector_data = _assert_object(data.get("selector"), f"transform {operation_id} selector")
    expected_matches = selector_data.get("expectedMatches")
    if isinstance(expected_matches, bool) or not isinstance(expected_matches, int) or expected_matches < 1:
        raise TransformError(f"transform {operation_id} expectedMatches 必须是正整数")
    selector = re.sub(
        r"\s+$",
        "",
        _read_source(
            transform_dir,
            selector_data.get("source"),
            f"transform {operation_id} selector.source",
        ),
    )
    if not selector:
        raise TransformError(f"transform {operation_id} selector 不能为空")

    content = ""
    if operation == "remove":
        if "content" in data:
            raise TransformError(f"transform {operation_id} remove 不能声明 content")
    else:
        content_data = _assert_object(data.get("content"), f"transform {operation_id} content")
        content = re.sub(
            r"\s+$",
            "",
            _read_source(
                transform_dir,
                content_data.get("source"),
                f"transform {operation_id} content.source",
            ),
        )
    position = data.get("position")
    if operation == "insert" and position not in INSERT_POSITIONS:
        raise TransformError(f"transform {operation_id} insert position 必须是 before 或 after")

    normalized_targets = []
    for index, target in enumerate(targets):
        target_data = _assert_object(target, f"transform {operation_id} targets[{index}]")
        kind = target_data.get("kind")
        if kind not in TARGET_KINDS:
            raise TransformError(f"transform {operation_id} target.kind 不支持:{kind}")
        marker_style = target_data.get("markerStyle", "html")
        if marker_style not in MARKER_STYLES:
            raise TransformError(
                f"transform {operation_id} target.markerStyle 不支持:{marker_style}"
            )
        if kind == "hook" and "markerStyle" not in target_data:
            raise TransformError(
                f"transform {operation_id} hook target 必须显式声明 markerStyle"
            )
        normalized_targets.append(
            {
                "kind": kind,
                "path": target_data.get("path"),
                "marker_style": marker_style,
            }
        )
    return {
        "id": operation_id,
        "operation": operation,
        "required": data.get("required") is not False,
        "targets": normalized_targets,
        "selector": selector,
        "expected_matches": expected_matches,
        "content": content,
        "position": position,
    }


def _load_declarations(transform_dir: Path, skills: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
    declaration_ids: list[str] = []
    operations: list[dict[str, Any]] = []
    seen_declarations: set[str] = set()
    seen_operations: set[str] = set()
    for file in sorted(
        path
        for path in transform_dir.iterdir()
        if not path.is_symlink() and path.is_file() and path.suffix == ".json"
    ):
        raw = _assert_object(json.loads(file.read_text(encoding="utf-8")), f"transform declaration {file.name}")
        if raw.get("schemaVersion") != SCHEMA_VERSION:
            raise TransformError(
                f"transform declaration {file.name} schemaVersion 不支持:{raw.get('schemaVersion')}"
            )
        declaration_id = _assert_id(raw.get("id"), f"transform declaration {file.name} id")
        if declaration_id in seen_declarations:
            raise TransformError(f"重复 transform declaration id:{declaration_id}")
        seen_declarations.add(declaration_id)
        aliases = raw.get("aliases", [])
        if not isinstance(aliases, list) or not all(isinstance(item, str) and item for item in aliases):
            raise TransformError(f"transform declaration {file.name} aliases 必须是非空字符串数组")
        if not _should_install(declaration_id, skills, aliases):
            continue
        raw_operations = raw.get("operations")
        if not isinstance(raw_operations, list) or not raw_operations:
            raise TransformError(f"transform declaration {file.name} operations 不能为空")
        declaration_ids.append(declaration_id)
        operations.extend(
            _normalize_operation(item, transform_dir, declaration_id, seen_operations)
            for item in raw_operations
        )
    return declaration_ids, operations


def prepare_transforms(
    transform_dir: Path,
    target_root: Path,
    skills: list[str] | None = None,
) -> dict[str, Any]:
    """预检全部声明，并在内存中计算目标文件的新内容。

    Args:
        transform_dir: 声明及其 matches/content 所在目录。
        target_root: 目标 Trellis 项目根目录。
        skills: 可选的精细安装过滤名。

    Returns:
        包含 declarations、files、results 的预检计划。

    Raises:
        TransformError: 声明非法或任一 required 目标漂移。
    """
    transform_dir = transform_dir.resolve(strict=True)
    target_root = target_root.resolve(strict=True)
    declarations, operations = _load_declarations(transform_dir, skills or [])
    files: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for operation in operations:
        for target_spec in operation["targets"]:
            target_path = target_spec["path"]
            try:
                target_file = _resolve_relative(
                    target_root,
                    target_path,
                    f"transform {operation['id']} target.path",
                )
            except TransformError as error:
                errors.append({"id": operation["id"], "target": target_path, "reason": str(error)})
                continue
            if not target_file.exists():
                results.append(
                    {
                        "id": operation["id"],
                        "target": target_path,
                        "status": "missing-target",
                        "required": operation["required"],
                    }
                )
                continue
            try:
                _assert_existing_inside(
                    target_root,
                    target_file,
                    f"transform {operation['id']} target",
                )
            except TransformError as error:
                errors.append({"id": operation["id"], "target": target_path, "reason": str(error)})
                continue

            file_plan = files.get(target_path)
            if file_plan is None:
                original = target_file.read_text(encoding="utf-8")
                file_plan = {
                    "target": target_path,
                    "target_file": target_file,
                    "original": original,
                    "next": original,
                    "operations": [],
                }
                files[target_path] = file_plan
            try:
                operation_for_target = {**operation, "marker_style": target_spec["marker_style"]}
                next_value, source = _apply_operation(
                    file_plan["next"],
                    operation_for_target,
                )
            except TransformError as error:
                result = {
                    "id": operation["id"],
                    "target": target_path,
                    "status": "error" if operation["required"] else "optional-skip",
                    "required": operation["required"],
                    "reason": str(error),
                }
                results.append(result)
                if operation["required"]:
                    errors.append(result)
                continue
            file_plan["next"] = next_value
            file_plan["operations"].append(operation["id"])
            results.append(
                {
                    "id": operation["id"],
                    "target": target_path,
                    "status": "ready",
                    "required": operation["required"],
                    "source": source,
                }
            )

    if errors:
        detail = "; ".join(
            f"{item['id']}@{item['target']}:{item['reason']}" for item in errors
        )
        raise TransformError(f"声明式强化变换预检失败:{detail}")

    for file_plan in files.values():
        # optional 全跳过时逐字保留，避免仅因结尾换行而改写用户文件。
        if file_plan["operations"]:
            file_plan["next"] = _normalize_text(file_plan["next"])
        file_plan["changed"] = file_plan["next"] != file_plan["original"]
    return {"declarations": declarations, "files": list(files.values()), "results": results}


def _preserve_first_backup(target_root: Path, target_file: Path) -> tuple[Path, bool]:
    relative = target_file.relative_to(target_root)
    backup = target_root / ".trellis/.backup-flower" / relative
    if backup.exists():
        return backup, False
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target_file, backup)
    return backup, True


def apply_prepared(target_root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """应用已通过预检的计划，并保留每个目标的首次备份。

    Args:
        target_root: 目标 Trellis 项目根目录。
        plan: prepare_transforms 返回的完整计划。

    Returns:
        changed、unchanged、skipped、targets 与 backupNotes 汇总。

    Raises:
        TransformError: 预检后目标发生并发漂移。
    """
    target_root = target_root.resolve(strict=True)
    for file_plan in plan["files"]:
        if file_plan["target_file"].read_text(encoding="utf-8") != file_plan["original"]:
            raise TransformError(f"声明式强化变换目标在应用前发生漂移:{file_plan['target']}")

    changed = 0
    unchanged = 0
    backup_notes: list[str] = []
    for file_plan in plan["files"]:
        if not file_plan["changed"]:
            unchanged += 1
            continue
        backup, created = _preserve_first_backup(target_root, file_plan["target_file"])
        note = f"{'已创建' if created else '保留已有'} {backup.relative_to(target_root).as_posix()}"
        if note not in backup_notes:
            backup_notes.append(note)
        file_plan["target_file"].write_text(file_plan["next"], encoding="utf-8")
        changed += 1
    skipped = sum(
        item["status"] in {"missing-target", "optional-skip"} for item in plan["results"]
    )
    return {
        "changed": changed,
        "unchanged": unchanged,
        "skipped": skipped,
        "targets": [item["target"] for item in plan["files"]],
        "backupNotes": backup_notes,
        "results": plan["results"],
    }


def main(argv: list[str] | None = None) -> int:
    """解析命令行参数并执行声明式变换。

    Args:
        argv: 不含程序名的参数；默认读取 sys.argv[1:]。

    Returns:
        成功返回 0，声明或预检失败返回 1，参数错误返回 2。
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print(
            "用法: apply-trellis-transforms.py <transform-dir> <target-project> [skill-name...]",
            file=sys.stderr,
        )
        return 2
    try:
        plan = prepare_transforms(Path(args[0]), Path(args[1]), args[2:])
        result = apply_prepared(Path(args[1]), plan)
    except (OSError, UnicodeError, json.JSONDecodeError, TransformError) as error:
        print(f"❌ {error}", file=sys.stderr)
        return 1
    print(
        "  ✓ 声明式变换 "
        f"changed={result['changed']} unchanged={result['unchanged']} skipped={result['skipped']}"
    )
    for item in result["results"]:
        if item["status"] == "optional-skip":
            print(
                "  · optional transform 跳过:"
                f"{item['id']}@{item['target']}({item['reason']})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
