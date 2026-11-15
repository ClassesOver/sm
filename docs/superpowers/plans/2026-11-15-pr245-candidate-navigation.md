# PR245 Candidate Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable source select_range in the native XLSX candidate assistant, including navigation-only requests.
**Architecture:** Opt-in navigationEnabled binds capability to the frozen request fingerprint. The native Agno planner returns an internal typed outcome containing trusted toolkit navigation and an optional existing proposal; no model-facing schema can forge navigation. Browser checks draft/view/task identity and reuses the verified navigation host hook. Data edits remain explicit acceptance; navigation-only results have no acceptance UI and server rejects adoption.
**Tech Stack:** Agno, FastAPI, Python, TypeScript, Univer.
**Spec:** docs/superpowers/specs/2026-11-15-pr245-agno-tool-parity-design.md (approved).

## Global Constraints

Fixed source f8c17004. Retain native async navigation_requested adaptation, frozen authorization, sheet-name identity, cancellation, durable result storage and old-client compatibility. No data edits, automatic adoption or save from navigation. Immediate desktop RPC and static viewer support remain open.

## Review Focus

- Navigation-only completion must not require fake content operations or permit adoption.
- Last navigation determines tool default sheet without widening authorization.
- Model final text/JSON cannot provide trusted target; toolkit owns target.
- Changed selection/draft/cancelled task cannot navigate; reveal failure retains valid edit candidate.
- Request capability changes conflict with existing request identity; legacy clients do not advertise navigation.

### Task 1: Trusted native Agno outcome and service transport

Files: workbook_ai_tools.py, workbook_ai.py, workbook_native_ai.py, workbook_native_ai_api.py; new reporting/tests/test_workbook_candidate_navigation.py.
- [x] Write and run failing tests for toolkit registration/defaults/scope, actual Agno navigation-only/mixed outcomes, service opt-in and no-adoption, request identity.
- [x] Add navigationEnabled default false; use native-only planner method with trusted outcome; preserve old plan_workbook contract and persist target with proposal envelope.
- [x] Run affected backend nodes.

### Task 2: Browser navigation and lifecycle

Files: frontend/src/workbook-native-ai.ts, workbook-main.ts, workbook-native-ai.test.ts; existing navigation smoke as appropriate.
- [x] Write and run failing UI tests for navigation-only, mixed edit, changed-view and failed/cancelled reveal.
- [x] Reuse host navigation function; validate current view before navigation, keep draft identity for later adoption independent from navigation; retain pending candidate on reveal failure.
- [x] Run scoped frontend checks and build/budget. Review, document evidence and push PR245 without force.
