# NOTICE

本文件说明 `skill-garden` 仓库的内容构成与各部分的复用边界。仓库同时包含**本项目原创内容**和**上游 Trellis 衍生内容**，两者许可证不同，请分别对待。

---

## 一、原创内容：MIT

以下路径为本项目原创，按仓库根目录的 [`LICENSE`](./LICENSE)（MIT）授权：

| 路径 | 内容 |
|------|------|
| `.common/**` | 全部通用 Skill（`humanize-writing`、`aliyun-ops`、`craft-rpa`、`craft-slides`、`open-idea`、`torrent-analyze` 等）及其 `SKILL.md`、脚本、模板、参考文档 |
| `.trellis/<variant>/.claude/**`、`.trellis/<variant>/.agents/**` | Trellis 强化包的 Skill / Command 正文 |
| `.trellis/0.6/scripts/**` | 强化包新增的独立脚本（`task_intent.py`、`auto_loop.py`、`untracked_flow.py` 等） |
| `.trellis/0.6/overrides/bundles/**` | Patch Bundle 声明 |
| `.trellis/0.6/overrides/patches/**/patch.json` 及 `*-content.*` | Patch 声明与本项目编写的替换/插入内容 |
| `.trellis/0.5/overrides/trellis-route.md` | 0.5 变体的 routing 注入内容 |
| `scripts/**` | `install.sh`、`apply-trellis-patches.py`、`generate-compiled-targets.py` |
| `README.md`、`.common/skill-migrations.json` | 文档与迁移声明 |

MIT 允许复制、修改、合并、发布、分发、再许可和销售，含公司内部使用与商业使用；唯一要求是在副本或实质性部分中**保留上述版权声明与许可声明**。不要求以相同许可证发布衍生作品。

---

## 二、上游 Trellis 衍生内容：受 AGPL-3.0-only 约束

以下路径包含上游 [Trellis](https://docs.trytrellis.app/)（npm 包 `@mindfoldhq/trellis`，作者 Mindfold LLC，许可证 **AGPL-3.0-only**）的原文或其修改结果。**MIT 不适用于这些部分**，其复制、修改与再分发受上游许可证约束：

| 路径 | 与上游的关系 |
|------|--------------|
| `compiled-targets/**` | 上游 Trellis 模板文件（如 `.trellis/workflow.md`、`.trellis/scripts/task.py`、`.trellis/agents/*.md`）应用本项目 Patch 后的**完整成品文件**，以及对应的 `*.diff` sidecar。正文主体来自上游 |
| `.trellis/0.6/overrides/patches/**/*selector*` | Patch 的定位锚点，内容是上游源文件的**逐字摘录** |
| `.trellis/0.6/overrides/patches/**/*baseline*` | Patch 的基线校验片段，内容是上游源文件的**逐字摘录** |

这些文件之所以入库，是为了让 Patch 具备可预检的基线、并保留确定性的审阅 diff；它们不是安装输入，也不是恢复源（见 README 的 “Compiled Targets” 一节）。

另需说明：`*-content.*` 替换内容整体为本项目原创（122 个文件约 1800 行），但少数 `replace` 操作的性质决定了其内容是在上游原文基础上裁剪或改写而成（例如仅删减若干行的 import 块）。这类短片段的复用同样以上游许可证为准。

**若你的复用只涉及第一类原创内容**（例如 issue #1 提到的 `humanize-writing`），则完全按 MIT 处理，不受本节影响。

**若你的复用涉及本节路径**，请以上游 AGPL-3.0-only 的条款为准，并自行完成合规评估——AGPL 对修改后经网络提供服务的场景有额外的源码提供义务。上游许可证全文随 `@mindfoldhq/trellis` npm 包分发。

---

## 三、说明

- 本文件描述本项目对自身内容的授权意图，以及对上游内容来源的事实标注，不构成法律意见。涉及 AGPL 部分的合规判断请咨询你所在组织的法务。
- 若发现上表的路径归类与仓库实际内容不符（例如新增目录未被覆盖），请提 issue 指出，本文件会随之修订。
