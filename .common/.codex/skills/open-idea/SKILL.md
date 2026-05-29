---
name: open-idea
description: 跨平台打开 IntelliJ IDEA 并加载指定项目目录。适用于用户要求“用 IDEA 打开这个项目 / open idea / 打开指定项目路径”，支持 Windows、macOS、Linux，以及在 WSL 中唤起 Windows IDEA 并自动转换路径。不用于修改项目代码、安装 JetBrains 产品或配置远程开发环境。
---

# 打开 IDEA

## 适用场景

- 用户要从当前会话唤起 IntelliJ IDEA 打开当前项目或指定路径。
- 当前环境可能是 Windows、macOS、Linux 或 WSL。
- WSL 中需要调用 Windows 侧 IDEA，并把 Linux 路径转换成 Windows 可识别路径。

## 执行原则

1. 优先使用本 skill 自带脚本，避免每次手写跨平台启动逻辑。
2. 如果用户没有给项目路径，默认使用当前工作目录。
3. 如果项目路径不存在，先停止并提示，不要猜测相近目录。
4. 如果用户指定了 IDEA 可执行文件，优先使用该路径；否则再尝试环境变量和常见安装路径。
5. WSL 中默认优先唤起 Windows IDEA，因为用户通常期望打开 Windows 桌面应用。

## 快速命令

从已安装 skill 的目标项目中执行：

```bash
python .codex/skills/open-idea/scripts/open_idea.py .
```

打开指定目录：

```bash
python .codex/skills/open-idea/scripts/open_idea.py /path/to/project
```

指定 IDEA 可执行文件：

```bash
python .codex/skills/open-idea/scripts/open_idea.py /path/to/project --idea "/path/to/idea"
```

只打印将要执行的命令，不真正启动：

```bash
python .codex/skills/open-idea/scripts/open_idea.py /path/to/project --dry-run
```

发起启动但不等待项目窗口验证：

```bash
python .codex/skills/open-idea/scripts/open_idea.py /path/to/project --no-verify
```

## 配置

脚本按以下优先级查找 IDEA：

1. 命令行 `--idea <path-or-command>`
2. 环境变量 `IDEA_EXECUTABLE`
3. 平台常见安装路径，并优先选择路径版本号最高的 IDEA
4. 当前环境 PATH 中的 `idea`、`idea64.exe`
5. WSL 中通过 `powershell.exe` 扫描 Windows 安装路径，并优先选择版本号最高的 IDEA

## WSL 规则

- 默认把项目路径通过 `wslpath -w` 转成 Windows 路径，并优先使用 `\\wsl$\...` 形式；如果 Windows 侧不可访问，再回退到 `\\wsl.localhost\...`。
- 默认调用 Windows 侧 IDEA。
- 启动前必须用 Windows 侧 `Test-Path` 校验转换后的项目路径可访问；不可访问时直接报错并提示用户改用 Windows 盘、WSL 普通用户目录或先修复 Windows 对 WSL UNC 路径的访问。
- 启动后默认等待项目窗口出现；只要未确认目标项目窗口标题，就不能简单声称“已打开”。
- 如果 IDEA 进程存在但没有项目窗口，脚本会检查最近的 IDEA 日志。若出现 `Station`、`Remote Execution Agent`、`IJent`、`WslIjent` 相关启动异常，应提示用户可临时禁用插件 `com.jetbrains.station` 和 `intellij.platform.ijent.impl` 后重试；不要自动修改用户 IDEA 配置。
- 如需强制使用 Linux 侧 IDEA，可加：

```bash
python .codex/skills/open-idea/scripts/open_idea.py . --target linux
```

## 输出要求

执行后向用户说明：

- 使用了哪个 IDEA 启动入口。
- 打开的项目路径。
- 是否已确认目标项目窗口打开；如果未确认，要说明检测到的进程窗口状态和日志诊断。
- 如果是 `--dry-run`，说明没有真正启动。
- 如果失败，给出缺失的配置项、可执行文件路径建议，或 Windows 无法访问 WSL 项目路径的具体原因。

## 反模式

- 不要硬编码单一 IDEA 安装路径后直接失败。
- 不要在 WSL 中把 `/home/...` 原样传给 Windows IDEA。
- 不要把 `Start-Process` 成功等同于 IDEA 已经打开项目。
- 不要自动安装 IDEA、Toolbox 或修改用户 shell 配置。
- 不要默认自动禁用 IDEA 插件；只能作为故障诊断建议，除非用户明确要求。
- 不要因为找不到 IDEA 就改项目文件。

## 资源

- `scripts/open_idea.py`：跨平台启动 IDEA 的主脚本。
