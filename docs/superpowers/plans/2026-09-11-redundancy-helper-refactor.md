# Reporting Redundancy Helper Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove four confirmed duplicate implementations while preserving current Reporting and sandbox behavior.

**Architecture:** Keep public APIs and provider-specific policy checks unchanged. Put elapsed-time calculation in `runtime/observability.py`, canonical sandbox binding digest calculation in `sandbox/contracts.py`, and the Reporting non-negative integer normalizer in `reporting/phase.py`; consumers import the shared helpers.

**Tech Stack:** Python 3.12, pytest, Ruff, Pydantic models, HMAC-SHA256.

**Spec:** `docs/superpowers/specs/2026-09-11-redundancy-helpers-design.md`

## Global Constraints

- No protocol fields, error codes, persistence formats, or business rules change.
- Existing provider binding-secret length checks remain in Daytona and local providers.
- Application logs continue to use loguru.
- Run focused tests only; do not repeat the full test suite.

---

### Task 1: Shared elapsed-time helper

**Files:**
- Modify: `smart_reporting/runtime/observability.py`
- Modify: `smart_reporting/context_management.py`
- Modify: `smart_reporting/runtime/database.py`
- Modify: `smart_reporting/reporting/metadata.py`
- Modify: `smart_reporting/reporting/diagnostics.py`
- Modify: `smart_reporting/reporting/agent.py`
- Test: `smart_reporting/tests/test_observability.py`

**Interfaces:**
- Produces `duration_ms(started_at: float) -> int` in `runtime.observability`.
- Consumers replace local `_duration_ms` definitions and import the shared helper.

- [ ] **Step 1: Write the failing test**

Add a focused test that monkeypatches `smart_reporting.runtime.observability.perf_counter` and asserts elapsed values are rounded and clamped at zero.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest -q smart_reporting/tests/test_observability.py -k duration_ms`
Expected: FAIL because `duration_ms` is not defined.

- [ ] **Step 3: Write minimal implementation and migrate callers**

Add the helper with the current expression `max(0, round((perf_counter() - started_at) * 1000))`, then replace all five identical private functions and their call sites with the import.

- [ ] **Step 4: Run focused tests and static checks**

Run: `.venv/bin/pytest -q smart_reporting/tests/test_observability.py -k duration_ms` and `.venv/bin/ruff check --select F smart_reporting/runtime/observability.py smart_reporting/context_management.py smart_reporting/runtime/database.py smart_reporting/reporting/metadata.py smart_reporting/reporting/diagnostics.py smart_reporting/reporting/agent.py`
Expected: PASS and no Ruff findings.

### Task 2: Shared sandbox binding digest

**Files:**
- Modify: `smart_reporting/sandbox/contracts.py`
- Modify: `smart_reporting/sandbox/daytona.py`
- Modify: `smart_reporting/sandbox/local/client.py`
- Test: `smart_reporting/tests/sandbox/test_contracts.py`

**Interfaces:**
- Produces `binding_digest(binding: WorkspaceBinding, secret: bytes) -> str` in `sandbox.contracts`.
- Both providers use it after their existing secret-length validation.

- [ ] **Step 1: Write the failing test**

Add a test asserting equivalent `WorkspaceBinding` values produce the same deterministic HMAC digest and that `idempotency_key` is excluded.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest -q smart_reporting/tests/sandbox/test_contracts.py -k binding_digest`
Expected: FAIL because `binding_digest` is not defined.

- [ ] **Step 3: Write minimal implementation and migrate providers**

Move the existing canonical JSON plus HMAC body into `sandbox.contracts`, remove both private copies, and update imports/calls without changing provider validation or error behavior.

- [ ] **Step 4: Run focused tests and static checks**

Run: `.venv/bin/pytest -q smart_reporting/tests/sandbox/test_contracts.py -k binding_digest` and `.venv/bin/ruff check --select F smart_reporting/sandbox/contracts.py smart_reporting/sandbox/daytona.py smart_reporting/sandbox/local/client.py`
Expected: PASS and no Ruff findings.

### Task 3: Shared non-negative integer normalizer

**Files:**
- Modify: `smart_reporting/reporting/phase.py`
- Modify: `smart_reporting/reporting/agent.py`
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Test: `smart_reporting/reporting/tests/test_reporting_workflow_scope.py`

**Interfaces:**
- Produces `_nonnegative_int(value: Any) -> int` in `reporting.phase`.
- Replaces all nine local `count` closures with the shared helper.

- [ ] **Step 1: Write the failing test**

Add tests for non-negative integers, negative integers, booleans, and non-numeric values using the phase helper.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest -q smart_reporting/reporting/tests/test_reporting_workflow_scope.py -k nonnegative_int`
Expected: FAIL because `_nonnegative_int` is not defined.

- [ ] **Step 3: Write minimal implementation and migrate callers**

Implement the exact existing predicate and replace local closures; preserve each caller's existing field names and arithmetic.

- [ ] **Step 4: Run focused tests and static checks**

Run: `.venv/bin/pytest -q smart_reporting/reporting/tests/test_reporting_workflow_scope.py -k nonnegative_int` and `.venv/bin/ruff check --select F smart_reporting/reporting/phase.py smart_reporting/reporting/agent.py smart_reporting/reporting/workflow/runtime/analysis.py`
Expected: PASS and no Ruff findings.

### Task 4: Remove duplicate async compression delegation

**Files:**
- Modify: `smart_reporting/context_management.py`
- Test: `smart_reporting/tests/test_context_management.py`

**Interfaces:**
- `ContextBudgetController` inherits `ashould_compress` from `ProtectedCompressionManager`.

- [ ] **Step 1: Write the failing regression test**

Add a test that invokes `ContextBudgetController.ashould_compress` with a stub model whose `count_tokens` crosses the budget, proving inherited async dispatch reaches the subclass `should_compress` implementation.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest -q smart_reporting/tests/test_context_management.py -k inherited_async_compression`
Expected: FAIL because the test records the subclass method as overridden rather than inherited.

- [ ] **Step 3: Write minimal implementation**

Delete only `ContextBudgetController.ashould_compress`; leave `should_compress`, `compress`, and `acompress` unchanged.

- [ ] **Step 4: Run focused tests and static checks**

Run: `.venv/bin/pytest -q smart_reporting/tests/test_context_management.py -k inherited_async_compression` and `.venv/bin/ruff check --select F smart_reporting/context_management.py`
Expected: PASS and no Ruff findings.

### Task 5: Final verification

- [ ] **Step 1: Run the focused regression set**

Run: `.venv/bin/pytest -q smart_reporting/tests/test_observability.py smart_reporting/tests/sandbox/test_contracts.py smart_reporting/reporting/tests/test_reporting_workflow_scope.py smart_reporting/tests/test_context_management.py`
Expected: PASS with no failures.

- [ ] **Step 2: Verify duplication removal and worktree scope**

Run: `.venv/bin/ruff check --select F smart_reporting` and `git diff --check`; inspect `git status --short` to ensure existing unrelated modifications remain untouched.

- [ ] **Step 3: Commit only implementation files and focused tests**

Stage the files changed by Tasks 1-4 and commit with `refactor: consolidate reporting helper logic`.
