#!/usr/bin/env python3
"""跨平台唤起 IntelliJ IDEA 并打开项目目录。"""

from __future__ import annotations

import argparse
import glob
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence


def is_wsl() -> bool:
    """判断当前 Python 是否运行在 WSL 中。"""
    if "WSL_DISTRO_NAME" in os.environ or "WSL_INTEROP" in os.environ:
        return True

    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return False

    return "microsoft" in release or "wsl" in release


def current_platform() -> str:
    """返回当前平台标识。"""
    if is_wsl():
        return "wsl"

    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    return "linux"


def run_text(command: Sequence[str]) -> str | None:
    """执行命令并返回去除空白后的 stdout，失败时返回 None。"""
    try:
        result = subprocess.run(command, check=True, text=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None

    value = result.stdout.strip()
    return value or None


def powershell_text(script: str) -> str | None:
    """通过 Windows PowerShell 执行脚本并返回 stdout。"""
    return run_text(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script])


def powershell_literal(value: str) -> str:
    """把字符串转成 PowerShell 单引号字面量。"""
    return "'" + value.replace("'", "''") + "'"


def resolve_project_path(raw_path: str) -> Path:
    """解析并校验项目路径。"""
    project_path = Path(raw_path).expanduser()
    if not project_path.is_absolute():
        project_path = Path.cwd() / project_path

    project_path = project_path.resolve()
    if not project_path.exists():
        raise FileNotFoundError(f"项目路径不存在：{project_path}")
    if not project_path.is_dir():
        raise NotADirectoryError(f"项目路径不是目录：{project_path}")

    return project_path


def wsl_to_windows_path(path: Path) -> str:
    """把 WSL 路径转换为 Windows 可识别路径。"""
    converted = run_text(["wslpath", "-w", str(path)])
    if converted:
        return converted

    raise RuntimeError("无法通过 wslpath 转换项目路径，请确认当前环境是 WSL。")


def assert_windows_path_accessible(path: str) -> None:
    """确认 Windows 侧能访问传给 IDEA 的项目目录。"""
    script = f"if (Test-Path -LiteralPath {powershell_literal(path)} -PathType Container) {{ 'OK' }} else {{ 'MISSING' }}"
    result = powershell_text(script)
    if result == "OK":
        return

    raise RuntimeError(
        "Windows 侧无法访问转换后的 WSL 项目路径："
        f"{path}。请先在 Windows 文件资源管理器中确认该路径可打开，"
        "或把项目放到 Windows 盘 / WSL 普通用户目录后重试。"
    )


def normalize_wsl_windows_executable(executable: str) -> str:
    """把 WSL 中的 Windows 可执行文件路径转换为 PowerShell 可识别路径。"""
    if executable.startswith("/") and Path(executable).exists():
        converted = run_text(["wslpath", "-w", executable])
        if converted:
            return converted

    return executable


def windows_normalize_path(path: Path) -> str:
    """返回 Windows 本机可使用的绝对路径字符串。"""
    return str(path)


def version_key_from_text(text: str) -> tuple[int, ...]:
    """从路径或版本文本里提取可排序的 IDEA 版本号。"""
    candidates: list[tuple[int, ...]] = []

    for match in re.finditer(r"(?<!\d)(20\d{2}(?:\.\d+){0,4})(?!\d)", text):
        candidates.append(tuple(int(part) for part in match.group(1).split(".")))

    for match in re.finditer(r"(?<!\d)(2\d{2}(?:\.\d+){1,4})(?!\d)", text):
        parts = [int(part) for part in match.group(1).split(".")]
        branch = parts[0]
        # JetBrains 构建号 253.x 表示 2025.3.x，用它补足 Toolbox 这类不含年份的路径。
        candidates.append((2000 + branch // 10, branch % 10, *parts[1:]))

    return max(candidates, default=(0,))


def best_idea_candidate(candidates: Iterable[tuple[str, str, float]]) -> str | None:
    """按路径版本号优先选择最新 IDEA，版本相同再看产品版本和修改时间。"""
    items = list(candidates)
    if not items:
        return None

    def sort_key(item: tuple[str, str, float]) -> tuple[tuple[int, ...], tuple[int, ...], float]:
        path, metadata, mtime = item
        return version_key_from_text(path), version_key_from_text(metadata), mtime

    return max(items, key=sort_key)[0]


def newest_match(patterns: Iterable[str]) -> str | None:
    """返回通配符匹配到的最高版本 IDEA 文件。"""
    matches: list[tuple[str, str, float]] = []
    for pattern in patterns:
        for item in glob.glob(os.path.expandvars(os.path.expanduser(pattern))):
            path = Path(item)
            if path.is_file():
                matches.append((str(path), "", path.stat().st_mtime))

    return best_idea_candidate(matches)


def windows_idea_candidates_from_powershell() -> list[tuple[str, str, float]]:
    """从 Windows 侧扫描 IDEA 安装目录并返回候选项。"""
    script = r"""
$ErrorActionPreference = "SilentlyContinue"
$patterns = @(
  "$env:LOCALAPPDATA\JetBrains\Toolbox\apps\IDEA-U\ch-0\*\bin\idea64.exe",
  "$env:LOCALAPPDATA\JetBrains\Toolbox\apps\IDEA-C\ch-0\*\bin\idea64.exe",
  "$env:ProgramFiles\JetBrains\IntelliJ IDEA*\bin\idea64.exe",
  "${env:ProgramFiles(x86)}\JetBrains\IntelliJ IDEA*\bin\idea64.exe"
)
Get-PSDrive -PSProvider FileSystem | ForEach-Object {
  $patterns += "$($_.Root)IntelliJ IDEA*\bin\idea64.exe"
  $patterns += "$($_.Root)JetBrains\IntelliJ IDEA*\bin\idea64.exe"
}
$seen = @{}
foreach ($pattern in $patterns) {
  Get-ChildItem -Path $pattern -File | ForEach-Object {
    if (-not $seen.ContainsKey($_.FullName)) {
      $seen[$_.FullName] = $true
      "{0}`t{1}`t{2}" -f $_.FullName, $_.VersionInfo.ProductVersion, $_.LastWriteTimeUtc.Ticks
    }
  }
}
exit 0
"""
    output = powershell_text(script)
    if not output:
        return []

    candidates: list[tuple[str, str, float]] = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        path, product_version, ticks = parts
        try:
            mtime = float(ticks)
        except ValueError:
            mtime = 0.0
        candidates.append((path, product_version, mtime))
    return candidates


def find_windows_idea(user_idea: str | None = None, from_wsl: bool = False) -> str | None:
    """查找 Windows 侧 IDEA 可执行文件。"""
    if user_idea:
        return user_idea

    env_idea = os.environ.get("IDEA_EXECUTABLE")
    if env_idea:
        return env_idea

    if from_wsl:
        idea_from_scan = best_idea_candidate(windows_idea_candidates_from_powershell())
        if idea_from_scan:
            return idea_from_scan

        path_idea = powershell_text(
            "$cmd = Get-Command idea64.exe,idea.exe,idea -ErrorAction SilentlyContinue | "
            "Select-Object -First 1; if ($cmd) { $cmd.Source }"
        )
        if path_idea:
            return path_idea

        return None

    common_paths = [
        r"%LOCALAPPDATA%\JetBrains\Toolbox\apps\IDEA-U\ch-0\*\bin\idea64.exe",
        r"%LOCALAPPDATA%\JetBrains\Toolbox\apps\IDEA-C\ch-0\*\bin\idea64.exe",
        r"%ProgramFiles%\JetBrains\IntelliJ IDEA*\bin\idea64.exe",
        r"%ProgramFiles(x86)%\JetBrains\IntelliJ IDEA*\bin\idea64.exe",
        r"C:\IntelliJ IDEA*\bin\idea64.exe",
        r"D:\IntelliJ IDEA*\bin\idea64.exe",
        r"E:\IntelliJ IDEA*\bin\idea64.exe",
        r"C:\JetBrains\IntelliJ IDEA*\bin\idea64.exe",
        r"D:\JetBrains\IntelliJ IDEA*\bin\idea64.exe",
        r"E:\JetBrains\IntelliJ IDEA*\bin\idea64.exe",
    ]
    idea_from_scan = newest_match(common_paths)
    if idea_from_scan:
        return idea_from_scan

    return shutil.which("idea64.exe") or shutil.which("idea.exe") or shutil.which("idea")


def find_macos_idea(user_idea: str | None = None) -> str | None:
    """查找 macOS 侧 IDEA 启动入口。"""
    if user_idea:
        return user_idea

    env_idea = os.environ.get("IDEA_EXECUTABLE")
    if env_idea:
        return env_idea

    path_idea = shutil.which("idea")
    if path_idea:
        return path_idea

    for app_name in ("IntelliJ IDEA.app", "IntelliJ IDEA CE.app"):
        app_path = Path("/Applications") / app_name
        if app_path.exists():
            return str(app_path)

    return None


def find_linux_idea(user_idea: str | None = None) -> str | None:
    """查找 Linux 侧 IDEA 启动入口。"""
    if user_idea:
        return user_idea

    env_idea = os.environ.get("IDEA_EXECUTABLE")
    if env_idea:
        return env_idea

    path_idea = shutil.which("idea") or shutil.which("idea.sh")
    if path_idea:
        return path_idea

    common_paths = [
        "~/.local/share/JetBrains/Toolbox/apps/IDEA-U/ch-0/*/bin/idea.sh",
        "~/.local/share/JetBrains/Toolbox/apps/IDEA-C/ch-0/*/bin/idea.sh",
        "/opt/idea*/bin/idea.sh",
        "/opt/intellij-idea*/bin/idea.sh",
        "/snap/bin/intellij-idea-ultimate",
        "/snap/bin/intellij-idea-community",
    ]
    return newest_match(common_paths)


def build_command(platform_name: str, project_path: Path, target: str, idea: str | None) -> tuple[list[str], str, str]:
    """生成启动 IDEA 的命令、展示用项目路径和启动入口。"""
    if platform_name == "wsl" and target != "linux":
        project_arg = wsl_to_windows_path(project_path)
        assert_windows_path_accessible(project_arg)
        idea_entry = find_windows_idea(idea, from_wsl=True)
        if not idea_entry:
            raise RuntimeError("未找到 Windows 侧 IDEA。请设置 IDEA_EXECUTABLE 或使用 --idea 指定 idea64.exe。")

        idea_entry = normalize_wsl_windows_executable(idea_entry)
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"Start-Process -FilePath {powershell_literal(idea_entry)} -ArgumentList @({powershell_literal(project_arg)})",
        ]
        return command, project_arg, idea_entry

    if platform_name == "windows":
        project_arg = windows_normalize_path(project_path)
        idea_entry = find_windows_idea(idea)
        if not idea_entry:
            raise RuntimeError("未找到 Windows IDEA。请设置 IDEA_EXECUTABLE 或使用 --idea 指定 idea64.exe。")
        return [idea_entry, project_arg], project_arg, idea_entry

    if platform_name == "macos":
        project_arg = str(project_path)
        idea_entry = find_macos_idea(idea)
        if not idea_entry:
            raise RuntimeError("未找到 macOS IDEA。请设置 IDEA_EXECUTABLE、安装 idea 命令，或使用 --idea 指定 IDEA。")

        if idea_entry.endswith(".app"):
            return ["open", "-a", idea_entry, project_arg], project_arg, idea_entry
        return [idea_entry, project_arg], project_arg, idea_entry

    project_arg = str(project_path)
    idea_entry = find_linux_idea(idea)
    if not idea_entry:
        raise RuntimeError("未找到 Linux IDEA。请设置 IDEA_EXECUTABLE、安装 idea 命令，或使用 --idea 指定 idea.sh。")

    return [idea_entry, project_arg], project_arg, idea_entry


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="跨平台唤起 IntelliJ IDEA 并打开项目目录。")
    parser.add_argument("project", nargs="?", default=".", help="要打开的项目目录，默认是当前目录。")
    parser.add_argument("--idea", help="IDEA 可执行文件路径或命令。")
    parser.add_argument(
        "--target",
        choices=("auto", "windows", "macos", "linux"),
        default="auto",
        help="启动目标。WSL 中默认 auto 会唤起 Windows IDEA；需要 Linux IDEA 时传 linux。",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印命令，不真正启动 IDEA。")
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    """命令入口。"""
    args = parse_args(argv)
    platform_name = current_platform()
    target = args.target

    if target == "auto":
        target = "windows" if platform_name == "wsl" else platform_name

    try:
        project_path = resolve_project_path(args.project)
        command, project_arg, idea_entry = build_command(platform_name, project_path, target, args.idea)
    except Exception as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1

    print(f"平台：{platform_name}")
    print(f"IDEA：{idea_entry}")
    print(f"项目：{project_arg}")
    print("命令：" + " ".join(f'"{part}"' if " " in part else part for part in command))

    if args.dry_run:
        print("dry-run：未启动 IDEA。")
        return 0

    try:
        subprocess.Popen(command)
    except OSError as error:
        print(f"错误：启动 IDEA 失败：{error}", file=sys.stderr)
        return 1

    print("已发起 IDEA 启动请求。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
