#!/usr/bin/env python3
"""为 skill-garden 独立安装器应用 Trellis Patch catalog。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


PATCH_SCHEMA_VERSION = 2
BUNDLE_SCHEMA_VERSION = 1
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LEGACY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")
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
SEVERITIES = {"error", "warning", "info"}
ASSERTION_TYPES = {"absent-literal", "required-literal", "max-occurrences"}
CATALOG_ID = "skill-garden"
TARGET_EVIDENCE_FILES = (
    ".codex/hooks.json",
    ".claude/settings.json",
    ".trellis/workflow.md",
)
GENERATED_COMMAND_RE = re.compile(
    r"(?:^|[\s`\"'([{])(py -3|python3|python)"
    r"(?=\s+(?:-X\s+utf8\s+)?(?:\./)?(?:\.trellis/scripts|\.codex/hooks|\.claude/hooks)/)",
    re.MULTILINE,
)


class PatchError(RuntimeError):
    """表示 Patch 声明、预检或应用阶段无法安全继续。"""


def _normalize_python_command(value: Any, label: str) -> str:
    """校验可用于文本物化的 Python 命令。

    Args:
        value: 待校验命令。
        label: 错误字段说明。

    Returns:
        去除首尾空白后的命令。

    Raises:
        PatchError: 命令为空或包含换行、NUL。
    """
    if not isinstance(value, str) or not value.strip():
        raise PatchError(f"{label} 必须是非空字符串")
    command = value.strip()
    if "\0" in command or "\r" in command or "\n" in command:
        raise PatchError(f"{label} 不能包含换行或 NUL")
    return command


def _resolve_trellis_python_command(target_root: Path) -> str:
    """从目标项目证据、环境和平台解析 Trellis Python 命令。

    Args:
        target_root: 目标 Trellis 项目根目录。

    Returns:
        目标项目实际使用的 Python 命令。
    """
    for relative in TARGET_EVIDENCE_FILES:
        file = target_root / PurePosixPath(relative)
        if not file.is_file():
            continue
        try:
            value = file.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        match = GENERATED_COMMAND_RE.search(value)
        if match:
            return match.group(1)
    if "TRELLIS_PYTHON_CMD" in os.environ:
        return _normalize_python_command(
            os.environ["TRELLIS_PYTHON_CMD"], "TRELLIS_PYTHON_CMD"
        )
    return "python" if sys.platform == "win32" else "python3"


def _materialize_trellis_python_text(value: str, command: str) -> str:
    """按 Trellis 模板规则物化 canonical `python3` 文本。

    Args:
        value: canonical Trellis 文本。
        command: 目标项目 Python 命令。

    Returns:
        已物化文本。
    """
    normalized_command = _normalize_python_command(command, "Trellis Python 命令")
    if normalized_command == "python3":
        return value
    return "\n".join(
        line if line.startswith("#!") else line.replace("python3", normalized_command)
        for line in value.split("\n")
    )


def _read_json(file: Path, label: str) -> dict[str, Any]:
    try:
        return _assert_object(json.loads(file.read_text(encoding="utf-8")), label)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PatchError(f"{label} 无法读取:{error}") from error


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise PatchError(f"{label} 必须是非空字符串")
    return value


def _require_string_array(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise PatchError(f"{label} 必须是非空字符串数组")
    return [_require_string(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _validate_compatibility(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("schemaVersion") != 1:
        raise PatchError("compatibility schemaVersion 必须为 1")
    variant = _require_string(raw.get("variant"), "compatibility.variant")
    line = raw.get("compatibleLine")
    if (
        not isinstance(line, dict)
        or not isinstance(line.get("major"), int)
        or isinstance(line.get("major"), bool)
        or line["major"] < 0
        or not isinstance(line.get("minor"), int)
        or isinstance(line.get("minor"), bool)
        or line["minor"] < 0
    ):
        raise PatchError("compatibility.compatibleLine 必须包含非负整数 major/minor")
    if variant != f"{line['major']}.{line['minor']}":
        raise PatchError("compatibility.variant 必须匹配 compatibleLine")
    tested_versions = _require_string_array(
        raw.get("testedVersions"),
        "compatibility.testedVersions",
    )
    if len(set(tested_versions)) != len(tested_versions):
        raise PatchError("compatibility.testedVersions 不能重复")
    for index, version in enumerate(tested_versions):
        if not SEMVER_RE.fullmatch(version):
            raise PatchError(
                f"compatibility.testedVersions[{index}] 必须是完整 semver"
            )
    if raw.get("untestedPatchPolicy") != "warning":
        raise PatchError("compatibility.untestedPatchPolicy 当前只允许 warning")
    if raw.get("newLinePolicy") != "error":
        raise PatchError("compatibility.newLinePolicy 当前只允许 error")
    return raw


def _validate_conflict_target(value: Any, label: str) -> str:
    target = _require_string(value, label)
    posix = PurePosixPath(target)
    windows = PureWindowsPath(target)
    if "\\" in target or posix.is_absolute() or windows.is_absolute() or windows.drive:
        raise PatchError(f"{label} 必须是项目内 POSIX 相对路径")
    if any(part in {"", ".", ".."} for part in target.split("/")):
        raise PatchError(f"{label} 包含不安全路径片段")
    return target


def _validate_assertion(raw: Any, label: str) -> dict[str, Any]:
    assertion = _assert_object(raw, label)
    assertion_type = assertion.get("type")
    if assertion_type not in ASSERTION_TYPES:
        raise PatchError(f"{label}.type 非法:{assertion_type}")
    if assertion_type == "max-occurrences":
        _require_string(assertion.get("value"), f"{label}.value")
        maximum = assertion.get("max")
        if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0:
            raise PatchError(f"{label}.max 必须是非负整数")
    else:
        _require_string_array(assertion.get("values"), f"{label}.values")
    return assertion


def _validate_conflicts(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("schemaVersion") != 1:
        raise PatchError("conflicts schemaVersion 必须为 1")
    rules = raw.get("rules")
    if not isinstance(rules, list):
        raise PatchError("conflicts.rules 必须是数组")
    seen: set[str] = set()
    for index, rule_value in enumerate(rules):
        label = f"conflicts.rules[{index}]"
        rule = _assert_object(rule_value, label)
        rule_id = _assert_id(rule.get("id"), f"{label}.id")
        if rule_id in seen:
            raise PatchError(f"conflict rule id 重复:{rule_id}")
        seen.add(rule_id)
        if rule.get("severity") not in SEVERITIES:
            raise PatchError(f"{label}.severity 非法:{rule.get('severity')}")
        _validate_conflict_target(rule.get("target"), f"{label}.target")
        operation_ids = _require_string_array(
            rule.get("whenOperations"),
            f"{label}.whenOperations",
        )
        for operation_index, operation_id in enumerate(operation_ids):
            _assert_operation_ref(
                operation_id,
                f"{label}.whenOperations[{operation_index}]",
            )
        _validate_assertion(rule.get("assertion"), f"{label}.assertion")
        _require_string(rule.get("owner"), f"{label}.owner")
        _require_string(rule.get("reason"), f"{label}.reason")
    return raw


def _materialize_conflict_assertions(
    conflicts: dict[str, Any], command: str
) -> dict[str, Any]:
    """物化冲突策略中的命令 literal，保持其它声明不变。

    Args:
        conflicts: 已校验 conflicts policy。
        command: 目标项目 Python 命令。

    Returns:
        assertion literal 已物化的新 conflicts policy。
    """
    rules = []
    for rule in conflicts["rules"]:
        assertion = rule["assertion"]
        if assertion["type"] == "max-occurrences":
            materialized_assertion = {
                **assertion,
                "value": _materialize_trellis_python_text(assertion["value"], command),
            }
        else:
            materialized_assertion = {
                **assertion,
                "values": [
                    _materialize_trellis_python_text(value, command)
                    for value in assertion["values"]
                ],
            }
        rules.append({**rule, "assertion": materialized_assertion})
    return {**conflicts, "rules": rules}


def load_patch_policy(
    overrides_dir: Path, python_command: str = "python3"
) -> dict[str, Any]:
    """读取并校验共享版本兼容与最终产物冲突声明。

    Args:
        overrides_dir: 包含 compatibility.json 与 conflicts.json 的目录。
        python_command: 目标项目 Python 命令；默认保持 canonical `python3`。

    Returns:
        已校验且按目标命令物化的 compatibility 与 conflicts 对象。

    Raises:
        PatchError: policy 缺失、JSON 非法或声明不满足协议。
    """
    root = overrides_dir.resolve(strict=True)
    return {
        "catalog": CATALOG_ID,
        "compatibility": _validate_compatibility(
            _read_json(root / "compatibility.json", "compatibility policy")
        ),
        "conflicts": _materialize_conflict_assertions(
            _validate_conflicts(_read_json(root / "conflicts.json", "conflict policy")),
            python_command,
        ),
    }


def _parse_version(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    match = SEMVER_RE.fullmatch(value)
    if not match:
        return None
    return {
        "value": value,
        "major": int(match.group(1)),
        "minor": int(match.group(2)),
        "patch": int(match.group(3)),
        "prerelease": match.group(4),
    }


def _diagnostic(
    diagnostic_id: str,
    severity: str,
    target: str,
    owner: str,
    reason: str,
    evidence: list[str],
    catalog: str = CATALOG_ID,
) -> dict[str, Any]:
    return {
        "id": diagnostic_id,
        "catalog": catalog,
        "qualifiedId": _qualify_id(catalog, diagnostic_id),
        "severity": severity,
        "target": target,
        "owner": owner,
        "reason": reason,
        "evidence": evidence,
    }


def _summarize(diagnostics: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"errors": 0, "warnings": 0, "info": 0}
    for item in diagnostics:
        if item["severity"] == "error":
            summary["errors"] += 1
        elif item["severity"] == "warning":
            summary["warnings"] += 1
        else:
            summary["info"] += 1
    return summary


def evaluate_patch_compatibility(
    version: str,
    compatibility: dict[str, Any],
    catalog: str = CATALOG_ID,
) -> dict[str, Any]:
    """按登记版本与兼容线评估目标 Trellis 版本。

    Args:
        version: 目标项目 `.trellis/.version` 的去空白值。
        compatibility: 已校验的 compatibility policy。

    Returns:
        version status 与结构化 diagnostics。
    """
    parsed = _parse_version(version)
    if parsed is None:
        return {
            "version": {"value": version or "", "status": "invalid"},
            "diagnostics": [
                _diagnostic(
                    "invalid-upstream-version",
                    "error",
                    ".trellis/.version",
                    "patch-compatibility",
                    "0.6 Patch 需要可解析的 Trellis semver 版本。",
                    [version or "<empty>"],
                    catalog,
                )
            ],
        }
    if parsed["value"] in compatibility["testedVersions"]:
        return {
            "version": {"value": parsed["value"], "status": "tested"},
            "diagnostics": [],
        }
    line = compatibility["compatibleLine"]
    if parsed["major"] == line["major"] and parsed["minor"] == line["minor"]:
        return {
            "version": {
                "value": parsed["value"],
                "status": "untested-compatible",
            },
            "diagnostics": [
                _diagnostic(
                    "untested-upstream",
                    "warning",
                    ".trellis/.version",
                    "patch-compatibility",
                    "目标版本位于兼容线内但尚未登记 baseline；只有完整预检和冲突断言通过后才允许继续。",
                    [parsed["value"]],
                    catalog,
                )
            ],
        }
    return {
        "version": {"value": parsed["value"], "status": "unsupported"},
        "diagnostics": [
            _diagnostic(
                "unsupported-upstream-line",
                "error",
                ".trellis/.version",
                "patch-compatibility",
                "该 Trellis minor/major 尚无受支持 Patch baseline；请使用匹配的 Flower 版本或 --no-enhance。",
                [parsed["value"]],
                catalog,
            )
        ],
    }


def evaluate_patch_conflicts(
    plan: dict[str, Any],
    conflicts: dict[str, Any],
    catalog: str = CATALOG_ID,
) -> dict[str, Any]:
    """对 Patch 计划中的最终内存文件执行确定性冲突断言。

    Args:
        plan: `prepare_patches` 返回的完整计划。
        conflicts: 已校验的 conflicts policy。

    Returns:
        只包含本次已选 operation 的结构化 diagnostics。
    """
    def resolve_operation_id(operation_id: str) -> str:
        return operation_id if "/" in operation_id else _qualify_id(catalog, operation_id)

    catalog_operations = plan.get("catalogOperations")
    if isinstance(catalog_operations, list):
        operation_targets = {
            operation.get("qualifiedId")
            or _qualify_id(operation.get("catalog", catalog), operation["id"]): set(
                operation["targets"]
            )
            for operation in catalog_operations
        }
        for rule in conflicts["rules"]:
            for operation_id in rule["whenOperations"]:
                qualified_operation_id = resolve_operation_id(operation_id)
                targets = operation_targets.get(qualified_operation_id)
                if targets is None:
                    raise PatchError(
                        f"conflict rule {_qualify_id(catalog, rule['id'])} "
                        f"引用未知 operation:{operation_id}"
                    )
                if rule["target"] not in targets:
                    raise PatchError(
                        f"conflict rule {_qualify_id(catalog, rule['id'])} "
                        f"target 未被 operation {qualified_operation_id} 修改:{rule['target']}"
                    )
    selected_operations = {
        entry.get("qualifiedId") or _qualify_id(catalog, entry["id"])
        for file_plan in plan["files"]
        for entry in file_plan.get(
            "operation_entries",
            [{"id": operation_id} for operation_id in file_plan["operations"]],
        )
    }
    files = {file_plan["target"]: file_plan["next"] for file_plan in plan["files"]}
    diagnostics: list[dict[str, Any]] = []
    for rule in conflicts["rules"]:
        if not all(
            resolve_operation_id(item) in selected_operations
            for item in rule["whenOperations"]
        ):
            continue
        value = files.get(rule["target"])
        if not isinstance(value, str):
            continue
        assertion = rule["assertion"]
        evidence: list[str] = []
        if assertion["type"] == "absent-literal":
            evidence.extend(
                f"仍存在:{literal}"
                for literal in assertion["values"]
                if literal in value
            )
        elif assertion["type"] == "required-literal":
            evidence.extend(
                f"缺少:{literal}"
                for literal in assertion["values"]
                if literal not in value
            )
        else:
            count = value.count(assertion["value"])
            if count > assertion["max"]:
                evidence.append(
                    f"出现 {count} 次，允许最多 {assertion['max']} 次:{assertion['value']}"
                )
        if evidence:
            diagnostics.append(
                _diagnostic(
                    rule["id"],
                    rule["severity"],
                    rule["target"],
                    rule["owner"],
                    rule["reason"],
                    evidence,
                    catalog,
                )
            )
    for item in plan["results"]:
        if item["status"] == "missing-target":
            diagnostics.append(
                _diagnostic(
                    f"missing-target:{item['id']}:{item['target']}",
                    "info",
                    item["target"],
                    item["patch"],
                    "目标平台入口未安装，按声明跳过。",
                    [item.get("qualifiedId", item["id"])],
                    item.get("catalog", catalog),
                )
            )
        elif item["status"] == "optional-skip":
            diagnostics.append(
                _diagnostic(
                    f"optional-skip:{item['id']}:{item['target']}",
                    "warning",
                    item["target"],
                    item["patch"],
                    "可选 Patch 未应用，需要评审其漂移原因。",
                    [item.get("reason", "unknown")],
                    item.get("catalog", catalog),
                )
            )
    return {"diagnostics": diagnostics}


def build_patch_conflict_report(
    version: str,
    plan: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """合并版本与最终产物诊断并生成稳定排序报告。

    Args:
        version: 目标 Trellis 版本。
        plan: `prepare_patches` 返回的完整计划。
        policy: `load_patch_policy` 返回的共享 policy。

    Returns:
        包含 version、diagnostics 与 severity 汇总的报告。
    """
    catalog = policy.get("catalog", CATALOG_ID)
    compatibility = evaluate_patch_compatibility(
        version,
        policy["compatibility"],
        catalog,
    )
    conflicts = evaluate_patch_conflicts(plan, policy["conflicts"], catalog)
    severity_order = {"error": 0, "warning": 1, "info": 2}
    diagnostics = sorted(
        compatibility["diagnostics"] + conflicts["diagnostics"],
        key=lambda item: (
            severity_order[item["severity"]],
            item["qualifiedId"],
            item["target"],
        ),
    )
    return {
        "version": compatibility["version"],
        "diagnostics": diagnostics,
        "summary": _summarize(diagnostics),
    }


def assert_no_patch_conflict_errors(report: dict[str, Any]) -> None:
    """在报告含 error 时抛出聚合异常。

    Args:
        report: `build_patch_conflict_report` 返回的报告。

    Raises:
        PatchError: 报告至少包含一个 error diagnostic。
    """
    errors = [item for item in report["diagnostics"] if item["severity"] == "error"]
    if not errors:
        return
    detail = "; ".join(
        f"{item.get('qualifiedId', item['id'])}@{item['target']}:{item['reason']}"
        for item in errors
    )
    error = PatchError(f"Patch 冲突检查失败:{detail}")
    error.patch_conflict_report = report
    raise error


def format_patch_diagnostic(diagnostic: dict[str, Any]) -> str:
    """格式化包含规则、目标、原因和证据的 Patch diagnostic。

    Args:
        diagnostic: 冲突报告中的单条 diagnostic。

    Returns:
        可直接输出到 CLI 的稳定文本。
    """
    labels = {"error": "错误", "warning": "警告", "info": "信息"}
    evidence = " | ".join(diagnostic["evidence"]) or "<none>"
    return (
        f"Patch {labels.get(diagnostic['severity'], diagnostic['severity'])}:"
        f"{diagnostic.get('qualifiedId', diagnostic['id'])}@{diagnostic['target']}"
        f"({diagnostic['reason']};证据:{evidence})"
    )


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


def _assert_operation_ref(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise PatchError(f"{label} 必须是 operation ID")
    parts = value.split("/")
    if len(parts) not in {1, 2} or any(not ID_RE.fullmatch(part) for part in parts):
        raise PatchError(f"{label} 必须是 local ID 或 <catalog-id>/<operation-id>")
    return value


def _qualify_id(catalog_id: str, local_id: str) -> str:
    return f"{catalog_id}/{local_id}"


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
            "id": operation["marker_id"],
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
                "id": operation["marker_id"],
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
        operation["marker_id"],
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
    after = data.get("after", [])
    depends_on = data.get("dependsOn", [])
    if not isinstance(after, list):
        raise PatchError(f"patch {operation_id} after 必须是字符串数组")
    if not isinstance(depends_on, list):
        raise PatchError(f"patch {operation_id} dependsOn 必须是字符串数组")
    after = [
        _assert_operation_ref(item, f"patch {operation_id} after[{index}]")
        for index, item in enumerate(after)
    ]
    depends_on = [
        _assert_operation_ref(item, f"patch {operation_id} dependsOn[{index}]")
        for index, item in enumerate(depends_on)
    ]
    qualified_after = [
        item if "/" in item else _qualify_id(CATALOG_ID, item) for item in after
    ]
    qualified_depends_on = [
        item if "/" in item else _qualify_id(CATALOG_ID, item) for item in depends_on
    ]
    if len(set(qualified_after)) != len(qualified_after):
        raise PatchError(f"patch {operation_id} after 不能重复")
    if len(set(qualified_depends_on)) != len(qualified_depends_on):
        raise PatchError(f"patch {operation_id} dependsOn 不能重复")
    depends_on_ids = set(qualified_depends_on)
    duplicated_relation = next(
        (item for item, qualified in zip(after, qualified_after) if qualified in depends_on_ids),
        None,
    )
    if duplicated_relation:
        raise PatchError(
            f"patch {operation_id} 同一依赖不能同时声明 after 和 dependsOn:{duplicated_relation}"
        )
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
        "catalog": CATALOG_ID,
        "qualified_id": _qualify_id(CATALOG_ID, operation_id),
        "marker_id": operation_id,
        "patch_id": patch["id"],
        "qualified_patch_id": patch["qualified_id"],
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
        "after_refs": after,
        "depends_on_refs": depends_on,
    }


def _materialize_operation_python_command(
    operation: dict[str, Any], command: str
) -> dict[str, Any]:
    """物化一个已规范化 operation 的 Python 命令文本。

    Args:
        operation: 已规范化 Patch operation。
        command: 目标项目 Python 命令。

    Returns:
        仅 selector、content 与 baselines 被物化的新 operation。
    """
    materialized = {**operation, "selector": {**operation["selector"]}}
    selector_text = materialized.get("selector_text")
    if isinstance(selector_text, str):
        selector_text = _materialize_trellis_python_text(selector_text, command)
        materialized["selector_text"] = selector_text
        if isinstance(materialized["selector"].get("text"), str):
            materialized["selector"]["text"] = selector_text
    if isinstance(materialized.get("content"), str):
        materialized["content"] = _materialize_trellis_python_text(
            materialized["content"], command
        )
    materialized["baselines"] = [
        _materialize_trellis_python_text(baseline, command)
        for baseline in materialized["baselines"]
    ]
    return materialized


def _load_catalog(
    overrides_dir: Path,
    skills: list[str],
    python_command: str,
) -> dict[str, Any]:
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
            "catalog": CATALOG_ID,
            "qualified_id": _qualify_id(CATALOG_ID, patch_id),
            "ref": ref,
            "purpose": purpose,
            "required": raw.get("required"),
            "operations": [],
        }
        patch["operations"] = [
            _materialize_operation_python_command(
                _normalize_operation(item, leaf_dir, patch, seen_operation_ids),
                python_command,
            )
            for item in raw_operations
        ]
        patch_by_ref[ref] = patch
        catalog_files.extend(path for path in leaf_dir.rglob("*") if path.is_file())

    bundles: list[str] = []
    selected_bundles: list[dict[str, Any]] = []
    patches: dict[str, dict[str, Any]] = {}
    memberships: dict[str, list[dict[str, Any]]] = {}
    referenced: set[str] = set()
    seen_bundle_ids: set[str] = set()
    for file in sorted(bundles_dir.rglob("*.json")):
        raw = _assert_object(json.loads(file.read_text(encoding="utf-8")), f"bundle {file.name}")
        if raw.get("schemaVersion") != BUNDLE_SCHEMA_VERSION:
            raise PatchError(
                f"bundle {file.name} schemaVersion 不支持:{raw.get('schemaVersion')}"
            )
        bundle_id = _assert_id(raw.get("id"), f"bundle {file.name} id")
        if bundle_id in seen_bundle_ids:
            raise PatchError(f"重复 bundle id:{bundle_id}")
        seen_bundle_ids.add(bundle_id)
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
        selected_patches: list[dict[str, Any]] = []
        for ref in refs:
            if not isinstance(ref, str) or ref not in patch_by_ref:
                raise PatchError(f"bundle {file.name} 引用未知 patch:{ref}")
            referenced.add(ref)
            if selected:
                selected_patches.append(patch_by_ref[ref])
        if selected:
            bundles.append(bundle_id)
            bundle = {
                "id": bundle_id,
                "catalog": CATALOG_ID,
                "qualifiedId": _qualify_id(CATALOG_ID, bundle_id),
                "patches": selected_patches,
            }
            selected_bundles.append(bundle)
            for patch in selected_patches:
                patches.setdefault(patch["id"], patch)
                memberships.setdefault(patch["id"], []).append(bundle)
        catalog_files.append(file)
    for ref in patch_by_ref:
        if ref not in referenced:
            raise PatchError(f"未被 bundle 引用的 patch:{ref}")
    for policy_name in ("compatibility.json", "conflicts.json"):
        policy_file = overrides_dir / policy_name
        if policy_file.is_file():
            catalog_files.append(policy_file)
    selected_patch_list = []
    for patch in patches.values():
        patch_memberships = memberships.get(patch["id"], [])
        selected_patch_list.append(
            {
                **patch,
                "bundle": patch_memberships[0]["id"] if patch_memberships else None,
                "bundle_ids": [item["id"] for item in patch_memberships],
                "bundles": [item["qualifiedId"] for item in patch_memberships],
            }
        )
    return {
        "bundles": bundles,
        "selected_bundles": selected_bundles,
        "patches": selected_patch_list,
        "all_patches": list(patch_by_ref.values()),
        "catalog_files": sorted(set(catalog_files)),
    }


def _resolve_operation_ref(
    ref: str,
    operation: dict[str, Any],
    operation_by_id: dict[str, dict[str, Any]],
) -> str:
    qualified_id = ref if "/" in ref else _qualify_id(operation["catalog"], ref)
    if qualified_id not in operation_by_id:
        raise PatchError(
            f"patch operation {operation['qualified_id']} 引用未知 operation:{ref}"
        )
    if qualified_id == operation["qualified_id"]:
        raise PatchError(f"patch operation {operation['qualified_id']} 不能依赖自身")
    return qualified_id


def _stable_topological_sort(
    operations: list[dict[str, Any]],
    include_edge: Any,
) -> list[dict[str, Any]]:
    base_index = {item["qualified_id"]: index for index, item in enumerate(operations)}
    operation_by_id = {item["qualified_id"]: item for item in operations}
    outgoing = {item["qualified_id"]: set() for item in operations}
    indegree = {item["qualified_id"]: 0 for item in operations}
    for operation in operations:
        relations = [
            *[(item, "after") for item in operation["after"]],
            *[(item, "dependsOn") for item in operation["depends_on"]],
        ]
        for source, relation_type in relations:
            if source not in operation_by_id or not include_edge(operation, source, relation_type):
                continue
            if operation["qualified_id"] in outgoing[source]:
                continue
            outgoing[source].add(operation["qualified_id"])
            indegree[operation["qualified_id"]] += 1
    ready = sorted(
        [item for item in operations if indegree[item["qualified_id"]] == 0],
        key=lambda item: base_index[item["qualified_id"]],
    )
    resolved: list[dict[str, Any]] = []
    while ready:
        operation = ready.pop(0)
        resolved.append(operation)
        for target_id in sorted(outgoing[operation["qualified_id"]], key=base_index.get):
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                ready.append(operation_by_id[target_id])
                ready.sort(key=lambda item: base_index[item["qualified_id"]])
    if len(resolved) != len(operations):
        cycle = [
            item["qualified_id"]
            for item in operations
            if indegree[item["qualified_id"]] > 0
        ]
        raise PatchError(f"Patch operation 依赖循环:{' -> '.join(cycle)}")
    return resolved


def _resolve_operation_order(catalog: dict[str, Any]) -> dict[str, Any]:
    all_operations = [
        operation
        for patch in catalog["all_patches"]
        for operation in patch["operations"]
    ]
    operation_by_id = {item["qualified_id"]: item for item in all_operations}
    if len(operation_by_id) != len(all_operations):
        raise PatchError("重复 qualified patch operation id")
    for operation in all_operations:
        operation["after"] = [
            _resolve_operation_ref(item, operation, operation_by_id)
            for item in operation["after_refs"]
        ]
        operation["depends_on"] = [
            _resolve_operation_ref(item, operation, operation_by_id)
            for item in operation["depends_on_refs"]
        ]
    _stable_topological_sort(all_operations, lambda _operation, _source, _type: True)

    selected_operations = [
        {
            **operation,
            "bundle": patch["bundle"],
            "bundle_ids": patch["bundle_ids"],
            "bundles": patch["bundles"],
        }
        for patch in catalog["patches"]
        for operation in patch["operations"]
    ]
    selected_ids = {item["qualified_id"] for item in selected_operations}
    for operation in selected_operations:
        for dependency in operation["depends_on"]:
            if dependency not in selected_ids:
                raise PatchError(
                    f"patch operation {operation['qualified_id']} dependsOn 未进入当前计划:{dependency}"
                )
    sorted_operations = _stable_topological_sort(
        selected_operations,
        lambda _operation, source, relation_type: (
            relation_type == "dependsOn" or source in selected_ids
        ),
    )
    declaration_index = {
        item["qualified_id"]: index for index, item in enumerate(selected_operations)
    }
    return {
        "all_operations": all_operations,
        "selected_operations": sorted_operations,
        "operation_order": [
            {
                "id": operation["id"],
                "catalog": operation["catalog"],
                "qualifiedId": operation["qualified_id"],
                "patch": operation["patch_id"],
                "qualifiedPatch": operation["qualified_patch_id"],
                "bundle": operation["bundle"],
                "bundles": operation["bundles"],
                "declarationIndex": declaration_index[operation["qualified_id"]],
                "resolvedIndex": index,
                "after": operation["after"],
                "dependsOn": operation["depends_on"],
                "incomingEdges": [
                    *[
                        {"from": source, "type": "after"}
                        for source in operation["after"]
                        if source in selected_ids
                    ],
                    *[
                        {"from": source, "type": "dependsOn"}
                        for source in operation["depends_on"]
                    ],
                ],
            }
            for index, operation in enumerate(sorted_operations)
        ],
    }


def _operation_identity(operation: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": operation["id"],
        "catalog": operation["catalog"],
        "qualifiedId": operation["qualified_id"],
        "patch": operation["patch_id"],
        "qualifiedPatch": operation["qualified_patch_id"],
        "bundle": operation["bundle"],
        "bundles": operation["bundles"],
    }


def prepare_patches(
    overrides_dir: Path,
    target_root: Path,
    skills: list[str] | None = None,
    python_command: str | None = None,
) -> dict[str, Any]:
    """预检全部 Skill-Garden Patch，并在内存中计算目标文件结果。

    Args:
        overrides_dir: 包含 patches/ 与 bundles/ 的 0.6 overrides 目录。
        target_root: 目标 Trellis 项目根目录。
        skills: 可选精细安装过滤名。
        python_command: 已解析的目标 Python 命令；省略时从目标项目解析。

    Returns:
        包含 bundles、patches、files、results、catalogHash 与 catalogOperations 的预检计划。

    Raises:
        PatchError: schema、selector、路径或 required Patch 无法安全应用。
    """
    overrides_dir = overrides_dir.resolve(strict=True)
    target_root = target_root.resolve(strict=True)
    python_command = python_command or _resolve_trellis_python_command(target_root)
    catalog = _load_catalog(overrides_dir, skills or [], python_command)
    order = _resolve_operation_order(catalog)
    bundles = catalog["bundles"]
    patches = catalog["patches"]
    catalog_files = catalog["catalog_files"]
    files: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for operation in order["selected_operations"]:
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
                            **_operation_identity(operation),
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
                                **_operation_identity(operation),
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
                                **_operation_identity(operation),
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
                        "operation_entries": [],
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
                file_plan["patches"].append(operation["patch_id"])
                file_plan["bundles"].append(operation["bundle"])
                file_plan["operation_entries"].append(_operation_identity(operation))
                ready_targets += 1
                results.append(
                    {
                        **_operation_identity(operation),
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
                    **_operation_identity(operation),
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
                    "qualifiedId": operation["qualified_id"],
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
                    "qualifiedId": operation["qualified_id"],
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
            f"{CATALOG_ID}\0{file.relative_to(overrides_dir).as_posix()}\0{file.read_text(encoding='utf-8')}"
            for file in catalog_files
        )
    )
    return {
        "bundles": bundles,
        "patches": [patch["id"] for patch in patches],
        "catalogs": [{"id": CATALOG_ID}],
        "selectedBundles": [
            {
                "id": item["id"],
                "catalog": item["catalog"],
                "qualifiedId": item["qualifiedId"],
            }
            for item in catalog["selected_bundles"]
        ],
        "selectedPatches": [
            {
                "id": patch["id"],
                "catalog": patch["catalog"],
                "qualifiedId": patch["qualified_id"],
                "bundle": patch["bundle"],
                "bundles": patch["bundles"],
            }
            for patch in patches
        ],
        "operationOrder": order["operation_order"],
        "files": list(files.values()),
        "results": results,
        "catalogHash": catalog_hash,
        "catalogOperations": [
            {
                "id": operation["id"],
                "catalog": operation["catalog"],
                "qualifiedId": operation["qualified_id"],
                "patch": operation["patch_id"],
                "qualifiedPatch": operation["qualified_patch_id"],
                "targets": [target["path"] for target in operation["targets"]],
            }
            for operation in order["all_operations"]
        ],
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
        changed、unchanged、missingTargets、optionalSkipped、targets、backupNotes 和 provenance 汇总。

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
        "schemaVersion": 2,
        "catalogHash": plan["catalogHash"],
        "applied": [
            {
                **entry,
                "target": file_plan["target"],
                "status": "applied",
                "resultHash": file_plan["after_hash"],
            }
            for file_plan in plan["files"]
            for entry in file_plan["operation_entries"]
        ],
    }
    missing_targets = sum(item["status"] == "missing-target" for item in plan["results"])
    optional_skipped = sum(item["status"] == "optional-skip" for item in plan["results"])
    return {
        "changed": changed,
        "unchanged": unchanged,
        "skipped": missing_targets + optional_skipped,
        "missingTargets": missing_targets,
        "optionalSkipped": optional_skipped,
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
        overrides_dir = Path(args[0])
        target_root = Path(args[1])
        python_command = _resolve_trellis_python_command(target_root.resolve(strict=True))
        policy = load_patch_policy(overrides_dir, python_command)
        version_file = target_root / ".trellis/.version"
        version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else ""
        compatibility = evaluate_patch_compatibility(version, policy["compatibility"])
        compatibility_report = {
            "version": compatibility["version"],
            "diagnostics": compatibility["diagnostics"],
            "summary": _summarize(compatibility["diagnostics"]),
        }
        # 未支持版本必须先返回 --no-enhance 指引，不能被旧 catalog 的 selector 漂移掩盖。
        assert_no_patch_conflict_errors(compatibility_report)
        plan = prepare_patches(overrides_dir, target_root, args[2:], python_command)
        report = build_patch_conflict_report(version, plan, policy)
        for diagnostic in report["diagnostics"]:
            if diagnostic["severity"] == "warning":
                print(f"  · {format_patch_diagnostic(diagnostic)}")
        assert_no_patch_conflict_errors(report)
        result = apply_prepared(target_root, plan)
    except (OSError, UnicodeError, json.JSONDecodeError, PatchError) as error:
        print(f"❌ {error}", file=sys.stderr)
        return 1
    print(
        "  ✓ Patch "
        f"changed={result['changed']} unchanged={result['unchanged']} "
        f"missing-target={result['missingTargets']} "
        f"optional-skip={result['optionalSkipped']}"
    )
    if report["summary"]["info"]:
        print(f"  · Patch 信息:{report['summary']['info']} 个目标入口未安装")
    for item in result["results"]:
        if item["status"] == "optional-skip":
            print(
                "  · optional Patch 跳过:"
                f"{item['id']}@{item['target']}({item['reason']})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
