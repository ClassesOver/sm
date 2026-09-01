# 全局质量告警与 Reporting 降级设计

## 目标与范围

本期建立可供全系统复用的质量告警能力。它让 Reporting 在遇到可修复的数据、指标、图表和语义质量问题时继续产出结果，同时将问题可靠地记录下来，供后续修复和成功复检自动关闭。

首期只提供后端记录与查询能力。不会提供人工确认、豁免、关闭或修改告警的接口，也不会回填现有字符串 warning。

质量降级不适用于授权和可信性边界。Dataset 授权与覆盖、证据身份、路径、哈希、产物身份、结构化协议、资源上限继续失败关闭。

## 领域边界

新增 `smart_reporting/quality_warnings/`，包含：

- 标准 Pydantic 契约：告警发现项、检查范围、查询条件和返回模型。
- PostgreSQL repository：主表和不可变事件表的读写。
- service：一次成功检查的事务性记录、幂等聚合、自动复检关闭和查询。
- HTTP router：只读查询接口。

该包是中立基础设施，不能反向导入 `reporting/`。Reporting 分析、图表、章节和发布模块只生成标准检查结果，并调用 service；不直接操作 SQL，也不自行维护历史告警状态。报告 checkpoint 和 manifest 只保存本次告警快照及 `qualityWarningIds` 回链，不能作为历史来源。

## 告警生命周期

一个问题由同一租户、领域、规则、主体和稳定根因指纹定义。首次发现创建 `open` 告警；同一问题在后续成功检查中再次发现时更新主记录、递增出现次数，并写入 `rechecked_open` 事件。

只有一次检查成功、明确声明覆盖了该主体、且该主体未再产生同一规则的对应问题，才可自动将该告警更新为 `resolved` 并写入 `resolved` 事件。检查失败、取消、跳过或仅覆盖部分主体时不进行 reconciliation，绝不关闭既有告警。

```text
成功检查 + findings
  -> 同事务 upsert open / 写 detected 或 rechecked_open event
  -> 仅对该检查范围内已覆盖而本次未发现的问题写 resolved event

检查失败或覆盖不完整
  -> 不调用 reconciliation
  -> 既有 open 告警保持不变
```

告警落库是质量降级继续执行的前提。若质量告警无法在 PostgreSQL 中持久化，必须以基础设施失败结束当前阶段并允许重试；不得吞掉问题后继续生成没有修复记录的报告。

## 数据模型

### `quality_warnings_v1`

| 字段 | 说明 |
| --- | --- |
| `warning_id` | UUID 主键，对外稳定标识。 |
| `database_name`、`company_id` | 可信执行上下文给出的租户边界。 |
| `domain` | 业务领域，例如 `reporting`。 |
| `rule_code` | 稳定英文规则码。 |
| `subject_type`、`subject_id` | 问题主体，例如 `metric/income_summary_total`。 |
| `fingerprint` | 规则、主体、稳定根因的 SHA-256。 |
| `status` | `open` 或 `resolved`。 |
| `severity` | 首期固定为 `warning`，保留扩展空间。 |
| `message`、`details` | 当前中文修复说明和受控、脱敏的定位数据。 |
| `first_observed_at`、`last_observed_at`、`resolved_at` | 生命周期时间。 |
| `occurrence_count` | 发现次数。 |
| `last_check_id` | 最近一次成功检查标识。 |
| `version` | 乐观并发控制。 |

唯一键为 `(database_name, company_id, domain, rule_code, subject_type, subject_id, fingerprint)`。查询索引覆盖 `(database_name, company_id, domain, status, last_observed_at DESC, warning_id DESC)`，并为规则、主体和首次发现时间提供相应复合索引。

### `quality_warning_events_v1`

事件表只追加，记录 `detected`、`rechecked_open` 和 `resolved`。每条事件保存 `warning_id`、租户键、检查标识、事件时间、来源运行上下文，以及当时的脱敏详情。`report_run_id`、`revision`、`thread_id`、`user_id`、`session_id` 仅记录在事件中，不能参与主问题身份，避免一次问题被每次运行拆分。

两张表均只支持 PostgreSQL。`details` 采用字段白名单、JSON 大小限制和敏感字段拒绝策略；不得保存原始 Dataset 数据、文件内容、token、capability、Cookie、密码或密钥。

## 指纹与检查协议

`fingerprint` 只使用稳定根因，例如指标代码和缺失字段、图表 ID 与未冻结指标代码。它不得包含时间、报告 revision、运行 ID、动态数值或用户会话信息。

业务模块以一个完整的成功检查调用 service：

```python
await quality_warning_service.record_successful_check(
    check_scope=CheckScope(
        domain="reporting",
        rule_code="report_metric_definition_incomplete",
        subject_type="metric",
        covered_subject_ids=("income_summary_total",),
    ),
    findings=(...),
    context=trusted_execution_context,
)
```

`CheckScope` 的租户信息只从可信执行上下文取得，不允许调用方在请求体中指定。单次调用只能关闭同一 `domain`、`rule_code`、`subject_type` 和已声明 `covered_subject_ids` 中的 open 告警；不同阶段使用各自明确的 rule code，不能互相关闭。

## HTTP 查询接口与权限

首期提供：

- `GET /quality-warnings`
- `GET /quality-warnings/{warning_id}`
- `GET /quality-warnings/{warning_id}/events`

列表支持 `domain`、`status`、`ruleCode`、`subjectType`、`subjectId`、`firstObservedAfter`、`lastObservedBefore` 和基于 `(last_observed_at, warning_id)` 的游标分页；默认只返回 `open`，排序为 `last_observed_at DESC, warning_id DESC`。

读取接口从可信请求身份获取 `database_name` 和 `company_id`，并在所有查询条件中强制加入这两个值。`warning_id` 详情和事件接口同样必须先按租户过滤，禁止通过全局 UUID 推测其他租户的数据。首期不提供任何写入型 HTTP 接口。

## Reporting 接入与契约调整

| 阶段 | 问题 | 降级行为 |
| --- | --- | --- |
| 确定性分析 | 指标定义缺失、formula/unit/期间不完整或冲突 | 写 `metric` 告警；该指标不生成权威定义。 |
| 语义目录 | `organizationGrain` 缺失 | 写 `dataset` 告警；记录为未知，禁止伪造为 `record`。 |
| 图表登记 | 图表引用未冻结指标 | 允许登记，写 `chart` 告警。 |
| 分析冻结 | facts 或图表引用没有完整指标定义 | 允许冻结，写对应 `metric/chart` 告警。 |
| 发布语义校验 | 期间、粒度、跨源推断不一致 | 保持非阻断，统一写入告警中心。 |

`AnalysisEvidenceManifest` 当前要求图表引用的全部指标都存在于 `metricDefinitions`。该规则必须调整为允许保留无权威定义的原始 `metricCodes`，并增加该项对应的 `qualityWarningIds`。有完整定义的指标仍沿用原校验；正文或图表不得把未定义指标显示为已验证口径。

每个阶段仅在自身检查完整成功时提交对应的 `CheckScope`。现有 `warnings` 字段继续作为用户可见的本次运行快照，但统一改用结构化规则码和告警 ID；其 500 条上限不影响全局告警历史。

## 错误处理与日志

质量检查本身发现问题时不抛质量拒绝异常；它构造 finding 并在成功写入告警中心后继续流程。告警服务写入失败、事务冲突超过可重试范围或租户上下文缺失属于基础设施/身份错误，必须失败关闭。

新增应用日志使用 Loguru 和稳定英文事件名，例如 `quality_warning_recorded`、`quality_warning_resolved`、`quality_warning_persist_failed`，仅带 `warning_id`、域、规则、主体和租户的安全标识，绝不记录 `details` 原文或敏感数据。

## 验证策略

- 单元测试：指纹稳定性、首次发现、重复发现幂等、成功复检关闭、部分覆盖不关闭、失败检查不关闭、详情敏感字段拒绝。
- PostgreSQL integration 测试：并发 upsert、唯一键聚合、不可变事件历史、租户隔离、游标分页。
- HTTP 测试：查询过滤、默认 open、详情与事件的租户隔离、无写入路由。
- Reporting 契约测试：指标定义问题、未知图表指标和发布语义问题均可继续并写入全局告警；Dataset 越权、证据覆盖错误、哈希漂移、路径越界和结构契约错误仍失败。
- 保留已存在的“同一指标跨期间”修复测试；它是误报修复，不是质量告警降级。

## 非目标

- 人工确认、豁免、关闭、修复工单和 UI。
- 通用规则调度器或后台批量复检任务。
- 从旧 checkpoint/manifest 的字符串 warning 回填历史。
- SQLite 或其他非 PostgreSQL 持久化兼容层。
