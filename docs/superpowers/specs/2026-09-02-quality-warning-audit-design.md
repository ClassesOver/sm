# 质量警告审计与接入设计

## 目标

在不改变 Reporting AgentOS 既有工作流步骤、Agno 重试/恢复语义和硬发布门禁的前提下，统一质量警告的接入、分类、去重、审计和发布回执。低风险问题允许随报告发布；影响结论可信度但仍可交付的问题标记为需复核；身份、权限、血缘、协议、脚本执行和产物完整性问题继续硬拒绝。

## 非目标

- 不把硬错误转换成质量警告。
- 不新增通用 Coding Agent 或独立工作流入口。
- 不让阶段代码直接访问 PostgreSQL 告警仓。
- 不改变章节动态生成、视觉审查或正式产物渲染逻辑。

## 分层架构

### 阶段接入层

`WarningEmitter` 是 Reporting 阶段内唯一的告警生产入口。它只创建不可变的 `WarningNotice`，保存当前 `reportRunId`、`revision` 和 `sourcePhase`，不访问数据库、不修改持久化状态。

生产方显式传入 `code`、`message`、`details` 和主体（`subjectType`、`subjectId`）。只有报告级告警可以使用 `report` 主体；禁止从任意 details 猜测主体。阶段结束时，notice 投影回现有 checkpoint/artifact 的 warnings 字段，保证 Agno 重试和恢复仍以现有状态为事实来源。

### 边界适配层

`WarningAdapter` 将现有 `SourceWarning`、分析 evidence warning、章节 artifact warning、渲染 warning 转换为统一 notice。适配器只在阶段边界使用：旧协议保持兼容，新代码不再手写多套 warning 字典。适配失败表示审计契约错误，不能静默丢弃：必须记录 `report_quality_warning_notice_invalid` 日志（含规则码与数量），并在审计摘要中给出 `invalidNoticeCount`。

### 发布审计层

`QualityAuditCollector` 在发布门禁内接收所有阶段 notice，执行：

1. 规则目录校验和 disposition 分类；
2. 主体和稳定 details 规范化；
3. 同一报告运行内跨阶段稳定去重；
4. 生成 `WarningAuditSummary`；
5. 在单一 `flush()` 边界按 `ruleCode + subjectType` 分组，调用新增的 `QualityWarningService.record_successful_checks` 批量接口。

`flush()` 对调用方是一次提交动作，但内部必须按 `CheckScope` 要求分组。持久化层提供 `record_successful_checks` 批量接口，在同一 PostgreSQL 事务中按稳定顺序获取各组 advisory lock、写入主记录和事件、解析已消失告警；任一组失败则整体回滚并作为系统错误返回。现有 `record_successful_check` 保留为单组兼容门面并委托批量实现。即使硬发布门禁有 issues，也要 flush 已完成的审计，避免丢失修复线索。

## 规则与发布语义

规则目录是代码内的不可变注册表，每个规则声明 disposition 和允许的主体类型：

- `informational`：仅记录，默认不要求人工复核；
- `quality_warning`：允许发布，必须出现在报告 warnings 中；
- `review_required`：允许生成交付物，但 `auditSummary.requiresReview=true`，由上层决定人工复核流程；
- 身份、权限、血缘、协议、脚本失败和产物完整性规则不注册到该目录，继续由硬门禁产生 issues。

未登记规则、主体缺失、主体类型不匹配或 details 不可规范化属于审计契约错误。按“语义业务校验只需软告警”，契约错误只跳过该条并记录日志与 `invalidNoticeCount`，不阻断正式发布；出现跳过时本次审计视为不完整，只记录发现，不关闭任何既有告警。新规则漏登记通过日志与摘要暴露，而不是拦截报告交付。

## 去重与事件审计

稳定 fingerprint 只使用规则、主体和明确的稳定 details，排除运行 ID、路径、时间、数值等动态字段，也不包含 source phase。这样同一根因跨分析、章节、渲染阶段只保留一条主记录。

主记录保存最新 disposition、message 和 source phase；本次检查事件额外保存合并后的 `sourcePhases`。同一 `warningId + checkId` 仍只产生一个事件，重试不会造成事件爆炸；新的 checkId 会递增 occurrence_count，并按完整成功检查的覆盖范围解析已消失告警。

## 持久化与 API

`QualityWarningRecord` 和 `QualityWarningEvent` 增加 `disposition`、`sourcePhase`（事件可使用 `sourcePhases`）字段，`WarningQuery` 支持按 disposition 查询。现有 PostgreSQL 表通过幂等的增量字段初始化兼容旧库，旧记录默认 `quality_warning`；不引入 SQLite 路径。

发布回执同时保留兼容的 `warnings` 列表，并新增结构化 `auditSummary`：总数、按 disposition 计数、按 source phase 计数、`requiresReview` 和本次 flush 结果。`issues` 只表示阻断原因，不能混入质量 warning。

## 稳定可靠性不变量

- **原子性**：一次发布审计的所有规则分组在同一数据库事务中提交；禁止出现只写入部分分组的“半次审计”。
- **幂等性**：`reportRunId + revision` 生成稳定 `checkId`；重复调用 flush 只返回已写入记录，不重复增加 occurrence_count 或事件。数据库继续以唯一约束作为最终防线。
- **重试与恢复**：审计收集结果先保存在当前 Workflow checkpoint，再执行 flush。进程在 flush 前崩溃时可从 checkpoint 重建；flush 中断时事务回滚，恢复后使用同一 checkId 重试。
- **确定性**：规则分组、主体集合、sourcePhases 和 details 按稳定排序后写入，保证重试、回放和多实例执行得到相同 fingerprint 与汇总。
- **并发安全**：批量锁按租户、领域、规则、主体类型的字典序获取，避免锁顺序不一致导致死锁；已有“完整成功复检才能 resolve”不变量保持不变。
- **资源边界**：单次审计限制 notice 数、规则组数、details 大小和汇总条目数；超限属于审计契约错误，按上条软处理（记录日志、审计不完整、不关闭既有告警），不静默截断。
- **失败可见**：flush 失败记录稳定的 Loguru 事件名和非敏感上下文；发布回执标记 `auditSummary.flushStatus=failed` 并返回系统错误，不能伪装成质量 warning。
- **兼容回退**：旧 checkpoint 没有 source phase 或 disposition 时由适配层使用明确默认值；无法安全推断主体或规则时失败关闭，不猜测、不丢弃。

## 数据流

阶段产生 notice -> 阶段 checkpoint 保存 warnings -> 发布门禁通过 WarningAdapter 汇总 -> QualityAuditCollector 分类/去重 -> 生成 auditSummary -> 单一 flush 持久化 -> 返回 issues/warnings/auditSummary。

## 测试与验收标准

- 规则目录覆盖所有当前可发布 warning，未登记规则失败关闭。
- emitter 要求显式主体，报告级主体例外，适配旧 SourceWarning 不丢字段。
- 同一根因跨阶段只生成一条主记录，sourcePhases 完整合并；相同 checkId 幂等。
- `review_required` 只设置 `requiresReview`，不影响 `formalReleaseAllowed`；硬错误仍阻断。
- 旧表/旧记录读取默认 disposition，API 可筛选 disposition。
- flush 按规则和主体分组并在单事务内提交，任一持久化失败整体回滚并抛出系统错误。
- 模拟进程崩溃、重复 flush、并发 flush 和数据库瞬时失败，验证恢复后无重复事件、无半次审计且 occurrence_count 正确。
- 发布回执的 issues、warnings、auditSummary 三者边界稳定，现有兼容字段不漂移。

实现前先运行质量警告模型/服务和发布门禁相关定点测试；实现后运行相同定点测试、Ruff、`py_compile` 和 `git diff --check`。
