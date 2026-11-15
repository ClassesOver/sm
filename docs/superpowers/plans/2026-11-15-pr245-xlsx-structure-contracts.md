# PR245 XLSX Structure Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire four missing source row/column DSL operations and close remaining input normalization defects.
**Architecture:** Translate source operations to existing applyRowColumnOps, preserving one-based DSL vs zero-based engine coordinates. Keep frozen authorization and enforce source structural-only batches. Normalize range outputs before passing to strict native engine. Use existing Node matching host for source query trim.
**Tech Stack:** Python, Agno, existing XLSX Node engine, pytest/openpyxl.
**Spec:** docs/superpowers/specs/2026-11-15-pr245-agno-tool-parity-design.md (approved).

## Global Constraints

Fixed source f8c17004fb730df11f0f743164ffd8b4281bb38c. Reuse existing engine and Agno. Structural/content/layout source DSL must be proposed in separate batches. Keep existing native operation compatibility. No automatic save or overwrite. No repeated full suite.

## Review Focus

- One-based row and column-letter inputs must move exactly intended cells, formulas and merges.
- Counts reject bool/float, zero, missing, source-limit excess and grid overhang before preview.
- Range mode cannot access structural tools; mixed source structural/content proposals reject atomically.
- Native engine receives canonical sort/merge ranges; non-target merge/value parts survive.
- Trace aliases preserve authorization and query trim follows JavaScript rather than Python whitespace.

### Task 1: Native structural DSL and canonical ranges

Modify workbook_ai_tools.py; create workbook_ai_structure.py and reporting/tests/test_workbook_ai_structure.py.
Interfaces: translate_row_column_operation(operation: dict,sheet_name: str) -> native operation dict; _range_address(address: str) -> canonical A1 rectangle. Four ops insert_rows/delete_rows(row,count),insert_cols/delete_cols(column,count); required count, caps500/100, rows1..1048576, columnsA..XFD. Only whole-workbook scope. New structural DSL cannot mix with content/layout/native kinds in the same candidate (source batch policy; native-only behavior unchanged).
- [x] Write real-engine preview/reopen tests for all4 operations including source/other-sheet formula and merge preservation, source immutability.
- [x] Add invalid count/span and mixed-batch/range authorization tests asserting preview not called and proposal absent; prove failures before implementation.
- [x] Implement helper, source DSL registration through propose_operations, structure guide and source batch guard.
- [x] Test lower/absolute/reversed sort+merge input against real engine; implement canonical range emission preserving non-target merges.
- [x] Run focused new/affected tool+precondition tests; commit tested deliverable.

### Task 2: Trace and search input normalization

Modify workbook_ai_tools.py, workbook_search.py, workbook_search.mjs; extend test_workbook_tool_contracts.py/test_workbook_search.py.
Interfaces: trace_precedents/trace_dependents normalize address via shared _cell_address; search Node applies query.trim() before compiling/matching; invalid blank query produces workbook_ai_search_invalid.
- [x] Add failing tests for trace lowercase/absolute aliases, selection denial and invalid range; JS BOM trim and NEL non-trim.
- [x] Implement source input handling; preserve return/output, error and read-coverage contracts.
- [x] Run affected tests and checks; independent whole-batch review; update evidence and push PR245 after integrating concurrent changes.
