---
name: trellis-run-e2e
description: "Run end-to-end behavior verification combining Playwright (frontend UI), curl (backend API), and MySQL MCP (DB assertions). Input is a 场景-路径-期望 scenario table; executes each row and logs pass/fail, restoring test data when needed. Triggers: 「跑E2E」「端到端验证」「自动化测试场景」「跑场景测试」「e2e test」. Not for lint/unit/spec-only (use trellis-check)."
---

# Run End-to-End Verification — 跨层自动化验证

以"场景-路径-期望"三列表为输入，逐条跨层执行并验证：Playwright 驱 UI、curl 打 API、MySQL MCP 查数据。最后汇总结果与必要的数据恢复。

> **何时用**：PR 前 UAT、功能端到端验收、单测覆盖不到的跨层流程验证。
> **何时不用**：只跑 lint/typecheck/spec 合规（去 `trellis-check`）；只做 PRD↔代码静态对照（去 `trellis-check-all`）。

---

## 前置条件（先自检，缺一项就暂停）

| 能力 | 典型来源 | 检查方式 |
|------|---------|---------|
| 前端 dev server | `http://localhost:3000/#/...` | `curl -sI $URL` / Playwright `browser_navigate` |
| 后端 API | `http://<host>:<port>/api/...` | `curl -sI $URL` |
| 登录态 / token | `x-dev-mode: true` + `authorization: Bearer <token>` 或 cookie | Playwright `browser_evaluate` 读 `sessionStorage`/`localStorage` |
| 数据库访问 | MySQL MCP 已注册 | `mcp__mysql__mysql_query` 可用 |
| 浏览器工具 | Playwright MCP（优先） | `mcp__plugin_playwright_playwright__browser_*` 可用 |

**缺项时**：向用户说明缺的是哪一项、用什么方法补（启动 dev / 换环境 / 切账号），**不要擅自跳过**。

---

## 执行步骤

### Step 0: 环境自检 + 抓登录态

```bash
# 前端可达？
curl -sI http://localhost:3000/ | head -1

# 后端可达？
curl -sI http://<backend-host>:<port>/api/... | head -1
```

用 Playwright 导航到一个已知可访问的页面，从 `sessionStorage`/`localStorage` 取 token：

```js
// browser_evaluate
() => ({
  token: sessionStorage.getItem('<token-key>'),
  user: localStorage.getItem('<user-key>'),
})
```

抓 Playwright 的 `browser_network_requests`，观察一次真实的 XHR，**确认后端要求的 header**（常见：`authorization`、`x-dev-mode`、自定义 traceId）。把这份 header 作为后续 `curl` 的模板。

### Step 1: 构造/加载场景表

**首选**：用户已经整理好 "场景 / 路径 / 期望" 三列表。照抄即可。

**次选**：从任务 `prd.md` 的 Acceptance Criteria + Business Rules 按下表模板补齐：

| 场景 ID | 路径类型 | 操作 | 期望 |
|---------|---------|------|------|
| S1 | UI | 走页面 X → 点按钮 Y → 填 Z | 弹窗/状态/提示 A |
| S2 | API | POST /callbacks/... body `{...}` | 返回 code=0，DB 字段 X=Y |
| S3 | DB+API | 先查基线 → 调接口 → 再查 | 某字段从 X 变 Y + 新流转日志 `Z` |
| S4 | 跨层 | UI 触发 → 后端副作用 → DB 对账 | 所有层一致 |

每条必须有明确的**可观察信号**（UI 文案、HTTP code、DB 字段值），避免 "应该能跑"。

### Step 2: 识别测试数据 + 备份基线

对每个场景：

1. 从 DB 查出测试目标的**基线状态**（任务状态、SLA、日志条目数等），写入对话上下文作为"Before"。
2. 对每个会被改动的字段，记录**回滚所需信息**（原值、原项目状态、原 flow_no 等）。
3. **不要改线上生产数据**；环境若是共享测试/预发，优先找孤立数据或使用临时数据。

### Step 3: 逐场景执行

按 ID 顺序执行每个场景，每条遵循以下模板：

```markdown
#### Sx: <场景名>
- Path: <UI/API/DB/跨层>
- Pre: <基线>（从 DB 查到的 Before）
- Act:
  - UI: Playwright 动作（snapshot → click/type → wait）
  - API: curl 带 header 调接口
  - DB: mcp__mysql__mysql_query 预改数据（仅当场景要求，比如把项目状态临时改成 Completed）
- Expect:
  - UI: `browser_take_screenshot` / `browser_snapshot` / 捕获 toast（用 MutationObserver）
  - API: 返回体 code=0 / msg = "<文案>"
  - DB: 字段变化 + 新 flow log 条目
- Result: ✅ / ❌ + 差异说明
- Restore: <必要的 UPDATE 恢复现场>
```

**UI 细节**：
- Toast 文案有 2.5s 自动消失，**别等**——先在 `browser_evaluate` 里装 MutationObserver 抓文案，再点按钮：

  ```js
  window.__toasts = [];
  new MutationObserver(() => {
    for (const el of document.querySelectorAll('*')) {
      const t = el.textContent?.trim() || '';
      if (t.includes('<关键字>') && t.length < 200 && el.children.length < 3) {
        if (!window.__toasts.includes(t)) window.__toasts.push(t);
      }
    }
  }).observe(document.body, { childList: true, subtree: true });
  // 再触发按钮点击
  ```

- 下拉/autocomplete 可能依赖聚焦事件。用 `browser_click` 先聚焦输入框再 `browser_type`，避免 `fill` 绕过 focus handler 不触发下拉。

**API 细节**：
- Header **完全对齐**前端抓到的真实请求（authorization、x-dev-mode、traceId）。无 token 报 401 时别去改服务端，先回去检查 header。
- 回调类接口通常**不需要用户 token**（对外系统调用），但前端业务接口必须带。
- 幂等键（requestId/externalNo）**每次用新值**，避免 IqsCallbackLog 去重返回 success 但其实没执行。

**DB 细节**：
- 查询用 `SELECT ... AS <alias>` 让 key 可读。
- 写 DML 前 `SELECT` 一次记录基线；写后 `SELECT` 一次对比。
- 多条 UPDATE 不要塞同一个 `mysql_query` 调用（某些 MCP 实现不支持 multi-statement），拆成多次调用。

### Step 4: 发现偏差时暂停

任意一条 ❌：**立即暂停**，向用户说明：

- 场景 ID + 具体差异（文案差一个字 / 状态没变 / 日志没新增）
- 是代码问题还是部署滞后（若行为像旧代码，优先怀疑部署：用 `javap -c <class>` 反编译看字节码是否含新逻辑；进程启动时间 vs class mtime 对比；IDE hot-reload 对 lambda 常失败，让用户 Rebuild Project）
- 建议修复方向（改代码 / rebuild / 换测试数据）

不要硬跑完再总结 — 早发现早暂停更省时间。

### Step 5: 数据恢复（tear-down）

用前面备份的基线信息逐条 UPDATE 回去：

```sql
-- 任务状态回滚
UPDATE <tbl_task> SET c_status = '<原值>', c_closed_at = NULL WHERE id = '...';
-- 项目状态回滚（如果测试时改过）
UPDATE <tbl_project> SET c_status = '<原值>', ... WHERE id = '...';
-- 清掉测试时加的 flow log / status log
DELETE FROM <tbl_flow_log> WHERE c_request_id LIKE 'PW-SCENARIO-%';
```

恢复完**再查一次**确认。若某条无法恢复（比如已上链的外部系统调用），**明确告知用户**并记录。

### Step 6: 汇总报告

```markdown
## 🎯 E2E 测试汇总

| 场景 | 路径 | 期望 | 结果 |
|------|------|------|:---:|
| S1 | UI | ... | ✅ |
| S2 | API+DB | ... | ✅ |
| S3 | 跨层 | ... | ❌：<差异说明> |

### 覆盖统计
- 通过：X / 总 N
- 失败：Y（需修复）
- 跳过：Z（未具备前置条件）

### 数据影响
- 修改过 M 条 DB 行，已全部恢复 ✅
- 未恢复：<如果有>

### 建议下一步
- <根据失败/跳过场景的具体建议>
```

---

## 核心原则

| 原则 | 为什么 |
|------|--------|
| **先对齐场景再动手** | "想当然测" = 白跑；文案/状态一个字都要写入期望 |
| **跨层交叉验证** | UI 看绿 ≠ DB 真的改了；只查 DB ≠ 用户能用 |
| **Header 和真实请求一致** | 401 80% 是 header 差一个，不要去改服务端 |
| **每场景都能 roll-back** | 不清理的"测试痕迹"会变成下一个人的 bug 现场 |
| **差异立即停** | 一条 ❌ 可能说明整批假设都错了，别继续堆无效结果 |

---

## 反模式（避免）

- ❌ 用 Playwright 只截图就下结论 — 文案可能已消失、或被 overlay 遮挡
- ❌ Toast 断言用 `sleep + screenshot` — 2.5s 够消失的，必须 MutationObserver 实时抓
- ❌ 跑完忘记 tear-down — 污染后续测试，特别是项目/状态类的"临时改成 Completed"
- ❌ 用相同 requestId 重跑 — 被 IqsCallbackLog 幂等返回 success，但实际没执行任何逻辑
- ❌ 发现一处失败就怀疑整个代码 — 先 `javap -c` 看字节码是否含新逻辑，可能只是 IDE 没 rebuild
- ❌ 场景表里写 "大致正常" / "应该能用" — 没有可观察信号就无法判定通过
- ❌ 把 DB 写操作塞进一个 multi-statement string — MCP 不一定支持，拆开更稳
- ❌ 跳过 Step 0 环境自检直接点按钮 — 浪费好几轮才发现 token 失效或没登录

---

## 与其他入口的区别

| 入口 | 形态 | 用途 |
|------|------|------|
| `trellis-check` | skill | lint / typecheck / spec 规范 |
| `trellis-check-all` | skill | PRD→代码 静态对照 + 假设验证 |
| **`trellis-run-e2e`** | skill（本技能）| **运行时行为跨层验证（UI+API+DB）** |
| `trellis-verify-prd` | skill | PRD↔源需求文档对账 |
