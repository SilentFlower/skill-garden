# Skill Garden

这是一个个人技能仓库骨架，用来集中管理你自己的 AI Agent 技能。

目标是同时兼容不同 Agent 运行时，并把技能本身集中放在统一位置，便于后续沉淀和迁移。

## 目录结构

- `.codex/skills/`
  放 Codex 项目级技能。
- `.claude/skills/`
  放 Claude 项目级技能。

## 推荐用法

- 每个技能尽量保持同名目录，方便在不同 Agent 之间对齐。
- 如果某个技能同时要兼容 Codex 和 Claude，优先保证两个目录下的技能名一致。
- 真正执行逻辑尽量收敛到一份主脚本，避免两个 Agent 各维护一套分叉实现。
- 技能自己的私有配置优先放在技能目录里的 `env/` 下，不要把示例值当成真实配置使用。
- 真实密钥配置建议只放在本地 `push.env`，仓库里只保留 `push.env.example`。

## 新增一个技能

1. 在 `.codex/skills/` 下创建技能目录。
2. 在 `.claude/skills/` 下创建同名技能目录。
3. 先写最小可用的 `SKILL.md`。
4. 如果需要执行脚本，在技能目录下加 `scripts/` 包装入口。
5. 如果两个 Agent 共用同一份逻辑，把主实现放在其中一侧的稳定路径，再由两边包装脚本去调用。

## 同步到其他项目

可以使用：

```bash
bash skill-garden/scripts/sync_skills.sh <目标项目目录> [skill-name...]
```

如果不传技能名，会把当前仓库里的全部技能都挂到目标项目的 `.codex/skills/` 和 `.claude/skills/`。

## 当前状态

当前已经迁入一个技能：

- `sub2api-account-json-fix`

它的主实现位于 `.codex/skills/sub2api-account-json-fix/`，Claude 兼容入口位于 `.claude/skills/sub2api-account-json-fix/`。
