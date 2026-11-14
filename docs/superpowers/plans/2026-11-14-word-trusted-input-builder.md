# Trusted Word input builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Derive private Word task input from existing server-recovered editor authority.
**Architecture:** One unregistered internal builder reuses grant lookup, native context/preview and selected_word_objects. Return typed input only; atomic task creation is exercised only by disposable test infrastructure.
**Tech Stack:** Existing Python/Pydantic/native DOCX engine/pytest/PostgreSQL.
**Spec:** docs/superpowers/specs/2026-11-14-word-trusted-input-builder-design.md

## Global Constraints
No provider/Codex startup, production route/scheduler/worker registration, new platform, schema/lifecycle change, new PR or business credentials. Trusted TaskExecutionScope is internal policy, not user-selected executor/workspace.

## Review Focus
- Mutable nested operations/selection across awaits: copied before first await, bound in tests.
- Stale/revoked or replaced session/context: final lookup rejects observed change.
- Body scope vs table/notes/revision: reject all nonparagraph/mixed selections.
- Instruction whitespace and hashes: hash exact original without trimming.
- Secrets and unselected content: whitelist DTO mapping, sanitized errors, repr nonexposure.

### Task 1: Trusted input derivation and actual DOCX proof
**Files:** Create smart_reporting/report_editor/native_word_task_builder.py; test smart_reporting/reporting/tests/test_native_word_task_builder.py.
**Interface:** NativeWordTaskInputBuilder(grants, editor).build(*, scope, server_session_reference, instruction, expected_sha256, operations, selection) -> NativeWordTaskInput.
- [ ] Add import-independent adapter assertion and behavioral tests against registered session/native context/actual synthetic DOCX preview.
- [ ] Run focused node, record expected missing-builder RED (not an unrelated dependency failure).
- [ ] Implement minimal derivation/limits/snapshot/revalidation and only selected paragraph mapping.
- [ ] Add mutation barrier, stale/changed context/session, forged scope/hash, invalid draft/selection and privacy tests; run RED/GREEN per behavior.
- [ ] Run targeted suite and Ruff; report missing native engine dependency honestly and send exact source for isolated cloud validation.

### Task 2: Existing atomic persistence seam
**Files:** Extend only new builder test or a new isolated PG builder test, not repository/schema.
- [ ] Use real builder result to call create_native_word_task on disposable PG, verify persisted input/hash and original instruction; generic projections omit selected/session data.
- [ ] Prove owner/thread mismatch rejected before create, and invalid builder never creates task.
- [ ] Run disposable PG with locked dependencies, record exact commit/tree, result counts and cleanup.
- [ ] Request Astra review; refresh verification ledger with evidence and no runtime/production claims.

Astra concrete additions: operations≤500 and≤12MiB canonical bytes; selection1..100 and exactly blockId per entry; instruction≤2000/nonblank. Snapshot mutable session capabilities with canonical identity bytes immediately on recovery. Actual DOCX type and independent verified source bytes are authoritative; add explicit original-source changes between previews, session deletion/expiry/in-place-cap mutation, caller-await mutation, context replacement and forged selection authority tests. Final normalization forbids accidental extra DTO fields.
