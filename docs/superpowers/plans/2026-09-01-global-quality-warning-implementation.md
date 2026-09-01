# 全局质量告警 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立租户隔离、可查询、可自动复检关闭的全局质量告警后端，并让 Reporting 的可修复质量问题继续产出报告。

**Architecture:** 新增不依赖 Reporting 的 `smart_reporting/quality_warnings/` 领域包，使用 PostgreSQL 主表保存当前告警、事件表保存不可变历史；业务阶段只提交一次完整成功检查，服务在同一事务中 upsert 告警并按覆盖范围自动关闭已修复问题。Reporting 通过注入的 service 接入，checkpoint/manifest 仅保存本次快照和告警 ID。

**Tech Stack:** Python 3.12、Pydantic、FastAPI、SQLAlchemy AsyncEngine、PostgreSQL、Loguru、pytest/anyio。

---

## 文件结构

- Create: `smart_reporting/quality_warnings/__init__.py`，只导出稳定公共契约。
- Create: `smart_reporting/quality_warnings/models.py`，定义租户上下文、检查范围、finding、查询参数和返回模型。
- Create: `smart_reporting/quality_warnings/repository.py`，定义 PostgreSQL 表、repository protocol、SQLAlchemy 实现和 schema 初始化。
- Create: `smart_reporting/quality_warnings/service.py`，实现指纹、事务性成功检查、幂等聚合和查询。
- Create: `smart_reporting/quality_warnings/api.py`，提供只读 FastAPI router。
- Create: `smart_reporting/tests/test_quality_warnings.py`，纯单元和 API 契约测试。
- Create: `smart_reporting/tests/test_quality_warnings_persistence.py`，PostgreSQL integration 测试。
- Modify: `smart_reporting/application.py`、`smart_reporting/app.py`、`smart_reporting/reporting/bootstrap.py`，装配 service、schema startup 和查询 router。
- Modify: `smart_reporting/reporting/workflow/controller.py`、`smart_reporting/reporting/cli.py`、`smart_reporting/reporting/workflow/runtime/base.py`，传播可信租户上下文。
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`、`smart_reporting/reporting/tools/analysis.py`、`smart_reporting/reporting/tools/sections.py`、`smart_reporting/reporting/workflow/checkpoint.py`、`smart_reporting/reporting/workflow/runtime/publication.py`，把质量问题改为 finding 并接入成功检查。
- Modify: 对应 Reporting 契约测试文件，保留安全门禁失败用例并新增告警继续路径。

### Task 1: 定义通用告警契约和稳定指纹

**Files:**
- Create: `smart_reporting/quality_warnings/models.py`
- Create: `smart_reporting/quality_warnings/__init__.py`
- Test: `smart_reporting/tests/test_quality_warnings.py`

- [ ] **Step 1: 写失败测试**

覆盖以下行为：

```python
def test_fingerprint_ignores_run_and_dynamic_values():
    first = WarningFinding(
        rule_code="report_metric_definition_incomplete",
        subject_type="metric",
        subject_id="income_summary_total",
        message="指标定义不完整。",
        details={"missingFields": ["unit"], "value": 1},
    )
    second = first.model_copy(update={"details": {"missingFields": ["unit"], "value": 99}})
    assert warning_fingerprint(first) == warning_fingerprint(second)

def test_check_scope_requires_explicit_complete_coverage():
    with pytest.raises(ValidationError):
        CheckScope(domain="reporting", rule_code="r", subject_type="metric", covered_subject_ids=())
```

测试还必须断言：规则码、主体类型和主体 ID 非空且限长；`details` 只接受 JSON 结构并拒绝 token/capability/password 等敏感键；租户上下文只由内部模型构造，不从 HTTP 查询参数读取。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest smart_reporting/tests/test_quality_warnings.py -q`

Expected: FAIL，因为公共模型和指纹函数尚未存在。

- [ ] **Step 3: 实现最小契约**

定义不可变 Pydantic 模型：`TenantScope(database_name, company_id)`、`CheckScope(domain, rule_code, subject_type, covered_subject_ids)`、`WarningFinding(rule_code, subject_type, subject_id, severity, message, details)`、`WarningQuery`、`QualityWarningRecord`、`QualityWarningEvent`。`warning_fingerprint()` 对稳定字段和白名单 details 做排序 JSON 后计算 SHA-256；不得把 run/revision/time/dynamic value 纳入指纹。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest smart_reporting/tests/test_quality_warnings.py -q`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add smart_reporting/quality_warnings smart_reporting/tests/test_quality_warnings.py
git commit -m "feat: define global quality warning contracts"
```

### Task 2: 实现 PostgreSQL 主表、事件表和事务 repository

**Files:**
- Create: `smart_reporting/quality_warnings/repository.py`
- Test: `smart_reporting/tests/test_quality_warnings.py`
- Test: `smart_reporting/tests/test_quality_warnings_persistence.py`

- [ ] **Step 1: 写失败测试**

为 in-memory fake repository 写行为测试：首次 finding 创建 `open` 主记录和 `detected` 事件；相同 fingerprint 重复提交只保留一条主记录并递增 `occurrence_count`；同一成功检查重复调用不增加次数；成功复检覆盖主体且没有 finding 时写 `resolved`；未覆盖主体不关闭；事件不可变。

为 PostgreSQL integration 测试准备 `REPORTING_TEST_DB_URL` fixture，验证唯一键并发 upsert、事件数量、租户 A 不能读取租户 B、游标分页稳定。

- [ ] **Step 2: 运行定点测试确认失败**

Run: `pytest smart_reporting/tests/test_quality_warnings.py smart_reporting/tests/test_quality_warnings_persistence.py -q`

Expected: FAIL，因为 repository 尚未实现。

- [ ] **Step 3: 实现 PostgreSQL repository**

在独立 `MetaData` 中定义 `quality_warnings_v1` 和 `quality_warning_events_v1`。主表唯一键为 `(database_name, company_id, domain, rule_code, subject_type, subject_id, fingerprint)`；事件表以自增/UUID 事件 ID 为主键并禁止更新接口。repository 提供：`create_schema()`、`record_successful_check(scope, findings, context)`、`list_warnings(scope, query)`、`get_warning(scope, warning_id)`、`list_events(scope, warning_id)`。所有写入在一个 `engine.begin()` 事务内完成，使用 PostgreSQL `ON CONFLICT` 或等价锁定更新；所有查询先拼接租户条件。

- [ ] **Step 4: 加入安全日志**

使用 Loguru 记录 `quality_warning_recorded`、`quality_warning_resolved`、`quality_warning_persist_failed`，只记录租户哈希/稳定 ID、规则和主体，不记录 details 原文。

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest smart_reporting/tests/test_quality_warnings.py -q`

Expected: PASS。若设置 `REPORTING_TEST_DB_URL`，再运行：`pytest smart_reporting/tests/test_quality_warnings_persistence.py -q`，Expected: PASS；未设置时只报告 integration 被跳过。

- [ ] **Step 6: Commit**

```bash
git add smart_reporting/quality_warnings smart_reporting/tests/test_quality_warnings.py smart_reporting/tests/test_quality_warnings_persistence.py
git commit -m "feat: persist global quality warning history"
```

### Task 3: 装配全局 service、可信租户上下文和只读查询 API

**Files:**
- Modify: `smart_reporting/application.py`
- Modify: `smart_reporting/app.py`
- Modify: `smart_reporting/reporting/bootstrap.py`
- Modify: `smart_reporting/reporting/workflow/controller.py`
- Modify: `smart_reporting/reporting/cli.py`
- Modify: `smart_reporting/reporting/workflow/runtime/base.py`
- Create/Modify: `smart_reporting/quality_warnings/api.py`
- Test: `smart_reporting/tests/test_quality_warnings.py`
- Test: `smart_reporting/tests/test_reporting_request_identity.py`

- [ ] **Step 1: 写失败测试**

测试 `GET /quality-warnings` 默认只返回当前租户的 `open` 告警；详情和事件 endpoint 对其他租户的 UUID 返回 404；分页游标不重复、不漏项；HTTP 请求体不能覆盖租户条件。测试 Workflow dependency 必须包含 `database` 和 `companyId`，缺失时以 `report_workflow_context_missing` 失败。

- [ ] **Step 2: 实现装配和身份传播**

在 `ApplicationContext` 中注入 `QualityWarningService`，应用启动时调用 `create_schema()`，并把 router 挂到 base app。HTTP 查询从已验签 capability 的 `request.state.capability.database/company` 生成 `TenantScope`；无 capability 的全局查询请求拒绝，不使用默认租户。

扩展 Reporting workflow scope dependency 为 `externalRunId/threadId/userId/database/companyId`。HTTP facade、CLI 和恢复路径都必须提供同一可信 scope；runtime 的 `_scope()` 校验并返回租户字段，缺失即失败关闭。`QualityWarningService` 作为 runtime 构造依赖注入，不能在模块中创建全局连接。

- [ ] **Step 3: 实现三个只读接口**

实现 `GET /quality-warnings`、`GET /quality-warnings/{warning_id}`、`GET /quality-warnings/{warning_id}/events`，查询参数映射到 `WarningQuery`，默认 `status=open`，按 `last_observed_at DESC, warning_id DESC` 返回有限页，并使用安全的游标编码。

- [ ] **Step 4: 运行测试**

Run: `pytest smart_reporting/tests/test_quality_warnings.py smart_reporting/tests/test_reporting_request_identity.py -q`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add smart_reporting/application.py smart_reporting/app.py smart_reporting/reporting/bootstrap.py smart_reporting/reporting/workflow/controller.py smart_reporting/reporting/cli.py smart_reporting/reporting/workflow/runtime/base.py smart_reporting/quality_warnings smart_reporting/tests/test_quality_warnings.py smart_reporting/tests/test_reporting_request_identity.py
git commit -m "feat: expose tenant-scoped quality warning queries"
```

### Task 4: 接入确定性分析和语义目录，质量问题改为 finding

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Modify: `smart_reporting/reporting/tools/analysis.py`
- Modify: `smart_reporting/reporting/workflow/checkpoint.py`
- Test: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`
- Test: `smart_reporting/reporting/tests/test_reporting_semantic_contract.py`

- [ ] **Step 1: 写失败测试**

新增断言：

- `validate_metric_code_bindings()` 缺失时分析继续，产生 `report_metric_definition_incomplete` finding，缺失指标不进入权威 `metricDefinitions`。
- `_finalize_semantic_catalog()` 对 metric formula/unit/period 冲突返回 warning 集合而不是抛质量异常。
- `organizationGrain` 缺失产生 `report_dataset_grain_unknown`，输出明确 `unknown`，不默认 `record`。
- Dataset 越权、evidence 覆盖不全和身份不一致仍抛原错误码。

- [ ] **Step 2: 运行定点测试确认失败**

Run: `pytest smart_reporting/reporting/tests/test_reporting_tool_contracts.py::test_finalize_semantic_catalog_fails_closed_on_ambiguous_facts smart_reporting/reporting/tests/test_reporting_semantic_contract.py -q`

Expected: 新增降级测试 FAIL，现有安全门禁测试 PASS。

- [ ] **Step 3: 调整返回契约并接入 service**

将 `_finalize_semantic_catalog()` 返回值扩展为 `(dataset_semantics, metric_definitions, findings)`；完整一致的 metric 继续生成定义，不完整/冲突 metric 只生成 finding。调用方在阶段成功边界调用 `record_successful_check()`，并将返回的 `warning_id` 写入 manifest/checkpoint 快照。不要在此处捕获授权、哈希或路径异常。

将 `AnalysisEvidenceManifest` 的 metric/chart 关系校验改为：允许未定义的原始 `metricCodes`，但要求有对应 warning ID；有定义的 metric 继续严格校验。为 `AnalysisEvidenceManifest` 增加受限 `qualityWarningIds` 字段并验证 ID 不重复。

- [ ] **Step 4: 运行定点测试确认通过**

Run: `pytest smart_reporting/reporting/tests/test_reporting_tool_contracts.py smart_reporting/reporting/tests/test_reporting_semantic_contract.py -q`

Expected: PASS，且原有越权、证据覆盖和身份失败测试仍 PASS。

- [ ] **Step 5: Commit**

```bash
git add smart_reporting/reporting/workflow/runtime/analysis.py smart_reporting/reporting/tools/analysis.py smart_reporting/reporting/workflow/checkpoint.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py smart_reporting/reporting/tests/test_reporting_semantic_contract.py
git commit -m "feat: downgrade analysis quality gates to warnings"
```

### Task 5: 接入图表引用、章节 claim 和发布语义复检

**Files:**
- Modify: `smart_reporting/reporting/tools/sections.py`
- Modify: `smart_reporting/reporting/workflow/runtime/sections.py`
- Modify: `smart_reporting/reporting/workflow/runtime/publication.py`
- Modify: `smart_reporting/reporting/workflow/state.py`
- Test: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`
- Test: `smart_reporting/reporting/tests/test_reporting_semantic_contract.py`

- [ ] **Step 1: 写失败测试**

新增断言：

- `register_report_charts()` 对未知 metric code 返回 `ok=True`，完成文件检查和 durable 登记，并返回结构化 `report_chart_metric_unknown` warning。
- 分析冻结对缺失 metric definition 继续完成，告警 ID 出现在 manifest/checkpoint。
- 章节 claim 的已有 warning 行为保留，同时写入对应 global finding。
- 发布期间、粒度和跨源问题继续发布并写入 global finding。
- 图表文件变更、路径越界、非法草案、哈希漂移仍失败。

- [ ] **Step 2: 实现图表 finding**

将 `sections.py` 中 `report_chart_metric_unknown` 的异常分支改为 warning 列表；确保 warning 在 `register_charts` durable payload 中一并保存，避免只存在工具返回值。图表仍保留原始 metric code，不伪造定义。

- [ ] **Step 3: 实现冻结和发布检查提交**

将 `tools/analysis.py` 的 `report_analysis_metric_definition_missing` 改为 finding，并在完整冻结成功后提交该阶段的 `CheckScope`。发布语义 warning 统一转换为 finding 后提交 publish scope；只有检查成功且覆盖主体完整时才调用 reconciliation。

- [ ] **Step 4: 运行定点测试确认通过**

Run: `pytest smart_reporting/reporting/tests/test_reporting_tool_contracts.py smart_reporting/reporting/tests/test_reporting_semantic_contract.py -q`

Expected: PASS，原有安全和产物身份拒绝测试不得改变。

- [ ] **Step 5: Commit**

```bash
git add smart_reporting/reporting/tools/sections.py smart_reporting/reporting/workflow/runtime/sections.py smart_reporting/reporting/workflow/runtime/publication.py smart_reporting/reporting/workflow/state.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py smart_reporting/reporting/tests/test_reporting_semantic_contract.py
git commit -m "feat: record chart and publication quality warnings"
```

### Task 6: 全链路回归、格式检查和文档交付

**Files:**
- Modify: `docs/` only if public API or deployment instructions changed.
- Test: all files changed in Tasks 1-5.

- [ ] **Step 1: 运行定点和 PostgreSQL integration 测试**

Run: `pytest smart_reporting/tests/test_quality_warnings.py smart_reporting/tests/test_quality_warnings_persistence.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py smart_reporting/reporting/tests/test_reporting_semantic_contract.py -q`

Expected: 定点测试通过；未配置 `REPORTING_TEST_DB_URL` 时仅 integration 跳过并在交付说明中注明。

- [ ] **Step 2: 运行静态检查**

Run: `ruff format --check smart_reporting/quality_warnings smart_reporting/app.py smart_reporting/application.py smart_reporting/reporting smart_reporting/tests/test_quality_warnings.py`; `ruff check ...`; `git diff --check`

Expected: 全部退出码为 0。

- [ ] **Step 3: 运行必要的跨模块回归**

若 Task 3-5 修改了 Workflow scope、checkpoint 或公共 HTTP 路由，再运行：`pytest smart_reporting/tests/test_application.py smart_reporting/tests/test_reporting_request_identity.py smart_reporting/reporting/tests/test_reporting_integration.py smart_reporting/reporting/tests/test_reporting_workflow_controller.py -q`。

- [ ] **Step 4: 检查差异和敏感数据**

Run: `git status --short`; `git diff --stat`; `rg -n "token|capability|password|cookie|secret" smart_reporting/quality_warnings`。

Expected: 无临时产物、密钥、原始数据写入；现有用户改动未被覆盖。

- [ ] **Step 5: Commit**

```bash
git add smart_reporting docs
git commit -m "test: verify global quality warning workflow"
```

## 计划自检

- 规格中的全局中立包对应 Tasks 1-3；Reporting 接入对应 Tasks 4-5；PostgreSQL、租户隔离、事件历史和游标查询均有测试任务。
- 自动关闭只发生在 `record_successful_check()` 的完整覆盖范围内；检查失败、取消和部分覆盖没有 reconciliation 路径。
- 授权、证据覆盖、路径、哈希、产物身份和结构协议仍由原异常路径保护，未被质量 finding 捕获。
- 没有为人工关闭、UI、调度器或 SQLite 增加实现任务。
- 所有任务都给出具体文件、测试命令和预期结果；未使用 TODO/TBD 占位。
