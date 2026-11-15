# PR245 XLSX Read Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make select_range from the XLSX reading assistant move the actual workbook view without editing data or claiming server-side UI execution.
**Architecture:** Capture viewSelection separately from authorized reading selection. Reader validates/canonicalizes select_range and owns the navigation request returned with final result; model cannot forge it through answer schema. Browser verifies source/draft/view identity then applies last target via real Univer APIs and existing viewport reveal, reporting success only after verification. Headless/legacy clients without viewSelection do not register navigation. This is the existing asynchronous read-job adapter: source's immediate desktop navigation receipt is adapted to navigation_requested, not a false selected receipt.
**Tech Stack:** Agno, Python/FastAPI, TypeScript/Univer/Vitest/pytest.
**Spec:** approved docs/superpowers/specs/2026-11-15-pr245-agno-tool-parity-design.md.

## Global Constraints

Fixed GenOffice f8c17004 tool select_range. Source sheetId uses local sheet name identity as existing adapters; stable source IDs remain open. Navigation is not data reading or editing. Frozen selection authorization remains independent of current/target view. No save/auto-adopt. Unknown/out-of-scope/malformed targets fail before enqueue. Viewer without grid capability remains read-only text view and does not advertise this tool. Candidate-edit planner select_range remains a later host integration, not claimed complete here.

## Review Focus

- Omitted sheetId uses captured current sheet, not first sheet; subsequent logical reads use last requested sheet without widening frozen authorization.
- Invalid/reversed/absolute ranges normalize before authorization; range scope forbids outside targets.
- Navigating does not create read coverage/citations or mutate document/draft; final model JSON cannot forge target.
- Late/cancelled results and changed draft/view never trigger navigation; reveal failure does not discard answer or claim success.
- Actual grid activation/selection/viewport checks use existing reveal semantics and handle closed/editing/stale workbooks.

### Task1: Trusted reader tool and request transport

Modify native_workbook_read_ai.py, native_office_read_tasks.py, native_ai_api.py; extend NativeOfficeReadPayload with optional viewSelection using existing validated workbook rectangle. Include view in reading identity only when supplied, pass through async task to reader. Add view_selection=None to reader; opt-in select_range, captured/last requested sheet defaults, trusted final navigation from reader state. Expose select_range only with valid view. Keep original tools/citations/coverage and no matching content operations.
- [x] Write failing pytest source tool/default/authorization/coverage/schema tests and service transport identity tests.
- [x] Implement and run affected reader/service/API tests; expect pass.

### Task2: Actual browser navigation and stale-result guard

Modify native-api.ts, workbook-ai-read-context.ts, native-office-assistant.ts, native-office-view.ts, workbook-main.ts; create workbook-ai-navigation.ts. Context captures actual view even for document reading, preserving selection:null for authority. Return officeReadNavigate hook from workbook editor; bridge into assistant. Navigation payload coordinates+canonical range+sheetName validated before grid mutation. Use setActiveSheet/setActiveRange and existing createWorkbookReveal; inspect final active range/visibility before success. Do not markDirty or modify operations.
- [x] Write failing capture/UI lifecycle and actual Univer navigation tests.
- [x] Implement; run scoped Vitest, frontend tsc/build as appropriate to changed entrypoints and dynamic chunk.
- [x] Independent bounded review; evidence and push PR245 without force, preserving concurrent work.
