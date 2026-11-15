# PR245 PDF Source Ranges and Composer UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Accept GenOffice start/end page range parameters in PDF read_pages and read_annotations, and align shared composer automatic height with pinned source.
**Architecture:** Extend existing native reader entrypoints with source aliases while preserving native paging. Bound source continuations to their requested range; retain global annotation identities even when filtering. Update review wrappers to forward source arguments. Shared UI uses source textarea height algorithm, keeping controllers/model policy intact.
**Tech Stack:** Python/Agno, TypeScript/Vitest, existing PDF browser smoke.
**Spec:** docs/superpowers/specs/2026-11-15-pr245-agno-tool-parity-design.md (approved).

## Global Constraints

Fixed source f8c17004. Native legacy no-argument reading still defaults to first10pages; source start/end selects inclusive range and read_pages caps each call at10pages. No model picker. Frozen selection/coverage/projection/candidate lifecycle unchanged. Do not repeat full suite. No dependency on retired editor modules.

## Review Focus

- Mixed source/native range arguments reject rather than silently selecting wrong pages.
- Source continuation retains end bound and annotation filtered range; legacy cursors stay backward compatible.
- Annotation read spans use original global ordinal, not filtered offset; later annotation processing cannot gain unread-note authority.
- Strict source integers through real Agno execution, no bool/string coercion.
- Composer handles input, programmatic clear, queue/reset and hidden reopen; clamp at168px without model controls.

### Task1: Native source page ranges

Files: native_pdf_ai.py, native_pdf_review_ai.py, new test_native_pdf_source_ranges.py, PDF smoke server.
- [x] Write failing range, cursor, authorization, annotation identity, strict actualAgno tests.
- [x] Implement source aliases and wrapper transport; run scoped reader/review regression tests.

### Task2: Parallel composer UI

Files: office-assistant-panel.ts/tests and office-assistant.css.
- [x] Source textarea auto-size, input/clear/open hooks, preserving follow/queue/IME; TDD and scoped tests.
- [x] Independent review; production build/budget and browser source-argument+UI checks, record acceptance and syncPR245.
