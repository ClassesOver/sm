# M0：多 Harness 基线与消费者盘点（部分交付）

日期：2026-11-14。对应 [PR #228 的 M0/PR-A](https://github.com/ClassesOver/sm/pull/228)。本次只完成源码冻结、现有入口核验、解耦清单及探针准入；外部探针部分的 M0 未完成。按用户最新方向，内部 harness 可在相关源码/权限/工具合同已核对后独立修复或推进 M1 内部能力，外部 DSH 接入不作前置条件。没有调用外部代理、模型或生产服务，没有启用开关。

## 1. 可复核基线

- `origin/code`：`ca091c5720e0a6ba4b7137abe7f6d795bc7f1dfb`；本次云端 checkout 初始 HEAD 同值，工作树干净。
- #226：合并提交 `eeebf383`，包含 `a9b55c650c3cc993700ec459a7cb72d31434a359` 的协程/租约守卫；#227：合并提交 `ca091c57`，原生编辑器变更 `edaec904`。
- #228 初始 HEAD：`0ed750ddb6b31a00c87601e0337bb74aa1e99968`，merge-base 等于上述 code SHA，无运行代码差异。修正入口描述后 HEAD 为 `5041d01c`。
- 初始 #228 Actions workflow runs 返回空列表；`gh pr checks 228` 仅显示 CodeRabbit `skipping`。Codex 审查无发现仅对应 `0ed750d`，不是新提交验收或产品联调证据。
- 仓库 `AGENTS.md` 已读取；checkout 未找到 `.agents/skills` 或其他 `SKILL.md`。测试方式依据 `pyproject.toml`、根 README、`smart_reporting/README.md` 和现有 MCP 合同测试。
- 复用云端 `.venv`：Agno 3.1.12；锁文件要求 `openai-codex==0.163.0`。未重新安装依赖，未启动 Codex CLI，CLI 存在不代表第二 harness 可接入。

## 2. 当前真实入口与迁移清单

以下均为上述源码基线的静态核查，只有第 1 行另有内嵌 MCP 工具发现测试。运行环境部署清单仍需现场 `tools/list` 核对。

| 消费者/能力 | 当前归属与证据 | 后续最小解耦边界 |
|---|---|---|
| 生产 MCP | `smart_reporting/app.py` 的 `application_context.mcp_config`：`report_workflow.as_tool(name="run_reporting_workflow")`、`default_tools=False`、`lifecycle_tools=True` | M1 修改实际应用装配；不能只修改旧工具工厂。原生工具还有 `continue_run`、`cancel_run` |
| 站内助手 facade | `reporting/agent.py::create_report_agent` 创建 `ReportWorkflowToolkit(controller)`；`app.py` 装配 `ReportWorkflowController` | 新助手直接持有受控能力；对旧 toolkit 的已有会话做迁移/排空，不能留下第二个写入者 |
| 旧 MCP 适配层 | `reporting_mcp/tools.py::create_reporting_mcp_tools`、`adapter.py::ReportingMcpAdapter` 调 controller 的 start/get/approve/reject/cancel；工厂仅由包导出、测试使用，未在 app 装配 | 保留兼容性决定和消费者登记；该层工具列表不等于生产列表 |
| 固定报告编排 | `reporting/workflow/controller.py`、`reporting/workflow/execution.py`；CLI 与应用仍使用既有报告运行链 | 盘点运行中任务及持久化身份后再禁新任务；M7 才删除固定编排，不能提前删共享函数 |
| 正文草稿/导出 | `report_editor/service.py::ReportEditorService.save_draft/export_revision`，现有 SHA 比较与修订保存 | 复用授权上下文、文件身份、草稿 CAS；M2 增加文档操作回执/outbox，不能把草稿 SHA 当跨对象协作协议 |
| 原生修订 | `report_editor/native_publication.py::NativePublicationService.save_revision` 使用 request_id、expected_sha256 和进程内 `_save_lock` | 复用真实 Office patch/身份检查；进程内锁不能代替跨进程事务、幂等和发布对账 |
| Excel/幻灯片 | `report_editor/workbook_api.py`、`slides_api.py` 的现有路由工厂 | 抽取可授权服务接口再给工具/UI 共用；不从 harness 直接模拟 HTTP Cookie 或绕过既有身份 |
| 事实/计算/数据读取 | `reporting/trace/{fact,computation,dataset,drilldown}_service.py` | 复用计算记录、来源、列可见性与 scope 检查；先消除 workflow 上下文依赖，不复制算法 |
| UI agent 进度 | `report_editor/agent_event_streams.py::AgentEventLog`，容量 128、进程内 history、越界 reset | 仅临时进度。M2 的文档事件、游标和恢复另做数据库事务；现有可重放进度不算耐久文档日志 |
| 取消/租约 | `task_execution/session.py`、`repository_impl.py::cancel_and_reject/heartbeat_lease` | 保留 owner/epoch fence；真实子进程停止、提交边界与 PostgreSQL 交错另验，不能由协程取消推导 |

在途任务处理方案：本轮不启动或改写任务。实施禁新入口前，按当前 controller/task repository 列出活动任务的 run/session/task、状态与 owner/epoch；选择有限排空或显式取消并对账产物。无法确认外部执行者停止时维持 unknown、拒绝冲突写入，不把旧任务恢复成新 harness 会话。完成迁移证据前保留历史修订与下载授权。

## 3. DSH 冻结与能力矩阵

只读取得官方仓库 `deepseek-ai/deepseek-harness`：`39163dd30f703a79079e2d2446545cff3c453738`。根与 `@deepseek-ai/dsh-api-session-controller` package.json 均为 `0.2.2-rc.3`。这是本次源码探针候选版本，不是部署版本或本项目依赖锁；未安装 DSH 依赖或执行其代码。

| 能力 | 固定源码证据 | 本项目真实运行状态 |
|---|---|---|
| prompt/追加输入 | `packages/api/session-controller/src/index.ts::prompt`、`commands.ts::prompt`；README 描述 requestId 去重，acceptance 是入队 | unknown，未接通 |
| 历史/follow | `src/index.ts::follow`、`src/web/controller.ts::follow`；README 区分 durable Session events 与 live assistant stream | unknown，未测断线补发/缺口 |
| cancel | `src/commands.ts::cancel` 调 `agent.cancel(..., {keepInbox:true})` 并返回 `{accepted:true}`，冷会话可返回 not-found | unknown；只能证明源码发出请求，未证明工具或后代进程停止 |
| 恢复/授权 | README 的 resume writer-held、Remote resource 授权说明 | unknown，未有本项目部署身份或重启证据 |
| 原生 A2A / 文档对象同步 | 本次没有完成入口与版本握手验证 | unknown，不从品牌/通用会话 API 推定支持 |
| 第二 harness | 云端存在 Codex CLI；没有选择、启动或向其委派任务 | 未选定。须先确认可用部署身份与公开适配接口，再做真实探针 |

固定源码入口：[Session Controller README](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/api/session-controller/README.md)、[取消实现](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/api/session-controller/src/commands.ts)。未把接受请求标记为执行成功。

在 `/workspace` 可见文件中未发现原 `dsh-smart-reporting` 插件源码；未搜索其他机器或假定历史绝对路径有效。当前 PATH 无 `dsh`。这些事实只说明本次云端环境的可用性，不代表用户没有部署。未读取或导出凭据。

## 4. 实跑证据

在仓库根、复用已有 `.venv` 执行一次：

```sh
.venv/bin/python -m pytest \
  smart_reporting/reporting_mcp/tests/test_contracts.py::test_agentos_embedded_mcp_exposes_only_reporting_tools \
  smart_reporting/reporting/tests/test_reporting_task_runtime_guard.py \
  smart_reporting/task_execution/tests/test_task_cancel_lease_fence.py \
  smart_reporting/reporting/tests/test_agent_events.py -q
```

结果：**38 passed，1 warning，18.81s**。warning 为第三方 visions 导入已弃用 imghdr。MCP 测试通过真实 Agno `build_mcp_server(...).list_tools()` 核对内嵌配置，但不是部署 HTTP 握手；租约测试使用 SQLite，不替代 PostgreSQL。事件测试仅验证当前进度流。未运行完整套件、真实模型、DSH、Office 浏览器、PostgreSQL 或外部进程取消测试。文档修改不触碰签发/导出实现，未重跑非阻断签发套件。

## 5. M0 后续准入与可执行探针

外部适配剩余阻碍（不阻塞内部 harness）：原插件源码/精确版本、实际 DSH Host 与授权身份、合成文档 scope、第二 harness 部署身份尚未定位。不要使用生产文档或从现有密钥猜测授权。下一轮先获取这些运行输入，再执行以下最小序列：

1. 冻结实际 harness/插件和服务 SHA；记录经过脱敏的工具发现清单与 adapter 版本，和本页候选源码对比。
2. 在合成文档执行 prompt → 受控工具读/写 → 读取已提交修订；同时记录 task/session/request/operation/version 身份与原始事件种类。
3. 断开 follow 后由一致性游标重连；证明已提交操作无缺口。向同一会话追加用户修改，随后旧 baseVersion 写入必须冲突，再读取后继续。
4. 取消进行中的操作；分开记录 acceptance、终态、子进程停止与迟到提交拒绝，缺任一项保持 unknown。再重启服务/会话验证恢复不重复副作用。
5. 用第二真实 harness 重复支持项，记录明确 unsupported/unknown；再关闭 M0，估算 PR-B/C。

依赖更新：内部基线与消费者盘点（本次）→ 内部 harness 独立修复、PR-B 内部共享能力及 PR-C 耐久同步。插件/身份与真实探针（待办）只约束外部适配；Word/DSH 外部闭环仍依赖 B+C 和外部探针。所有 M0–M7 checkbox 保持未完成。本页是部分 PR-A 证据，不是产品功能交付。
