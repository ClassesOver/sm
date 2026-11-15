# PR245 PPTX Source Guides Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expose source load_guide(groups) through native SlidesAIToolkit using all six immutable imported PPTX operation guides.
**Architecture:** Reuse pinned vendor source text through a fixed-name loader in office/ai_skills.py. Register the source-named tool with enum groups, ordered deduplication and exact source join delimiter. Return source output separately from native adapter instructions; loading reference docs must never grant source operations or satisfy authorized page reads.
**Tech Stack:** Python, Agno, pytest.
**Spec:** docs/superpowers/specs/2026-11-15-pr245-agno-tool-parity-design.md (approved).

## Global Constraints

Pinned GenOffice f8c17004. Original source bytes unchanged. Six source groups in source order text/element/insert/table/slide/deck. Native proposal schema and explicit acceptance stay authoritative; EMU source references do not replace native 96dpi pixel geometry. No file path inputs or network fetch at runtime. No full-suite repeat (AGENTS.md).

## Review Focus

- Unknown/empty/mixed-invalid lists reject all; no partial source output or filesystem path traversal.
- Return all source bytes without truncation, preserve requested group order, remove duplicate groups.
- Source examples may describe unsupported operations; explicit adapter metadata and planner instructions must preserve actual native tools/scope.
- Documentation access cannot mark a slide read or register a candidate.
- Real Agno tool schema and loop consume docs before independently authorized read/proposal; notes mode stays notes-only.

### Task 1: Fixed source loader and native toolkit guide

Files: office/ai_skills.py, report_editor/slides_ai_tools.py, slides_ai.py; reporting/tests/test_slides_ai_guides.py.
- [x] Write failing contract tests for every guide's provenance, all-input validation, source join/dedupe, no read/proposal side effects, exact Agno schema and tool loop.
- [x] Run RED tests; implement allowlisted source loader and registered load_guide(groups) with separate nativeAdapter instructions.
- [x] Run scoped tests for existing slides toolkit, native service, notes, and skills integration as affected.
- [x] Fresh independent review; record evidence and update coverage; commit and push existing PR245 branch without force, preserving concurrent changes.
