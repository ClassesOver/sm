# XLSX AI source cell preconditions — bounded acceptance

Baseline code `1e4a0a34` plus previous uncommitted Office fixes. Fixed source:
GenOffice f8c17004fb730df11f0f743164ffd8b4281bb38c,
`packages/xlsx-gateway/src/domain/in-memory-workbook.ts:280–302` and
`domain/workbook-dsl.ts:setCellSchema/setFormulaSchema`. User goal: enumerate and
fill XLSX gaps. This batch changes only `workbook_ai_tools.py`, adds focused tests,
and updates current audit evidence; previous Office/PDF changes remain untouched.

## Implemented contract

- `set_cell.expectedValue` is checked, including explicit null/missing-cell semantics,
  finite scalar types and boolean-versus-number strictness. Numeric int/float equality
  remains source-number equality; strings are not coerced into numbers.
- `set_formula.expectedFormula` is exact and string-typed. Formula case, whitespace,
  leading '=' and actual absence are not guessed or normalized during comparison.
- Proposal-local sparse shadow cells replay pure source set/clear/formula operations
  in order, including repeated writes. Frozen model is neither modified nor replaced
  by this shadow. Any later mismatch rejects the whole batch before preview.
- Scope authorization precedes the actual-value comparison. Errors contain only safe
  codes, not the out-of-scope value. Failed preconditions leave candidate unset and
  allow a corrected retry.
- Mixed native/source discriminators and condition fields on the wrong operation
  cannot silently drop guards. After a native/structural/non-cell prefix, conditional
  cell writes explicitly fail `workbook_ai_precondition_requires_cell_batch`: this
  translator cannot safely materialize that prefix. Unconditional existing mixed
  candidates remain supported. The writing guide explains this limit.
- Existing real engine preview, proposal freeze, explicit acceptance and full-draft
  identity/CAS are retained. This is not a new write/HTTP/publication endpoint.

Chosen boundary: replay known cell DSL, refuse uncertain prefix effects. Checking an
unchanged frozen base after a sort/raw mutation would be wrong; implementing a second
spreadsheet evaluator would also be wrong. Full source preconditions after arbitrary
native prefixes remain open until they can use materialized actual engine state.

## Fresh evidence

Artifacts `/tmp/xlsx-preconditions-20261114/`:

- Initial behavioral RED: **17 failed / 3 passed**, red.log. Existing implementation
  previewed mismatched conditions, including type/formula/sequential/mixed-prefix.
- First GREEN: **33 passed** across new preconditions + candidate-boundary tests.
- Further mixed-wire/wrong-field RED: **6 failed / 20 deselected**, mixed-red.log.
  These cases were corrected without changing the successful-path assertions.
- Final affected three-file run: **63 passed**, combined.log. Includes **28 new
  precondition tests**, existing tool/boundary tests, and actual XLSX bridge read/edit/
  openpyxl readback in both range and workbook scopes. Source original A1=42 and other
  cells remain; candidate final formula =B1; mismatched candidate never reaches preview.
- Ruff for changed Python/test files and diff whitespace checks passed.
- Independent same-model static review found no important issue. Source scalar/formula,
  scope-before-read, sequential shadow, batch atomicity and conservative prefix limit
  were explicitly reviewed. Reviewer did not rerun tests.

The real current workbook CLI was bundled from repository sources using existing
frontend esbuild/dependencies into isolated `/tmp/.../engine/dist/cli.mjs`, with the
normal createRequire banner. Tests selected it with
`AGENT_REPORTING_WORKBOOK_ENGINE_DIR`, so this is the real bridge/engine, not a mock
patcher. No repository dist/config/lock/version change. Temporary engine dependency
link is removed afterward. JSON bytes/Openpyxl are independent file evidence; no
browser download, real provider, production HTTP adoption or production DB run was
performed. Full test suite was not repeated. Existing visions/imghdr deprecation
warning remains (Python3.13 removal), not claimed warning-free.

This closes silently ignored source cell preconditions within the stated pure-cell
contract. It does not close all source DSL parameters, arbitrary-prefix preconditions,
AI redaction, durable tasks, rich/unsupported formula semantics, or full XLSX parity.
No commit, push, merge or deployment.
