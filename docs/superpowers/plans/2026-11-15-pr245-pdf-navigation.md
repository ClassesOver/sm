# PR245 PDF Reading Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Register source goto_page(page) for native PDF reading tasks with actual verified browser navigation.
**Architecture:** Optional captured viewPageId opts into navigation and binds request identity. Reader owns the last validated pending target, using its existing verified draft projection order to map effective tool pages to host page IDs. Model final JSON cannot provide targets. Frontend checks source/draft/selection/view/task and uses the existing page navigation host with actual DOM visibility verification. navigation_requested is asynchronous; success is browser-owned.
**Tech Stack:** Python/Agno/FastAPI, TypeScript/Vitest, existing PDF viewport, Playwright smoke.
**Spec:** docs/superpowers/specs/2026-11-15-pr245-agno-tool-parity-design.md (approved).

## Global Constraints

Pinned source f8c17004, tool goto_page(page), integer 1-based. Local tools retain effective page numbering when a draft projection exists; explicitly document mapping difference from desktop original numbering. Frozen selection remains authoritative; no body read/citation evidence or document edits from navigation. Legacy/headless readers do not register the tool. No save/adopt/permission widening. No repeated full test suite.

## Review Focus

- Reorder/delete/blank draft pages resolve to actual host IDs, never guessed original index; mismatched host order is rejected.
- Invalid, bool, out-of-range or out-of-selection pages never record navigation.
- Navigation-only result does not fabricate read evidence or citations; model JSON cannot forge target.
- Changed source/draft/view, task cancel/dispose, edit/preview/save state cannot execute delayed navigation; reveal failure retains answer.
- Optional view binding participates in request identity; followups retain context for the same authorized document despite a page change. Legacy planner kwargs remain unchanged.

### Task1: Trusted reader and API transport

Files: native_pdf_ai.py, native_pdf_ai_tasks.py, native_ai_api.py; new tests/test_native_pdf_ai_navigation.py, relevant existing task/draft tests.
- [x] Write and run failing tool/Agno/schema/projection/identity tests.
- [x] Implement opt-in view binding, trusted targets and projection map; preserve old clients.
- [x] Run affected reader/service/API/draft tests.

### Task2: Browser navigation, lifecycle and real smoke

Files: frontend native-api.ts, native-pdf-assistant.ts, pdf-main.ts, native-ai-progress.ts, new pdf-ai-navigation.ts; scoped tests and portable existing PDF AI smoke extension.
- [x] Write failing helper/assistant lifecycle tests, implement actual viewport confirmation and truthful failure.
- [x] Run scoped frontend tests, build/budget, real browser native HTTP+Agno smoke (provider stub explicitly identified), inspect screenshot/no-write/asset identity evidence.
- [x] Independent review; record acceptance, commit and sync PR245 without force, preserving concurrent work.

### Task3: Parallel shared assistant UI alignment (user steering)

User requires tool and UI alignment simultaneously, permits source UI copying, and disallows user model choice. Files: office-assistant-panel.ts/tests and accepted-task hooks in native-ai, native-office-assistant, native-pdf-assistant/review/form, workbook-native-ai, slides-native-ai.
- [x] Implement pinned GenOffice 48px bottom-follow behavior, preserve scroll-up and reset for accepted send/newchat; reject model-picker UI.
- [x] Fresh review; reproduce/fix missing task reset and hidden-completion reopen follow with TDD, maintain dispose cleanup.
- [x] Run shared and consumer scoped tests; consolidate build and real PDF smoke with Task2.
