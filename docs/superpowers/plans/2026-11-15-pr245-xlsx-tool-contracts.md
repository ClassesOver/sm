# PR245 XLSX Tool Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close concrete XLSX reader contract gaps before adding missing host tools.
**Architecture:** Preserve Agno registration and existing authorization; normalize source A1 notation at tool input, resolve omitted sheet from frozen selection, and use JavaScript RegExp for source regex semantics.
**Tech Stack:** Python 3.12, Agno 3.1.12, Node, pytest.
**Spec:** docs/superpowers/specs/2026-11-15-pr245-agno-tool-parity-design.md

## Global Constraints

Fixed upstream f8c17004fb730df11f0f743164ffd8b4281bb38c. Frozen authorization, explicit adoption, no automatic save, no repeated full suite. This first subsystem plan does not claim four-format completion.

## Review Focus

- Absolute/lowercase/reversed ranges must retrieve actual values without expanding authorization.
- Omitted sheet targets frozen selection; explicit unknown identities fail.
- Literal search must match each field separately, with source JavaScript coercion.
- Regex uses JavaScript semantics and is bounded against runaway execution.
- Reader and candidate tools expose the same regex parameter through real Agno schemas.

### Task 1: A1 inputs and selected sheet defaults

Files: workbook_ai_tools.py, native_workbook_read_ai.py; tests/test_workbook_ai_tools.py, tests/test_native_workbook_read_ai.py under smart_reporting/reporting.
Interface: _bounds(address) returns normalized zero-based rectangle; _sheet(None) selects frozen selection sheet when present. read_cells canonicalizes addresses before lookup.
- [x] Add tests for lower/absolute/reversed A1, outside-selection rejection, second-sheet default and canonical read_cells values.
- [x] Run these nodes and confirm failures from current strict parser/default.
- [x] Implement normalization, canonical cell lookup and selected-sheet default without changing source identities or selection scope.
- [x] Run affected reader/tool tests; expected all pass.
- [x] Commit source and tests.

### Task 2: find_cells regex contract

Files: workbook_ai_tools.py, native_workbook_read_ai.py, new workbook_search.py and workbook_search.mjs; new tests/test_workbook_search.py.
Interface: find_cells retains existing positional parameters and appends regex: bool=False; matcher returns matching input indexes. Use node with JSON stdin, no shell, timeout. Invalid regex returns workbook_ai_search_invalid; timeout returns explicit failure, never zero matches.
- [x] Add tests for source literal matching, regex groups/anchors/case-insensitivity, JavaScript-only named group syntax, invalid regex, errors_only, selection isolation and registered Agno schema.
- [x] Run added tests and confirm missing parameter/behavior failures.
- [x] Implement matching with native JavaScript RegExp and shared reader forwarding. Preserve output fields and bounds.
- [x] Run affected search, reader and tool tests, Ruff and diff check; expected pass.
- [x] Update evidence and remaining gaps; commit.

Later subsystem plans cover XLSX navigation/document creation and DSL parity, then Word, PPTX and PDF tools. Their implementation details follow fresh source/host investigation, not guessed adapters.
