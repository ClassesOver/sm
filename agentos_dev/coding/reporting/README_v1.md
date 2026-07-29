# Report Agent v1 规约

v1 的 Workflow ID 固定为 `enterprise-reporting-workflow-v1`。v1 只使用服务端注册的数据源，
请求、模型上下文和 Workflow state 均不得包含 host、用户名、密码或 DSN。数据源配置与覆盖规则见
[`data_source/README.md`](data_source/README.md)。

## 数据和语义边界

- 所有入口先转换为严格的 `ReportRequestEnvelope`。`sourceIds` 省略时使用配置文件中的
  `defaultSourceIds`。
- metadata API 与 DDL 只允许缩小服务端表白名单，并必须与实时 catalog 的表、字段、类型和可空性
  一致。
- DataShape 只执行聚合查询，不读取样本行。它记录全表和期间行数、期间外及期间字段空值行数、
  日期或年度期间覆盖与缺失、字段空值/基数/唯一性、数值分布、低基数 Top-K，以及 metadata revision、
  schema hash、统计版本和查询数。
- 服务端 Profile 通过显式继承解析为不可变 Effective Profile。Capability 只能根据 Snapshot 和
  DataShape 缩小可用维度、指标和章节；Profile 不能扩大数据源白名单。
- Profile 显式声明的 reconciliation 在提纲前按共同粒度聚合并对账；没有规则时不猜测表关系。
- 提纲只接收用户目标、期间和确定性生成的 OutlineShapeView，不直接接收无界的完整数据画像。
- 数据源、Schema 和 Profile 唯一确定时直接继续；仅在多个 metadata Agent 需要选择时暂停审核。
- `dimensionColumns` 声明 requirement 可用维度，`grainColumns` 声明本次查询共同粒度；每张表通过
  `measureColumns` 声明必须聚合的指标字段，多表 requirement 通过 `relations` 显式声明关系和共同
  join keys。

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
使旧产物或下载 grant 失效。HTTP 发布结果只返回同源下载 URL，CLI 只返回本地路径、大小和 SHA-256。

PandasAI 不作为运行时依赖。v1 仅吸收其显式语义层、SQL AST 处理和类型化产物思想，不吸收连接
配置、模型生成代码直接执行、动态数据库函数或执行失败后自动修改 SQL。

## Metadata 与下载部署

外部 metadata 服务只使用两阶段 POST：`/get_agent_json`（请求 `{}`）和
`/get_model_ddl_term_json`（请求 `{"agent_id": <正整数>}`）。远端不提供 revision，服务按完整原始
DDL、模型说明和 term 计算 SHA-256。原始 DDL 与 SQLGlot 结构化结果一并保存在 Workflow state，
但不进入 CodingTask；超时、鉴权失败、5xx、非法 JSON、响应超限或 DDL 解析失败均终止 Workflow。

综合 AgentOS 的 HTTP 下载只在最终发布审核批准后签发，grant 原文只返回给调用方，数据库表
`report_download_grants_v1` 仅保存 SHA-256。下载请求必须携带当前 `X-AGUI-Thread` 和
`X-AGUI-Capability`；响应为 attachment，并设置 `Cache-Control: no-store` 和
`X-Content-Type-Options: nosniff`。应用会脱敏 Uvicorn access log，反向代理、网关及 APM 也必须对
`/reports/v1/download/*` 禁止记录原始路径。

独立 Report AgentOS 默认没有 Odoo database/company/session scope，因此不签发 HTTP grant；最终批准
会失败关闭。CLI 使用独立发布器，只返回本地相对路径、大小和 SHA-256，不返回 URL。
