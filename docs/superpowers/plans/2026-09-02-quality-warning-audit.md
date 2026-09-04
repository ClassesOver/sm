# Quality Warning Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持 Reporting AgentOS 硬门禁和 Agno 重试/恢复语义不变的前提下，建立统一的质量警告接入、分层、跨阶段去重、可靠持久化和发布审计回执。

**Architecture:** 阶段只通过 `WarningEmitter` 生成不可变 notice；`WarningAdapter` 在发布边界转换现有 warning 协议；`QualityAuditCollector` 负责规则校验、分类、稳定去重和汇总。Collector 使用 PostgreSQL 批量事务接口一次性写入所有规则组，旧单组服务接口继续作为兼容门面。

**Tech Stack:** Python 3.12、Pydantic、FastAPI、Agno 3.0.0、SQLAlchemy async、PostgreSQL、pytest、Loguru。

---

## 文件结构与责任

- Create: `smart_reporting/quality_warnings/policy.py`：不可变规则目录和 disposition 分类。
- Create: `smart_reporting/quality_warnings/audit.py`：`WarningEmitter`、`WarningAdapter`、`QualityAuditCollector`、汇总模型。
- Modify: `smart_reporting/quality_warnings/models.py`：统一 notice、disposition/source phase、批量检查契约和查询字段。
- Modify: `smart_reporting/quality_warnings/repository.py`：批量原子写入、增量 schema 初始化、事件来源阶段保存。
- Modify: `smart_reporting/quality_warnings/service.py`：批量服务门面，单组 API 委托批量 API。
- Modify: `smart_reporting/quality_warnings/api.py`：按 disposition 筛选。
- Modify: `smart_reporting/quality_warnings/__init__.py`：稳定公共导出。
- Modify: `smart_reporting/reporting/workflow/runtime/publication.py`：统一适配、汇总、flush 和 `auditSummary` 回执。
- Create: `smart_reporting/tests/test_quality_warning_audit.py`：接入、规则、去重和可靠性单元测试。
- Modify: `smart_reporting/tests/test_quality_warnings.py`：模型/API 契约测试。
- Modify: `smart_reporting/tests/test_quality_warnings_persistence.py`：PostgreSQL 批量事务和幂等测试。
- Modify: `smart_reporting/reporting/tests/test_reporting_semantic_contract.py`：发布分类回归。
- Modify: `smart_reporting/reporting/tests/test_reporting_section_concurrency.py`：发布门禁审计回执回归。

### Task 1: 定义规则目录与统一契约

**Files:**
- Create: `smart_reporting/quality_warnings/policy.py`
- Modify: `smart_reporting/quality_warnings/models.py`
- Modify: `smart_reporting/quality_warnings/__init__.py`
- Test: `smart_reporting/tests/test_quality_warning_audit.py`
- Test: `smart_reporting/tests/test_quality_warnings.py`

- [ ] **Step 1: Write failing tests for dispositions and explicit subjects**

```python
def test_registered_rule_exposes_disposition_and_subject_types() -> None:
    rule = get_warning_rule("report_period_basis_conflict")
    assert rule.disposition == "review_required"
    assert "section_claim" in rule.subject_types


def test_unknown_rule_is_rejected() -> None:
    with pytest.raises(QualityWarningContractError, match="规则未登记"):
        WarningEmitter(source_phase="publication").emit(
            code="unregistered_rule",
            subject_type="report",
            subject_id="run-1",
            message="未知规则",
        )
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `.venv/bin/python -m pytest smart_reporting/tests/test_quality_warning_audit.py -k "registered_rule or unknown_rule" -q`

Expected: FAIL because the rule registry and emitter contract do not exist.

- [ ] **Step 3: Add the immutable rule and model contracts**

Implement `policy.py` with a frozen `WarningRule` containing `code`, `disposition`, and `subject_types`, plus `get_warning_rule(code)` that raises `QualityWarningContractError` for unregistered rules. Register every current publishable warning code from `sections.py`, `analysis.py`, `publication.py`, and `SourceWarning`; do not register identity, lineage, protocol, path, script, or artifact-integrity failures.

Extend `WarningFinding` with `disposition: Literal["informational", "quality_warning", "review_required"]` and `source_phase: NonEmptyIdentity`, with aliases `sourcePhase`. Add `WarningNotice` as the emitter input/output contract with explicit `subject_type`, `subject_id`, bounded details, and `source_phase`. Add `WarningCheck` containing `CheckScope`, `findings`, and `CheckContext`; add `disposition` to `WarningQuery` and `QualityWarningRecord`. Existing records default to `quality_warning` when read from rows.

- [ ] **Step 4: Run focused tests and format**

Run: `.venv/bin/python -m pytest smart_reporting/tests/test_quality_warning_audit.py smart_reporting/tests/test_quality_warnings.py -q`

Expected: PASS for rule lookup, unknown-rule rejection, explicit subject validation, legacy defaults, and existing warning tests.

- [ ] **Step 5: Commit**

```bash
git add smart_reporting/quality_warnings/policy.py smart_reporting/quality_warnings/models.py smart_reporting/quality_warnings/__init__.py smart_reporting/tests/test_quality_warning_audit.py smart_reporting/tests/test_quality_warnings.py
git commit -m "feat(reporting): define quality warning audit contracts"
```

### Task 2: Implement emitter, adapters, collector and deterministic summary

**Files:**
- Create: `smart_reporting/quality_warnings/audit.py`
- Modify: `smart_reporting/quality_warnings/__init__.py`
- Test: `smart_reporting/tests/test_quality_warning_audit.py`

- [ ] **Step 1: Write failing tests for adapters and cross-phase deduplication**

```python
def test_collector_merges_same_root_cause_and_keeps_source_phases() -> None:
    collector = QualityAuditCollector(report_run_id="run-1", revision=2)
    collector.extend(
        (
            WarningEmitter(source_phase="analysis").emit(
                code="report_period_basis_conflict",
                subject_type="section_claim",
                subject_id="claim-1",
                message="期间口径冲突",
                details={"claimId": "claim-1", "field": "periodBasis"},
            ),
            WarningEmitter(source_phase="publication").emit(
                code="report_period_basis_conflict",
                subject_type="section_claim",
                subject_id="claim-1",
                message="期间口径冲突（发布复核）",
                details={"claimId": "claim-1", "field": "periodBasis"},
            ),
        )
    )
    audit = collector.build()
    assert len(audit.findings) == 1
    assert audit.findings[0].source_phases == ("analysis", "publication")
    assert audit.requires_review is True


def test_source_warning_adapter_preserves_dataset_references() -> None:
    notice = WarningAdapter.from_source_warning(
        source_warning, source_phase="analysis"
    )
    assert notice.details["datasetIds"] == ["dataset-1"]
```

- [ ] **Step 2: Run tests and verify the new behavior fails**

Run: `.venv/bin/python -m pytest smart_reporting/tests/test_quality_warning_audit.py -q`

Expected: FAIL because adapter and collector implementations are absent.

- [ ] **Step 3: Implement the three-layer audit API**

Implement `WarningEmitter.emit()` and `.extend()` so callers must provide `subject_type` and `subject_id`; only `subject_type="report"` may use a report-level ID. The emitter validates the rule registry and creates immutable `WarningNotice` values without database access.

Implement `WarningAdapter.from_source_warning()`, `.from_mapping()`, and `.from_notice()` at the boundary. Mapping conversion must reject missing/ambiguous subjects instead of selecting `claimId/chartId/sectionCode` by precedence. Existing `SourceWarning` dataset/query references must be copied into details without sensitive values.

Implement `QualityAuditCollector.add()/extend()/build()/flush()`. `build()` sorts by `(rule_code, subject_type, subject_id, fingerprint)`, merges equal fingerprints, sorts `source_phases`, counts dispositions and phases, and sets `requires_review` when any finding is `review_required`. A notice without a registered rule or valid subject raises `QualityWarningContractError`. `flush()` returns an awaitable result and delegates persistence to the batch service only after `build()` succeeds.

- [ ] **Step 4: Verify deterministic and bounded behavior**

Run: `.venv/bin/python -m pytest smart_reporting/tests/test_quality_warning_audit.py -q`

Expected: PASS, including reversed input order producing identical fingerprints and summaries, duplicate notices collapsing to one finding, source phase union, unknown rule rejection, and notice/detail count limits.

- [ ] **Step 5: Commit**

```bash
git add smart_reporting/quality_warnings/audit.py smart_reporting/quality_warnings/__init__.py smart_reporting/tests/test_quality_warning_audit.py
git commit -m "feat(reporting): add warning emitter and audit collector"
```

### Task 3: Add atomic PostgreSQL batch persistence and schema compatibility

**Files:**
- Modify: `smart_reporting/quality_warnings/repository.py`
- Modify: `smart_reporting/quality_warnings/service.py`
- Modify: `smart_reporting/quality_warnings/models.py`
- Test: `smart_reporting/tests/test_quality_warnings_persistence.py`

- [ ] **Step 1: Write failing persistence tests**

Add tests that call `record_successful_checks()` with two rule groups and assert both records are visible; call it twice with the same `check_id` and assert `occurrence_count` and event count do not increase; make the second group fail and assert no first-group row remains; run two concurrent batches and assert no deadlock or incorrect resolve.

- [ ] **Step 2: Run the PostgreSQL-focused tests and verify failure**

Run: `.venv/bin/python -m pytest smart_reporting/tests/test_quality_warnings_persistence.py -q`

Expected: FAIL because the batch protocol, schema columns, and atomic implementation do not exist. Tests requiring PostgreSQL remain marked `integration` and use the existing isolated database fixture.

- [ ] **Step 3: Implement the batch protocol and service validation**

Add `record_successful_checks(tenant, checks)` to the repository and service protocols. Validate every finding against its own `CheckScope`, reject empty batches and duplicate check IDs, and require all checks to use the same tenant. Keep `record_successful_check()` as a one-element wrapper calling the batch method.

- [ ] **Step 4: Implement one-transaction persistence**

Move the current upsert/resolve body behind a transaction accepting all checks. Sort scopes by `(domain, rule_code, subject_type)` before `pg_advisory_xact_lock`; deduplicate findings by stable fingerprint; upsert `disposition`, `source_phase`, message and details; append one event per `warning_id + check_id` with merged `sourcePhases` stored inside the existing event `details` JSONB; resolve absent covered warnings only after every group has been processed. Let any exception roll back the entire transaction and log `quality_warning_batch_persist_failed` with non-sensitive scope/count fields.

- [ ] **Step 5: Make schema initialization idempotent**

Keep `metadata.create_all` for new databases, then execute PostgreSQL `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for `disposition` and `source_phase`, set existing rows to `quality_warning`, and add non-null defaults. Event source phases remain in the already validated `details` JSONB payload, so no event-table schema change is required. Do not add SQLite or another database dialect.

- [ ] **Step 6: Verify persistence and commit**

Run: `.venv/bin/python -m pytest smart_reporting/tests/test_quality_warnings_persistence.py -q`

Expected: PASS for atomicity, idempotency, concurrent ordering, resolution, tenant isolation, and old-row compatibility.

```bash
git add smart_reporting/quality_warnings/models.py smart_reporting/quality_warnings/repository.py smart_reporting/quality_warnings/service.py smart_reporting/tests/test_quality_warnings_persistence.py
git commit -m "feat(reporting): persist quality audit atomically"
```

### Task 4: Integrate the collector with the publication gate

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/publication.py`
- Modify: `smart_reporting/reporting/workflow/checkpoint.py` only if a structured audit summary must be checkpointed
- Test: `smart_reporting/reporting/tests/test_reporting_semantic_contract.py`
- Test: `smart_reporting/reporting/tests/test_reporting_section_concurrency.py`

- [ ] **Step 1: Add failing publication tests**

Assert that a `review_required` semantic finding leaves `formalReleaseAllowed` true and returns `auditSummary.requiresReview` true; assert that unknown warning mappings become a blocking audit-contract issue; assert that analysis, section and publication copies of one root cause result in one finding with all source phases; assert that hard dataset/path/artifact issues remain in `issues` and are never persisted as quality warnings.

- [ ] **Step 2: Run the focused publication tests and verify failure**

Run: `.venv/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_semantic_contract.py smart_reporting/reporting/tests/test_reporting_section_concurrency.py -q`

Expected: FAIL because publication currently guesses subjects and loops over `record_successful_check()` directly.

- [ ] **Step 3: Replace ad-hoc grouping with one collector**

In `_dataset_publication_gate`, instantiate one collector with stable `report_run_id`, `revision`, and phase metadata. Add source warnings, evidence warnings, section artifact warnings, semantic warnings, and render warnings through their adapters. Keep the existing `issues` construction untouched for hard gates. Call `audit = collector.build()` once, then `await collector.flush(service, tenant, context)` once. Do not infer subjects from arbitrary dictionaries in publication code.

- [ ] **Step 4: Return the structured audit result**

Return `auditSummary` containing `total`, `byDisposition`, `bySourcePhase`, `requiresReview`, and `flushStatus`; leave the existing `warnings` list unchanged for compatibility. Set `formalReleaseAllowed` to `not issues`, independent of `requiresReview`. If collector validation or flush fails, raise `ReportingError("report_quality_audit_failed", ...)` and preserve the non-sensitive Loguru event.

- [ ] **Step 5: Verify publication semantics and commit**

Run: `.venv/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_semantic_contract.py smart_reporting/reporting/tests/test_reporting_section_concurrency.py -q`

Expected: PASS with unchanged hard-gate behavior and explicit audit summary boundaries.

```bash
git add smart_reporting/reporting/workflow/runtime/publication.py smart_reporting/reporting/tests/test_reporting_semantic_contract.py smart_reporting/reporting/tests/test_reporting_section_concurrency.py
git commit -m "feat(reporting): integrate structured warning audit"
```

### Task 5: Expose disposition filtering and finish reliability regression coverage

**Files:**
- Modify: `smart_reporting/quality_warnings/api.py`
- Modify: `smart_reporting/quality_warnings/models.py`
- Modify: `smart_reporting/quality_warnings/__init__.py`
- Test: `smart_reporting/tests/test_quality_warnings.py`
- Test: `smart_reporting/tests/test_quality_warnings_persistence.py`

- [ ] **Step 1: Add API filtering tests**

Call `GET /quality-warnings?disposition=review_required` with a verified capability and assert the service receives `WarningQuery(disposition="review_required")`; pass an invalid disposition and assert FastAPI returns 422; verify tenant isolation remains unchanged.

- [ ] **Step 2: Implement query plumbing**

Add `disposition` to `WarningQuery`, repository conditions, and API query parameters with alias `disposition`. Export all new public contracts. Keep status default `open` and existing cursor semantics unchanged.

- [ ] **Step 3: Add crash/retry/concurrency tests**

Use a fake repository to make `flush()` fail once then succeed and assert the collector reuses the same check ID and produces no duplicate findings. Use a transaction failure injection in the PostgreSQL fixture and assert both rule groups roll back. Run two identical concurrent flushes and assert one detected event plus one idempotent replay.

- [ ] **Step 4: Run the complete focused suite and static checks**

Run:

```bash
.venv/bin/python -m pytest smart_reporting/tests/test_quality_warning_audit.py smart_reporting/tests/test_quality_warnings.py smart_reporting/tests/test_quality_warnings_persistence.py smart_reporting/reporting/tests/test_reporting_semantic_contract.py smart_reporting/reporting/tests/test_reporting_section_concurrency.py -q
.venv/bin/ruff format --check smart_reporting/quality_warnings smart_reporting/reporting/workflow/runtime/publication.py smart_reporting/tests smart_reporting/reporting/tests
.venv/bin/ruff check smart_reporting/quality_warnings smart_reporting/reporting/workflow/runtime/publication.py smart_reporting/tests smart_reporting/reporting/tests
.venv/bin/python -m py_compile smart_reporting/quality_warnings/*.py smart_reporting/reporting/workflow/runtime/publication.py
git diff --check
```

Expected: all focused tests pass; Ruff, compilation, and diff checks pass. Full repository checks are only needed if cross-module failures appear.

- [ ] **Step 5: Commit**

```bash
git add smart_reporting/quality_warnings/api.py smart_reporting/quality_warnings/models.py smart_reporting/quality_warnings/__init__.py smart_reporting/tests/test_quality_warnings.py smart_reporting/tests/test_quality_warnings_persistence.py
git commit -m "test(reporting): verify quality audit reliability"
```

## Plan Self-Review

- Spec coverage: emitter/adapter/collector, rule dispositions, cross-phase deduplication, atomic batch persistence, idempotent retry/recovery, deterministic ordering, resource limits, API filtering, and publication `auditSummary` are covered by Tasks 1-5.
- Hard gates remain outside the rule registry and continue to populate `issues`; no task converts identity, lineage, protocol, script, path, or artifact failures into warnings.
- No task introduces SQLite, a generic Coding Agent, a new Reporting workflow step, or a second persistence implementation.
- All new method names are consistent: `record_successful_checks` is the batch API, `record_successful_check` is its single-check compatibility wrapper, and `QualityAuditCollector.flush` is the sole publication persistence boundary.
- No placeholders or unspecified failure paths remain; each task names files, tests, commands, and expected outcomes.
