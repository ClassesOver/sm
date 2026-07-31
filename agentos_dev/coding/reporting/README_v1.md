# Report Agent v1 规约

v1 的 Workflow ID 固定为 `enterprise-reporting-workflow-v1`。v1 只使用服务端注册的数据源，
请求、模型上下文和 Workflow state 均不得包含 host、用户名、密码或 DSN。数据源配置与覆盖规则见
[`data_source/README.md`](data_source/README.md)。

## 数据和语义边界

- 顶层 Workflow 输入严格区分自然语言 `{"version":"1","prompt":"..."}` 与现有
  `ReportRequestEnvelope v1`。Envelope 直接校验；自然语言由无工具结构化模型归一化，原文保持为
  `reportGoal`，单个明确年份转换为全年。期间缺失或冲突时首步通过 output review 暂停，补充内容
  作为 `rejection_feedback` 在同一 run 内重试。`sourceIds` 省略时使用配置文件中的
  `defaultSourceIds`。
- metadata DDL 是本次运行表范围的事实来源，并固化为不可变结构快照。实时 catalog 必须包含 DDL
  字段且类型兼容；额外字段、nullable 差异和 DECIMAL 参数差异不阻断只读分析。
- 数据理解阶段的输入表、模型选表和纠错候选统一使用
  `{"sourceId": "operations", "table": "reporting.income"}`；不向该阶段提供拆分的
  `database/name`、SQL 文件名或 `table.column` 引用。模型同时选择期间字段、期间粒度和业务角色。
- 数据理解输出不符合严格 Schema 或引用越界时，运行时一次反馈全部问题及规范候选，并在本步骤内
  最多调用模型五次；程序只做大小写归一化，不补全或拟合表和字段。该步骤关闭 Workflow 外层重试。
- DataShape 只执行聚合查询，不读取样本行。它记录全表和期间行数、期间外及期间字段空值行数、
  日期或年度期间覆盖与缺失、字段空值/基数/唯一性、数值分布、低基数 Top-K，以及 metadata revision、
  schema hash、统计版本和查询数。
- 服务端 Profile 通过显式继承解析为不可变 Effective Profile。Capability 只能根据 Snapshot 和
  DataShape 缩小可用维度、指标和章节；Profile 不能扩大数据源白名单。
- Profile 只作为模型可参考的业务上下文，不再充当字段、章节或对账策略白名单。
- 提纲只接收用户目标、期间和确定性生成的 OutlineShapeView，不直接接收无界的完整数据画像。
- 数据源、Schema 和 Profile 唯一确定时直接继续；仅在多个 metadata Agent 需要选择时暂停审核。
- `dimensionColumns` 声明 requirement 可用维度，`grainColumns` 声明本次查询共同粒度；每张表通过
  `periodColumn`/`periodGranularity` 声明期间语义，`measureColumns` 声明必须聚合的指标字段，多表
  requirement 通过 `relations` 显式声明关系和共同 join keys。

规划采用“强契约、弱校验”：模型必须返回完整结构化计划，但程序不规定具体表、字段、章节或分析
方法，只验证引用存在、范围未越界以及后续 SQL 与计划一致。

## SQL 审核边界

SQL 必须一次批量生成，并通过 SQLGlot AST 校验：单条只读、Snapshot 表字段白名单、requirement/source/表集合
一致、每张表包含完整且精确的期间条件、按完整共同粒度预聚合且聚合全部指标字段。跨表明细连接
一律拒绝；各表聚合 CTE 只能按全部共同粒度键连接。

审核保存规范化 SQL 和 SHA-256。执行阶段必须同时满足 SQL 原文和 hash 完全一致，不允许重写、
纠错或失败后自动生成替代 SQL。

## 成稿和发布边界

CodingTask 不提供数据库函数，也不采用 `execute_sql_query` 模式；它只能读取 Workflow 已原子提交的
不可变数据集。同一 workflow run 的暂停、恢复和报告 revision 共用稳定 CodingTask key。

PDF 由 Workflow 固定调用 WeasyPrint 渲染，模型不能选择引擎或页面 CSS。Effective Profile 只通过
`pageLayout.headerLeft/headerRight/footerLeft/footerRight` 定义页眉页脚格式，占位符限于
`{title}`、`{page}`、`{pages}`；页脚必须包含当前页和总页数。默认页眉左侧为
“上海鼎医信息技术有限公司”。PDF 验收会逐页检查解析后的页眉、页脚和页码。

`ReportArtifactManifest` 将 Markdown、图表、引用、数据集快照 hash 和报告 revision 绑定；
`PdfArtifactManifest` 必须完整保留图表、引用和关键章节。任何数据集、revision 或文件 hash 变化都会
使旧产物或下载 grant 失效。最终发布审核通过后，Workflow 的正式末步骤统一签发交付结果；Controller
不再复制发布终态。HTTP 发布结果只返回同源下载 URL，CLI 只返回本地路径、大小和 SHA-256。

PandasAI 不作为运行时依赖。v1 仅吸收其显式语义层、SQL AST 处理和类型化产物思想，不吸收连接
配置、模型生成代码直接执行、动态数据库函数或执行失败后自动修改 SQL。

## Metadata 与下载部署

外部 metadata 服务只使用两阶段 POST：`/get_agent_json`（请求 `{}`，响应
`{"agent_list": [...]}`）和 `/get_model_ddl_term_json`（请求 `{"agent_id": <正整数>}`）。
远端不提供 revision，服务按完整原始
DDL、模型说明和 term 计算 SHA-256。原始 DDL 与 SQLGlot 结构化结果一并保存在 Workflow state，
但不进入 CodingTask；超时、鉴权失败、5xx、非法 JSON、响应超限或 DDL 解析失败均终止 Workflow。

综合 AgentOS 的 HTTP 下载只在最终发布审核批准后签发，grant 原文只返回给调用方，数据库表
`report_download_grants_v1` 仅保存 SHA-256。下载请求必须携带当前 `X-AGUI-Thread` 和
`X-AGUI-Capability`；响应为 attachment，并设置 `Cache-Control: no-store` 和
`X-Content-Type-Options: nosniff`。应用会脱敏 Uvicorn access log，反向代理、网关及 APM 也必须对
`/reports/v1/download/*` 禁止记录原始路径。

独立 Report AgentOS 注册公开 `report-agent` 和其驱动的 `enterprise-reporting-workflow-v1`，不公开
worker Agent。Report worker 直接由报表配置和中立运行资源构造，不复制 Coding Agent，也不依赖
Coding CLI/AgentOS 产品入口。`/agui` 与 AgentOS Agent API 都通过原生 Agno Agent 入口执行；自然
语言只作为 `prompt` 原样进入 Workflow 首步，facade 不解析期间，内部审核、查询和恢复
仍使用同一个 Agno Workflow。Workflow 暂停后，facade 必须调用标记为
`requires_user_input` 的 `report_workflow_review`；`action`、`feedback` 和 `agent_id` 由 AgentOS
收集而不暴露给模型，工具再恢复同一持久化 Workflow run。原生 Workflow API 未提供项目私有
dependency 时，作用域直接来自 Agno
`RunContext.run_id/session_id/user_id`；恢复时使用 Workflow state。独立服务使用已验证的 Agno
`user_id` 和 Workflow thread 构造 `reporting` 发布作用域，并通过独立的 grant repository、发布
issuer 和同源下载 router 签发及校验 HTTP grant，不复用 Odoo capability scope；
`POST /agui/cancel` 使用 JWT 用户、`threadId` 和 `runId` 定位持久化 Workflow，取消后同步清理关联的
Report worker execution；
当前部署固定 `AGENT_OS_WORKERS=1`，确保 Agno 默认的进程内取消管理器与启动 controller 位于同一
进程。配置值大于 1 时服务拒绝启动；需要多 worker 时必须先接入 Agno 共享取消管理器并补充跨进程
取消契约测试。
CLI 使用独立发布器，只返回本地相对路径、大小和 SHA-256，不返回 URL。`cli_v2` 接受自然语言或
Envelope，直接运行同一个顶层 Workflow；每次暂停只修改最后一个未解决 requirement，并将完整
`step_requirements` 传给 Agno `acontinue_run`。既有 `cli` 继续保留 Controller/Envelope 兼容入口。
