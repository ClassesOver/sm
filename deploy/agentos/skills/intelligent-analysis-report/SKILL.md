---
name: intelligent-analysis-report
description: 从受控 StarRocks、已注册查询、DatasetHandle、工作区引用、Odoo 导出或混合来源生成企业智能运营分析报告。用于需要来源确认、动态提纲审核、分析计划、受控取数、Coding 分析、PDF 验收和最终发布审核的管理报表任务。
---

# 企业智能运营报表

严格通过报表 Workflow 推进。公开 Agent 只能使用以下工具：

- 新请求调用 `report_workflow_start`，传入完整报表目标；存在显式来源 ID 时同时传入 `source_ids`。
- 工具返回 `paused` 后，准确展示 `review`，等待用户明确决定。批准调用 `report_workflow_approve`；拒绝时把完整反馈传给 `report_workflow_reject`；明确取消时调用 `report_workflow_cancel`。
- 工具返回 `completed` 后，只返回 `report` 中的正式产物。不得把 `paused`、`running` 或 `failed` 描述为完成。
- 不得直接调用取数、SQL、Coding、工作区、PDF 或发布工具，也不得自行模拟 Workflow 阶段。内部 Workflow 和 `report-worker` 负责这些能力。

`agentos_plan` 只展示进度，不能替代来源绑定、`ReportOutline` 或 `AnalysisPlan`。

以下是内部 Workflow 的执行与验收约束，不是公开 Agent 的工具调用步骤。

## 1. 绑定来源

- 优先使用用户显式绑定的来源；查询失败时不得静默换源。
- 临时连接只接受系统注入的确认引用；批准后仅使用无密钥来源 binding。不得复述、记录、推断或请求工具返回密码或内部引用。
- 建连前展示脱敏 endpoint、数据库和允许表并等待确认。
- DDL 只作为元数据提示。以连接后的实际 catalog、字段和权限为准；不一致时停止并要求重新确认。
- 混合来源分别物化为 DatasetHandle，再在 Daytona 中关联；禁止跨库 SQL。

## 2. 受限画像

只读取生成提纲所需的信息：表结构、日期范围、期间覆盖、维度基数、空值和重复风险。提纲批准前不要执行完整业务分析。

## 3. 生成并审核提纲

根据目标和画像动态生成 `ReportOutline`，等待用户批准。拒绝时吸收反馈重新生成，不绕过审核。

医院运营分析通常评估以下章节，但应按实际数据动态取舍：

- 管理摘要
- 收入规模与结构
- 收入及工作量预算达成
- 支出与项目预算执行
- 成本结构与收支效率
- 工作量与资源效率
- 院区、科室排名和异常
- 差异归因及管理建议

## 4. 制定分析计划

生成 `AnalysisPlan`。综合、同比、环比和归因必须逐项选择 `execute` 或 `not_applicable` 并说明原因，可按需增加趋势、异常、Top N 和钻取。

- 同比优先使用上一年可比期间；数据缺失时标记 `not_applicable`。
- 环比只使用上一连续月份；月份不连续时标记 `not_applicable`。
- 不预设结论，只声明待验证方法、口径和证据。

## 5. 声明并物化数据

- 为每项分析创建 `DataRequirement`，声明 binding、指标、维度、粒度、期间、对比期间和用途，不在需求中直接写 SQL。
- SQL 只允许服务端 provider 生成、校验和执行。
- 每张事实表先按一致粒度分别聚合。禁止直接连接不同粒度明细，避免收入、成本或工作量倍增。
- 累计指标不得跨期间直接求和。
- 后续分析只引用不可变 DatasetHandle；来源范围或元数据指纹变化后重新开始。

## 6. Coding 分析与成稿

把 AnalysisPlan 和 DatasetHandle 交给 Coding Agent，在当前 Daytona 工作区完成口径核验、统计、归因、图表和 Markdown。不得向 Coding Agent 提供数据库凭据或允许其自行连接数据库。

对空数据、指标无法对账、对比期不足和粒度冲突明确失败或标记不适用，不编造结果。

## 7. 验收与发布

渲染 PDF，检查页数、空白页、图表和 Markdown 引用，只有验收通过后才进入发布审核。最终审核批准后返回正式 Markdown、PDF 和完整 DatasetHandle 血缘；拒绝或取消时清理本轮临时连接和未发布状态。
