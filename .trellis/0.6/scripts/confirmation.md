# 会话内超时确认

本协议只服务 Brief 首次开工、Check-All 问题处置、Push 精确计划。项目默认启用，由当前原生 Codex 客户端 / App Server 或 Claude Code 提供交互工具。当前入口未注册工具、配置不可用或会话失联时，给出原因并保持人工。经校验的 auto-loop 使用原 runner，不叠加本协议。Spec 歧义、未决业务取舍和独立权限审批不能自动作答。

## 先确认能力

只从当前工具列表识别原生确认工具：Codex 为 `trellis_confirmation`，Claude 为 `flower-confirmation` 注册的 `confirm`。以本轮实际暴露的工具名调用 `{"operation":"status"}`。同时得到 `protocol=1`、`bound=true`、`ready=true`、`enabled=true` 及 `kinds.<brief|check|push>=true` 才继续。工具缺失、返回 `manual` 或读取失败时，简述工具或策略给出的原因并沿用人工。禁止把 Shell、其他 MCP、`request_user_input` 的自定义 timeout 或定时唤醒当成原生展示或有效领取。

## 冻结、展示与领取

1. 先按流程 owner 形成完整材料，保留原模板、全部范围和风险。Brief 直接使用最新 `<task>/brief.md`。检查报告和 Git 计划将完整正文送入 `confirmation.py materialize` 的 stdin；结果给出 gitignored `.trellis/.runtime/confirmations/materials/<id>.md`。该文件仅用于当前跨进程校验，不是导出附件，不放入任务交付或 Git 计划。禁止用 shell 插值生成正文。
2. 准备 `spec`：必填 `kind`、`file`（正文相对路径）；有依据时将相对路径放入 `basis`。检查将当前**全部待处置** ID 放入 `problem_ids`（CHK/FBK/DOC）；提交必填 `mode: "push"|"commit-only"`，单仓填写 `git_paths`，多仓用 `repositories: [{"root":"仓库路径","git_paths":["精确文件"]}]` 按计划顺序列全。任务记录、生成命令和预计输出仍完整写在正文中。调用 `{"operation":"prepare","spec":{…}}` 后得到 `request_id` 和策略 `seconds`；此时未计时。
3. 调用 `{"operation":"wait","request_id":"<id>"}`。支持直接长等待时也可使用 `{"operation":"wait","spec":{…}}` 合并准备和等待。原生界面完整展示冻结正文、默认动作和秒数，并确认绘制后开始计时；这次展示满足 owner 的完整正文要求。Codex Code Mode 使用单次 `functions.exec`，按准备返回的秒数加上展示和复核余量（30 秒）设置 `yield_time_ms`；宿主预算不足时保持人工。不得缩短时长或用助手文本、文件链接替代展示。工具仍在等待时只等待原调用，不重复准备。
4. 只有匹配请求的 `source=policy_timeout`、`decision=continue` 才调用同一原生工具的 `{"operation":"claim","request_id":"<id>"}`。**claim 成功**且返回的 `kind`、`action` 与本次 owner 匹配，才替代本次人工范围选择。工具返回后、claim 之前到达的人工输入仍可撤销。领取失败、取消、材料变化、预算不足或工具失败时保持人工；不重试领取来重复执行。取消本身既不批准也不拒绝方案。
5. 领取后仍遵守 owner 的全部检查、前置条件、文件与分支范围。按实际结果调用 `{"operation":"finish","request_id":"<id>","outcome":"completed|interrupted|needs_verification"}`（选择一个值）。失联时如实报告已经产生的副作用及待核验项。活许可只存在于当前入口内存，重开不会消费旧请求。

## 默认动作

| kind | 时长默认值 | claim.action | 领取后的动作 |
| --- | --- | --- | --- |
| brief | 正文1000字内100秒，之后每500字加30秒，不足一档按一档 | implement | 对这份已展示且有效的方案运行 `task.py start`，进入实现 |
| check | 第一条100秒，每多一条加30秒；零条不等待 | repair_all_and_recheck | 修复当前报告全部待处置项并重检；新业务取舍暂停，风险接受仍必须人工明确决定 |
| push | 200秒 | execute_git_plan | 沿用当前计划和模式；普通 commit + push，明确 commit-only 时仅本地提交 |

报告必须把自动决定来源写为 `policy_timeout`，不能写成“用户已经确认”。人工分支由原 owner 核对真实回复并记 `human`；按键取消本身不是批准。prepare 重试复用同一请求，已领取或撤销的同版本材料不能重新自动执行。材料、范围、模式、Git 基线或会话变化后，旧请求失效；更改方案必须重新冻结和展示。显式只读、暂停、停止、拒绝或用户更改范围时不准备自动决定。项目默认启用，`.trellis/config.yaml` 的 `confirmation_timeout.enabled: false` 可关闭；各类的 `enabled` 和秒数配置独立，缺失采用默认、损坏回人工，不得临时缩短用户时长来促使当前动作执行。
