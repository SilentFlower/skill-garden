#!/usr/bin/env python3
"""为 skill-garden 独立安装器应用 Trellis Patch catalog。"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


PATCH_SCHEMA_VERSION = 2
BUNDLE_SCHEMA_VERSION = 1
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LEGACY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
OPERATIONS = {"insert", "replace", "remove"}
TARGET_KINDS = {
    "workflow",
    "skill",
    "command",
    "hook",
    "markdown",
    "file",
    "json",
    "yaml",
    "toml",
}
SELECTORS = {
    "literal",
    "workflow-state",
    "workflow-hub",
    "markdown-section",
    "markdown-document",
    "whole-file",
}
MISSING_POLICIES = {"skip", "create", "error"}
CREATABLE_TARGET_KINDS = {"json", "yaml", "toml"}
TARGET_POLICIES = {"each-existing", "at-least-one", "required-all"}
MARKER_STYLES = {"html", "hash", "slash", "none"}
INSTALL_MODES = {"full-or-selected", "full-only"}


class PatchError(RuntimeError):
    """表示 Patch 声明、预检或应用阶段无法安全继续。"""


def _assert_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PatchError(f"{label} 必须是对象")
    return value


def _assert_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise PatchError(f"{label} 必须是小写连字符 ID")
    return value


def _assert_legacy_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not LEGACY_ID_RE.fullmatch(value):
        raise PatchError(f"{label} 必须是安全的历史 ID")
    return value


def _resolve_relative(root: Path, relative: Any, label: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise PatchError(f"{label} 必须是 POSIX 相对路径")
    posix = PurePosixPath(relative)
    windows = PureWindowsPath(relative)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        raise PatchError(f"{label} 必须是 POSIX 相对路径")
    if any(part in {"", ".", ".."} for part in relative.split("/")):
        raise PatchError(f"{label} 包含不安全路径片段:{relative}")
    resolved_root = root.resolve()
    resolved = resolved_root.joinpath(*posix.parts)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise PatchError(f"{label} 逃逸根目录:{relative}") from error
    return resolved


def _assert_existing_inside(root: Path, file: Path, label: str) -> None:
    try:
        file.resolve(strict=True).relative_to(root.resolve(strict=True))
    except ValueError as error:
        raise PatchError(f"{label} 通过软链逃逸根目录:{file}") from error


def _read_source(leaf_dir: Path, relative: Any, label: str) -> str:
    file = _resolve_relative(leaf_dir, relative, label)
    if not file.is_file():
        raise PatchError(f"{label} 不存在:{relative}")
    _assert_existing_inside(leaf_dir, file, label)
    value = file.read_text(encoding="utf-8")
    if not value:
        raise PatchError(f"{label} 不能为空:{relative}")
    return value


def _read_content(leaf_dir: Path, raw: Any, label: str) -> Any:
    data = _assert_object(raw, label)
    keys = [key for key in ("source", "sources", "value") if key in data]
    if len(keys) != 1:
        raise PatchError(f"{label} 必须且只能声明 source、sources 或 value")
    if keys[0] == "value":
        return data["value"]
    if keys[0] == "source":
        return _read_source(leaf_dir, data["source"], f"{label}.source")
    sources = data["sources"]
    if not isinstance(sources, list) or not sources:
        raise PatchError(f"{label}.sources 必须是非空数组")
    return "\n".join(
        re.sub(r"\s+$", "", _read_source(leaf_dir, source, f"{label}.sources[{index}]"))
        for index, source in enumerate(sources)
    )


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+$", "", value) + "\n"


def _sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _should_install(name: str, skills: list[str], aliases: list[str]) -> bool:
    if not skills:
        return True
    stripped = name.removeprefix("trellis-")
    return any(item in {name, stripped} or item in aliases for item in skills)


def _marker_lines(namespace: str, marker_id: str, style: str) -> tuple[str, str]:
    label = f"skill-garden {namespace} {marker_id} v0.6"
    if style == "hash":
        return f"# BEGIN {label}", f"# END {label}"
    if style == "slash":
        return f"// BEGIN {label}", f"// END {label}"
    return f"<!-- BEGIN {label} -->", f"<!-- END {label} -->"


def _marker_parts(
    namespace: str,
    marker_id: str,
    content: str,
    style: str,
) -> tuple[str, str, str, re.Pattern[str]]:
    begin, end = _marker_lines(namespace, marker_id, style)
    body = re.sub(r"\s+$", "", content) + "\n" if content else ""
    block = f"{begin}\n{body}{end}"
    pattern = re.compile(re.escape(begin) + r"\n.*?" + re.escape(end), re.DOTALL)
    return begin, end, block, pattern


def _active_marker(value: str, operation: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [
        {
            "namespace": "patch",
            "id": operation["id"],
            "style": operation["marker_style"],
            "source": "managed-marker",
        },
        *[
            {
                "namespace": item["namespace"],
                "id": item["id"],
                "style": item.get("style") or operation["marker_style"],
                "source": "legacy-marker",
            }
            for item in operation["legacy_markers"]
        ],
    ]
    if operation["marker_style"] != "html":
        candidates.append(
            {
                "namespace": "patch",
                "id": operation["id"],
                "style": "html",
                "source": "legacy-marker-style",
            }
        )
    active: list[dict[str, Any]] = []
    for candidate in candidates:
        marker = _marker_parts(
            candidate["namespace"],
            candidate["id"],
            operation["content"],
            candidate["style"],
        )
        begin_count = value.count(marker[0])
        end_count = value.count(marker[1])
        if begin_count != end_count:
            raise PatchError(f"managed marker 不配对:{begin_count}/{end_count}")
        if begin_count:
            active.append({**candidate, "marker": marker, "count": begin_count})
    if len(active) > 1:
        raise PatchError("managed marker 同时存在多种新旧形式")
    if not active:
        return None
    if active[0]["count"] != operation["expected_matches"]:
        raise PatchError(
            f"managed marker 数量 {active[0]['count']} 不等于预期 "
            f"{operation['expected_matches']}"
        )
    return active[0]


def _managed_block(operation: dict[str, Any]) -> tuple[str, str, str, re.Pattern[str]]:
    return _marker_parts(
        "patch",
        operation["id"],
        operation["content"],
        operation["marker_style"],
    )


def _strip_legacy_skill_override(value: str, override_id: str) -> tuple[str, bool]:
    lines = value.split("\n")
    begin_prefix = f"<!-- BEGIN skill-garden skill override {override_id}"
    end_prefix = f"<!-- END skill-garden skill override {override_id}"
    try:
        begin = next(index for index, line in enumerate(lines) if line.startswith(begin_prefix))
    except StopIteration:
        return value, False
    try:
        end = next(
            index for index, line in enumerate(lines[begin:], begin) if line.startswith(end_prefix)
        )
    except StopIteration as error:
        raise PatchError(f"legacy skill override marker 不配对:{override_id}") from error
    start = begin
    while start > 0 and not lines[start - 1].strip():
        start -= 1
    if start > 0 and re.match(r"^#{2,4} HIGHEST PRIORITY: skill-garden ", lines[start - 1]):
        start -= 1
    del lines[start : end + 1]
    while start > 0 and start < len(lines) and lines[start - 1] == "" and lines[start] == "":
        del lines[start]
    while start + 1 < len(lines) and lines[start] == "" and lines[start + 1] == "":
        del lines[start]
    return "\n".join(lines), True


def _strip_legacy_workflow_hub(value: str) -> tuple[str, bool]:
    lines = value.split("\n")
    try:
        begin = next(
            index for index, line in enumerate(lines)
            if line.startswith("<!-- BEGIN skill-garden overrides")
        )
    except StopIteration:
        return value, False
    try:
        end = next(
            index for index, line in enumerate(lines[begin:], begin)
            if line.startswith("<!-- END skill-garden overrides")
        )
    except StopIteration as error:
        raise PatchError("legacy workflow hub marker 不配对") from error
    start = begin
    while start > 0 and not lines[start - 1].strip():
        start -= 1
    if start > 0 and re.match(
        r"^#{2,4} HIGHEST PRIORITY: skill-garden overrides",
        lines[start - 1],
    ):
        start -= 1
    del lines[start : end + 1]
    while start > 0 and start < len(lines) and lines[start - 1] == "" and lines[start] == "":
        del lines[start]
    while start + 1 < len(lines) and lines[start] == "" and lines[start + 1] == "":
        del lines[start]
    return "\n".join(lines), True


def _apply_cleanup(value: str, cleanup: list[dict[str, Any]]) -> tuple[str, bool]:
    next_value = value
    changed = False
    for item in cleanup:
        if item["type"] == "skill-override":
            next_value, item_changed = _strip_legacy_skill_override(next_value, item["id"])
        elif item["type"] == "workflow-hub":
            next_value, item_changed = _strip_legacy_workflow_hub(next_value)
        else:
            raise PatchError(f"不支持的 legacy cleanup:{item['type']}")
        changed = changed or item_changed
    return next_value, changed


def _apply_literal(value: str, operation: dict[str, Any]) -> tuple[str, str]:
    active = _active_marker(value, operation)
    managed = _managed_block(operation)
    if active:
        return active["marker"][3].sub(lambda _: managed[2], value), active["source"]
    selector = operation["selector_text"]
    matches = value.count(selector)
    if matches != operation["expected_matches"]:
        raise PatchError(
            f"selector 匹配 {matches} 次,预期 {operation['expected_matches']} 次"
        )
    if operation["operation"] in {"replace", "remove"}:
        return value.replace(selector, managed[2]), "selector"
    replacement = (
        f"{managed[2]}\n{selector}"
        if operation["position"] == "before"
        else f"{selector}\n{managed[2]}"
    )
    return value.replace(selector, replacement), "selector"


def _workflow_state_pattern(name: str) -> re.Pattern[str]:
    return re.compile(
        r"^(\[workflow-state:" + re.escape(name) + r"\]\n)(.*?)(^\[/workflow-state:"
        + re.escape(name)
        + r"\])",
        re.DOTALL | re.MULTILINE,
    )


def _apply_workflow_state(value: str, operation: dict[str, Any]) -> tuple[str, str]:
    if operation["operation"] != "replace" or operation.get("scope") != "body":
        raise PatchError("workflow-state 只支持 replace body")
    pattern = _workflow_state_pattern(operation["selector"]["name"])
    match = pattern.search(value)
    if not match:
        raise PatchError(f"未找到 workflow-state:{operation['selector']['name']}")
    body = match.group(2)
    active = _active_marker(body, operation)
    source = active["source"] if active else None
    if source is None:
        normalized_body = body.strip()
        baseline_match = any(item.strip() == normalized_body for item in operation["baselines"])
        legacy_match = any(
            any(
                _marker_lines(item["namespace"], item["id"], style)[0] in body
                for style in {item.get("style") or operation["marker_style"], "html"}
                if style != "none"
            )
            for item in operation["legacy_markers"]
        )
        if not baseline_match and not legacy_match:
            raise PatchError(
                f"workflow-state:{operation['selector']['name']} body fingerprint 漂移"
            )
        source = "legacy-marker" if legacy_match else "baseline"
    managed = _managed_block(operation)
    replacement = f"{match.group(1)}{managed[2]}\n{match.group(3)}"
    return pattern.sub(lambda _: replacement, value, count=1), source


def _find_heading_section(value: str, heading: str) -> tuple[str, str, str] | None:
    lines = value.split("\n")
    try:
        start = lines.index(heading)
    except ValueError:
        return None
    level_match = re.match(r"^(#+)", heading)
    if not level_match:
        return None
    level = len(level_match.group(1))
    end = len(lines)
    for index in range(start + 1, len(lines)):
        match = re.match(r"^(#+)\s", lines[index])
        if match and len(match.group(1)) <= level:
            end = index
            break
    return "\n".join(lines[:start]), "\n".join(lines[start:end]), "\n".join(lines[end:])


def _apply_markdown_section(value: str, operation: dict[str, Any]) -> tuple[str, str]:
    active = _active_marker(value, operation)
    managed = _managed_block(operation)
    if active:
        return active["marker"][3].sub(lambda _: managed[2], value), active["source"]
    found = _find_heading_section(value, operation["selector"]["heading"])
    if not found:
        raise PatchError(f"未找到 Markdown section:{operation['selector']['heading']}")
    before, section, after = found
    if operation["baselines"] and not any(
        item.rstrip() == section.rstrip() for item in operation["baselines"]
    ):
        raise PatchError(f"Markdown section fingerprint 漂移:{operation['selector']['heading']}")
    if operation["operation"] == "insert":
        replacement = (
            f"{managed[2]}\n{section}"
            if operation["position"] == "before"
            else f"{section}\n{managed[2]}"
        )
    else:
        replacement = managed[2]
    return "\n".join([before, replacement, after]), "selector"


def _frontmatter_end(value: str) -> int:
    match = re.match(r"^---\n.*?\n---\n", value, re.DOTALL)
    return match.end() if match else 0


def _apply_markdown_document(value: str, operation: dict[str, Any]) -> tuple[str, str]:
    if operation["operation"] != "replace" or operation.get("scope") != "body":
        raise PatchError("markdown-document 只支持 replace body")
    offset = _frontmatter_end(value)
    if operation["selector"].get("preserveFrontmatter") is True and offset == 0:
        raise PatchError("目标缺少 Markdown frontmatter")
    body = value[offset:].lstrip("\n")
    active = _active_marker(body, operation)
    if not active and operation["baselines"] and not any(
        item.strip() == body.strip() for item in operation["baselines"]
    ):
        raise PatchError("Markdown document body fingerprint 漂移")
    prefix = value[:offset].rstrip()
    managed = _managed_block(operation)
    return f"{prefix}\n\n{managed[2]}\n", active["source"] if active else "baseline"


def _apply_workflow_hub(value: str, operation: dict[str, Any]) -> tuple[str, str]:
    if operation["operation"] != "insert":
        raise PatchError("workflow-hub 只支持 insert")
    active = _active_marker(value, operation)
    managed = _managed_block(operation)
    if active:
        return active["marker"][3].sub(lambda _: managed[2], value), active["source"]
    heading = operation["selector"]["heading"] + "\n"
    if value.count(heading) != operation["expected_matches"]:
        raise PatchError(f"workflow hub 锚点匹配异常:{heading.rstrip()}")
    end = value.index(heading) + len(heading)
    return (
        value[:end] + "\n" + managed[2] + "\n\n" + value[end:].lstrip("\n"),
        "selector",
    )


def _apply_whole_file(value: str, operation: dict[str, Any]) -> tuple[str, str]:
    if operation["operation"] != "replace":
        raise PatchError("whole-file 只支持 replace")
    desired = _normalize_text(operation["content"])
    if _normalize_text(value) == desired:
        return desired, "desired-content"
    if operation["baselines"] and not any(
        _normalize_text(item) == _normalize_text(value) for item in operation["baselines"]
    ):
        raise PatchError("whole-file fingerprint 漂移")
    return desired, "baseline"


def _apply_operation(value: str, operation: dict[str, Any]) -> tuple[str, str]:
    selector_type = operation["selector"]["type"]
    if selector_type == "literal":
        return _apply_literal(value, operation)
    if selector_type == "workflow-state":
        return _apply_workflow_state(value, operation)
    if selector_type == "workflow-hub":
        return _apply_workflow_hub(value, operation)
    if selector_type == "markdown-section":
        return _apply_markdown_section(value, operation)
    if selector_type == "markdown-document":
        return _apply_markdown_document(value, operation)
    if selector_type == "whole-file":
        return _apply_whole_file(value, operation)
    raise PatchError(f"不支持的 Core selector:{selector_type}")


def _normalize_legacy_markers(raw: Any, label: str) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PatchError(f"{label} 必须是数组")
    normalized = []
    for index, item in enumerate(raw):
        data = _assert_object(item, f"{label}[{index}]")
        namespace = data.get("namespace")
        if not isinstance(namespace, str) or not namespace:
            raise PatchError(f"{label}[{index}].namespace 必须是非空字符串")
        marker_id = _assert_legacy_id(data.get("id"), f"{label}[{index}].id")
        style = data.get("style")
        if style is not None and style not in MARKER_STYLES:
            raise PatchError(f"{label}[{index}].style 不支持:{style}")
        normalized.append({"namespace": namespace, "id": marker_id, "style": style})
    return normalized


def _normalize_cleanup(raw: Any, label: str) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PatchError(f"{label} 必须是数组")
    normalized = []
    for index, item in enumerate(raw):
        data = _assert_object(item, f"{label}[{index}]")
        cleanup_type = data.get("type")
        if cleanup_type not in {"skill-override", "workflow-hub"}:
            raise PatchError(f"{label}[{index}].type 不支持:{cleanup_type}")
        cleanup_id = data.get("id")
        if cleanup_type == "skill-override":
            cleanup_id = _assert_id(cleanup_id, f"{label}[{index}].id")
        normalized.append({"type": cleanup_type, "id": cleanup_id})
    return normalized


def _normalize_baselines(raw: Any, leaf_dir: Path, label: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not raw:
        raise PatchError(f"{label} 必须是非空数组")
    return [
        _read_source(leaf_dir, source, f"{label}[{index}]")
        for index, source in enumerate(raw)
    ]


def _normalize_target(raw: Any, operation_id: str, index: int) -> dict[str, Any]:
    data = _assert_object(raw, f"patch {operation_id} targets[{index}]")
    kind = data.get("kind")
    if kind not in TARGET_KINDS:
        raise PatchError(f"patch {operation_id} target.kind 不支持:{kind}")
    marker_style = data.get(
        "markerStyle",
        "hash" if kind == "hook" else "none" if kind == "file" else "html",
    )
    if marker_style not in MARKER_STYLES:
        raise PatchError(f"patch {operation_id} target.markerStyle 不支持:{marker_style}")
    missing = data.get("missing", "skip")
    if missing not in MISSING_POLICIES:
        raise PatchError(f"patch {operation_id} target.missing 不支持:{missing}")
    if missing == "create" and kind not in CREATABLE_TARGET_KINDS:
        raise PatchError(
            f"patch {operation_id} missing=create 只允许 json/yaml/toml target"
        )
    requires = data.get("requires", [])
    if not isinstance(requires, list) or not all(
        isinstance(item, str) and item for item in requires
    ):
        raise PatchError(f"patch {operation_id} target.requires 必须是字符串数组")
    return {
        "kind": kind,
        "path": data.get("path"),
        "marker_style": marker_style,
        "missing": missing,
        "requires": requires,
    }


def _normalize_selector(raw: Any, leaf_dir: Path, operation_id: str) -> dict[str, Any]:
    data = _assert_object(raw, f"patch {operation_id} selector")
    selector_type = data.get("type")
    if selector_type not in SELECTORS:
        raise PatchError(f"patch {operation_id} selector.type 不支持:{selector_type}")
    expected_matches = data.get("expectedMatches", 1)
    if isinstance(expected_matches, bool) or not isinstance(expected_matches, int) or expected_matches < 1:
        raise PatchError(f"patch {operation_id} expectedMatches 必须是正整数")
    selector = {**data, "expectedMatches": expected_matches}
    if selector_type == "literal":
        selector["text"] = re.sub(
            r"\s+$",
            "",
            _read_source(leaf_dir, data.get("source"), f"patch {operation_id} selector.source"),
        )
    if selector_type == "workflow-state" and not isinstance(data.get("name"), str):
        raise PatchError(f"patch {operation_id} workflow-state name 必须是字符串")
    if selector_type == "workflow-hub" and not isinstance(data.get("heading"), str):
        raise PatchError(f"patch {operation_id} workflow-hub heading 必须是字符串")
    if selector_type == "markdown-section" and not isinstance(data.get("heading"), str):
        raise PatchError(f"patch {operation_id} markdown-section heading 必须是字符串")
    return selector


def _normalize_operation(
    raw: Any,
    leaf_dir: Path,
    patch: dict[str, Any],
    seen_operation_ids: set[str],
) -> dict[str, Any]:
    data = _assert_object(raw, f"patch {patch['id']} operation")
    operation_id = _assert_id(data.get("id"), f"patch {patch['id']} operation.id")
    if operation_id in seen_operation_ids:
        raise PatchError(f"重复 patch operation id:{operation_id}")
    seen_operation_ids.add(operation_id)
    operation = data.get("operation")
    if operation not in OPERATIONS:
        raise PatchError(f"patch {operation_id} operation 不支持:{operation}")
    targets = data.get("targets")
    if not isinstance(targets, list) or not targets:
        raise PatchError(f"patch {operation_id} targets 不能为空")
    selector = _normalize_selector(data.get("selector"), leaf_dir, operation_id)
    required = data.get("required")
    if required is None:
        required = patch.get("required")
    if required is None:
        required = True
    if not isinstance(required, bool):
        raise PatchError(f"patch {operation_id} required 必须是布尔值")
    target_policy = data.get("targetPolicy", "each-existing")
    if target_policy not in TARGET_POLICIES:
        raise PatchError(f"patch {operation_id} targetPolicy 不支持:{target_policy}")
    content: Any = ""
    if operation == "remove":
        if "content" in data:
            raise PatchError(f"patch {operation_id} remove 不能声明 content")
    else:
        content = _read_content(leaf_dir, data.get("content"), f"patch {operation_id} content")
    position = data.get("position")
    if operation == "insert" and position not in {"before", "after"}:
        raise PatchError(f"patch {operation_id} insert position 必须是 before 或 after")
    return {
        "id": operation_id,
        "patch_id": patch["id"],
        "purpose": patch["purpose"],
        "operation": operation,
        "required": required,
        "target_policy": target_policy,
        "targets": [
            _normalize_target(item, operation_id, index) for index, item in enumerate(targets)
        ],
        "selector": selector,
        "selector_text": selector.get("text"),
        "expected_matches": selector["expectedMatches"],
        "content": re.sub(r"\s+$", "", content) if isinstance(content, str) else content,
        "position": position,
        "scope": data.get("scope"),
        "legacy_markers": _normalize_legacy_markers(
            data.get("legacyMarkers"), f"patch {operation_id} legacyMarkers"
        ),
        "cleanup": _normalize_cleanup(data.get("cleanup"), f"patch {operation_id} cleanup"),
        "baselines": _normalize_baselines(
            data.get("baselines"), leaf_dir, f"patch {operation_id} baselines"
        ),
    }


def _load_catalog(
    overrides_dir: Path,
    skills: list[str],
) -> tuple[list[str], list[dict[str, Any]], list[Path]]:
    patches_dir = overrides_dir / "patches"
    bundles_dir = overrides_dir / "bundles"
    patch_by_ref: dict[str, dict[str, Any]] = {}
    catalog_files: list[Path] = []
    seen_patch_ids: set[str] = set()
    seen_operation_ids: set[str] = set()
    for file in sorted(patches_dir.rglob("patch.json")):
        if file.is_symlink():
            continue
        leaf_dir = file.parent
        ref = leaf_dir.relative_to(patches_dir).as_posix()
        raw = _assert_object(json.loads(file.read_text(encoding="utf-8")), f"patch {ref}")
        if raw.get("schemaVersion") != PATCH_SCHEMA_VERSION:
            raise PatchError(f"patch {ref} schemaVersion 不支持:{raw.get('schemaVersion')}")
        patch_id = _assert_id(raw.get("id"), f"patch {ref} id")
        if patch_id in seen_patch_ids:
            raise PatchError(f"重复 patch id:{patch_id}")
        seen_patch_ids.add(patch_id)
        purpose = raw.get("purpose")
        if not isinstance(purpose, str) or not purpose:
            raise PatchError(f"patch {ref} purpose 必须是非空字符串")
        raw_operations = raw.get("operations")
        if not isinstance(raw_operations, list) or not raw_operations:
            raise PatchError(f"patch {ref} operations 不能为空")
        patch = {
            "id": patch_id,
            "ref": ref,
            "purpose": purpose,
            "required": raw.get("required"),
            "operations": [],
        }
        patch["operations"] = [
            _normalize_operation(item, leaf_dir, patch, seen_operation_ids)
            for item in raw_operations
        ]
        patch_by_ref[ref] = patch
        catalog_files.extend(path for path in leaf_dir.rglob("*") if path.is_file())

    bundles: list[str] = []
    patches: dict[str, dict[str, Any]] = {}
    referenced: set[str] = set()
    for file in sorted(bundles_dir.rglob("*.json")):
        raw = _assert_object(json.loads(file.read_text(encoding="utf-8")), f"bundle {file.name}")
        if raw.get("schemaVersion") != BUNDLE_SCHEMA_VERSION:
            raise PatchError(
                f"bundle {file.name} schemaVersion 不支持:{raw.get('schemaVersion')}"
            )
        bundle_id = _assert_id(raw.get("id"), f"bundle {file.name} id")
        aliases = raw.get("aliases", [])
        if not isinstance(aliases, list) or not all(
            isinstance(item, str) and item for item in aliases
        ):
            raise PatchError(f"bundle {file.name} aliases 必须是字符串数组")
        install_mode = raw.get("installMode", "full-or-selected")
        if install_mode not in INSTALL_MODES:
            raise PatchError(f"bundle {file.name} installMode 不支持:{install_mode}")
        refs = raw.get("patches")
        if not isinstance(refs, list) or not refs:
            raise PatchError(f"bundle {file.name} patches 不能为空")
        selected = not skills or (
            install_mode != "full-only" and _should_install(bundle_id, skills, aliases)
        )
        for ref in refs:
            if not isinstance(ref, str) or ref not in patch_by_ref:
                raise PatchError(f"bundle {file.name} 引用未知 patch:{ref}")
            referenced.add(ref)
            if selected:
                patches[patch_by_ref[ref]["id"]] = {**patch_by_ref[ref], "bundle": bundle_id}
        if selected:
            bundles.append(bundle_id)
        catalog_files.append(file)
    for ref in patch_by_ref:
        if ref not in referenced:
            raise PatchError(f"未被 bundle 引用的 patch:{ref}")
    return bundles, list(patches.values()), sorted(set(catalog_files))


def prepare_patches(
    overrides_dir: Path,
    target_root: Path,
    skills: list[str] | None = None,
) -> dict[str, Any]:
    """预检全部 Skill-Garden Patch，并在内存中计算目标文件结果。

    Args:
        overrides_dir: 包含 patches/ 与 bundles/ 的 0.6 overrides 目录。
        target_root: 目标 Trellis 项目根目录。
        skills: 可选精细安装过滤名。

    Returns:
        包含 bundles、patches、files、results 与 catalogHash 的预检计划。

    Raises:
        PatchError: schema、selector、路径或 required Patch 无法安全应用。
    """
    overrides_dir = overrides_dir.resolve(strict=True)
    target_root = target_root.resolve(strict=True)
    bundles, patches, catalog_files = _load_catalog(overrides_dir, skills or [])
    files: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for patch in patches:
        for operation in patch["operations"]:
            ready_targets = 0
            existing_targets = 0
            for target_spec in operation["targets"]:
                target_path = target_spec["path"]
                try:
                    missing_requirement = any(
                        not _resolve_relative(
                            target_root,
                            required_path,
                            f"patch {operation['id']} target.requires",
                        ).exists()
                        for required_path in target_spec["requires"]
                    )
                    if missing_requirement:
                        results.append(
                            {
                                "id": operation["id"],
                                "patch": patch["id"],
                                "bundle": patch["bundle"],
                                "target": target_path,
                                "status": "missing-target",
                                "required": operation["required"],
                            }
                        )
                        continue
                    target_file = _resolve_relative(
                        target_root, target_path, f"patch {operation['id']} target.path"
                    )
                    exists = target_file.exists()
                    if not exists:
                        if target_spec["missing"] == "skip":
                            results.append(
                                {
                                    "id": operation["id"],
                                    "patch": patch["id"],
                                    "bundle": patch["bundle"],
                                    "target": target_path,
                                    "status": "missing-target",
                                    "required": operation["required"],
                                }
                            )
                            continue
                        if target_spec["missing"] == "error":
                            raise PatchError("目标不存在")
                        if not target_file.parent.is_dir():
                            results.append(
                                {
                                    "id": operation["id"],
                                    "patch": patch["id"],
                                    "bundle": patch["bundle"],
                                    "target": target_path,
                                    "status": "missing-target",
                                    "required": operation["required"],
                                }
                            )
                            continue
                        _assert_existing_inside(
                            target_root,
                            target_file.parent,
                            f"patch {operation['id']} target.parent",
                        )
                    else:
                        _assert_existing_inside(
                            target_root, target_file, f"patch {operation['id']} target"
                        )
                    existing_targets += 1
                    file_plan = files.get(target_path)
                    if file_plan is None:
                        original = target_file.read_text(encoding="utf-8") if exists else None
                        file_plan = {
                            "target": target_path,
                            "target_file": target_file,
                            "original": original,
                            "original_exists": exists,
                            "next": original or "",
                            "operations": [],
                            "patches": [],
                            "bundles": [],
                        }
                        files[target_path] = file_plan
                    cleaned, cleanup_changed = _apply_cleanup(
                        file_plan["next"], operation["cleanup"]
                    )
                    operation_for_target = {
                        **operation,
                        "marker_style": target_spec["marker_style"],
                    }
                    next_value, source = _apply_operation(cleaned, operation_for_target)
                    file_plan["next"] = next_value
                    file_plan["operations"].append(operation["id"])
                    file_plan["patches"].append(patch["id"])
                    file_plan["bundles"].append(patch["bundle"])
                    ready_targets += 1
                    results.append(
                        {
                            "id": operation["id"],
                            "patch": patch["id"],
                            "bundle": patch["bundle"],
                            "target": target_path,
                            "status": "ready",
                            "required": operation["required"],
                            "source": "legacy-cleanup"
                            if cleanup_changed and source == "selector"
                            else source,
                        }
                    )
                except PatchError as error:
                    result = {
                        "id": operation["id"],
                        "patch": patch["id"],
                        "bundle": patch["bundle"],
                        "target": target_path,
                        "status": "error" if operation["required"] else "optional-skip",
                        "required": operation["required"],
                        "reason": str(error),
                    }
                    results.append(result)
                    if operation["required"]:
                        errors.append(result)
            if operation["required"] and operation["target_policy"] == "at-least-one" and not ready_targets:
                errors.append(
                    {
                        "id": operation["id"],
                        "target": "<target-group>",
                        "reason": "at-least-one target 未命中",
                    }
                )
            if (
                operation["required"]
                and operation["target_policy"] == "required-all"
                and existing_targets != len(operation["targets"])
            ):
                errors.append(
                    {
                        "id": operation["id"],
                        "target": "<target-group>",
                        "reason": "required-all target 不完整",
                    }
                )
    if errors:
        detail = "; ".join(
            f"{item['id']}@{item['target']}:{item['reason']}" for item in errors
        )
        raise PatchError(f"Patch 预检失败:{detail}")

    for file_plan in files.values():
        if file_plan["operations"]:
            file_plan["next"] = _normalize_text(file_plan["next"])
        file_plan["changed"] = (
            file_plan["next"] != file_plan["original"]
            if file_plan["original_exists"]
            else bool(file_plan["operations"])
        )
        file_plan["before_hash"] = (
            _sha256(file_plan["original"]) if file_plan["original_exists"] else None
        )
        file_plan["after_hash"] = _sha256(file_plan["next"])
    catalog_hash = _sha256(
        "\0".join(
            f"{file.relative_to(overrides_dir).as_posix()}\0{file.read_text(encoding='utf-8')}"
            for file in catalog_files
        )
    )
    return {
        "bundles": bundles,
        "patches": [patch["id"] for patch in patches],
        "files": list(files.values()),
        "results": results,
        "catalogHash": catalog_hash,
    }


def _preserve_first_backup(target_root: Path, target_file: Path) -> tuple[Path, bool]:
    relative = target_file.relative_to(target_root)
    backup = target_root / ".trellis/.backup-flower" / relative
    if backup.exists():
        _assert_existing_inside(target_root, backup, "已有 Patch backup")
        return backup, False
    existing = backup.parent
    while not existing.exists() and existing != target_root:
        existing = existing.parent
    _assert_existing_inside(target_root, existing, "Patch backup parent")
    backup.parent.mkdir(parents=True, exist_ok=True)
    _assert_existing_inside(target_root, backup.parent, "Patch backup parent")
    shutil.copy2(target_file, backup)
    return backup, True


def apply_prepared(target_root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """应用已通过预检的 Patch 计划，并保留首次备份。

    Args:
        target_root: 目标 Trellis 项目根目录。
        plan: `prepare_patches` 返回的计划。

    Returns:
        changed、unchanged、skipped、targets、backupNotes 和 provenance 汇总。

    Raises:
        PatchError: 预检后目标发生存在性或内容漂移。
    """
    target_root = target_root.resolve(strict=True)
    for file_plan in plan["files"]:
        exists = file_plan["target_file"].exists()
        if exists != file_plan["original_exists"]:
            raise PatchError(f"Patch 目标在应用前发生存在性漂移:{file_plan['target']}")
        if exists and file_plan["target_file"].read_text(encoding="utf-8") != file_plan["original"]:
            raise PatchError(f"Patch 目标在应用前发生内容漂移:{file_plan['target']}")
        if not exists:
            parent = file_plan["target_file"].parent
            if not parent.is_dir():
                raise PatchError(
                    f"Patch 目标父目录在应用前发生存在性漂移:{file_plan['target']}"
                )
            _assert_existing_inside(
                target_root,
                parent,
                f"Patch 目标父目录:{file_plan['target']}",
            )

    changed = 0
    unchanged = 0
    backup_notes: list[str] = []
    for file_plan in plan["files"]:
        if not file_plan["changed"]:
            unchanged += 1
            continue
        if file_plan["original_exists"]:
            backup, created = _preserve_first_backup(target_root, file_plan["target_file"])
            note = f"{'已创建' if created else '保留已有'} {backup.relative_to(target_root).as_posix()}"
            if note not in backup_notes:
                backup_notes.append(note)
        else:
            file_plan["target_file"].parent.mkdir(parents=True, exist_ok=True)
        file_plan["target_file"].write_text(file_plan["next"], encoding="utf-8")
        changed += 1
    provenance = {
        "schemaVersion": 1,
        "catalogHash": plan["catalogHash"],
        "applied": [
            {
                "id": operation_id,
                "patch": file_plan["patches"][index],
                "bundle": file_plan["bundles"][index],
                "target": file_plan["target"],
                "status": "applied",
                "resultHash": file_plan["after_hash"],
            }
            for file_plan in plan["files"]
            for index, operation_id in enumerate(file_plan["operations"])
        ],
    }
    return {
        "changed": changed,
        "unchanged": unchanged,
        "skipped": sum(
            item["status"] in {"missing-target", "optional-skip"}
            for item in plan["results"]
        ),
        "targets": [item["target"] for item in plan["files"]],
        "backupNotes": backup_notes,
        "results": plan["results"],
        "provenance": provenance,
    }


def main(argv: list[str] | None = None) -> int:
    """解析独立安装参数并执行 Skill-Garden Patch。

    Args:
        argv: 不含程序名的参数；默认读取 `sys.argv[1:]`。

    Returns:
        成功返回 0，Patch/文件错误返回 1，参数错误返回 2。
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print(
            "用法: apply-trellis-patches.py <overrides-dir> <target-project> [skill-name...]",
            file=sys.stderr,
        )
        return 2
    try:
        plan = prepare_patches(Path(args[0]), Path(args[1]), args[2:])
        result = apply_prepared(Path(args[1]), plan)
    except (OSError, UnicodeError, json.JSONDecodeError, PatchError) as error:
        print(f"❌ {error}", file=sys.stderr)
        return 1
    print(
        "  ✓ Patch "
        f"changed={result['changed']} unchanged={result['unchanged']} "
        f"skipped={result['skipped']}"
    )
    for item in result["results"]:
        if item["status"] == "optional-skip":
            print(
                "  · optional Patch 跳过:"
                f"{item['id']}@{item['target']}({item['reason']})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
