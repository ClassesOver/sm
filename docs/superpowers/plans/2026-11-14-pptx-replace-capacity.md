# PPTX Replacement Capacity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Atomically reject unsaveable find/replace drafts.
**Architecture:** Check final cloned edit count before returning; reuse existing dialog catch.
**Tech Stack:** TypeScript, Vitest 3.2.7, jsdom 27.4.0.
**Spec:** ../specs/2026-11-14-pptx-replace-capacity-design.md

## Global Constraints
No main host, CSS, backend, other formats, implicit saves, splitting, or truncation.
No push/PR/merge/deploy. Directed tests only; no repeated complete suite.

## Review Focus
Count edits not matches; preserve geometry; distinguish slide identities; reject
atomically; keep dialog usable after failures. All covered by the task below.

## Task 1: Planner boundary and dialog recovery
Files: modify `smart_reporting/report_editor/frontend/src/slides-find-replace.ts`;
create `slides-find-replace-capacity.test.ts` beside it.
Interface: unchanged `planSlidesReplace` and `openSlidesFindReplace`.
- [x] Add tests: 501 new rejects, exact500 succeeds, 501 matches in one object
  succeeds, 499+2 rejects, 500 existing updated preserving geometry succeeds,
  same ID on two slides counts separately; repeated DOM overflow preserves
  inputs and calls no onReplace, narrower query then commits exactly once.
- [x] Run focused capacity test with isolated dependencies; verify behavioral RED.
- [x] Add final `result.length > 500` guard using approved concrete Chinese warning.
- [x] Run capacity and existing find/replace tests; confirm GREEN.
- [x] Review diff and record versions, SHA integrity checks and verification limits.
