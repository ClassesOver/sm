# Ordinary Office accept authority

Base: 94f188b1d366226246a31fde9fc2263fd1096727. Isolated branch fix/regular-accept-authority.

Real FastAPI + HTTPX in-process ASGI, real grant exchange, cookie/CSRF, InMemoryReportEditorRepository registry, NativeEditorService context and source identity reading, real ordinary Word/PDF, workbook and slides AI services. Only successful candidate creation and preview are controlled; these tests do not run planners, engines, providers, PG, browsers or save. File workspace is real and temporary. No network listener.

24-node matrix: four formats × success, registry deletion, natural expiry (registered future expiry allowed to elapse), persisted context replacement, external source overwrite, job snapshot replacement. Barrier is inside preview. Exact domain codes, accepted=False, no revision reservation and unchanged source (or exactly the injected external bytes) are asserted.

Final test SHA256: 8c02f2060ecb2af647bfb4a2626d7b3cd2ca823ab8c46935b2d46576ec46c022. Identical final test against base production: 20 assertion failures (HTTP 200 accepted true instead of intended rejection), 4 positive passes, 1 third-party imghdr warning, 7.61s. Earlier fixture media-type setup errors are not business RED. Initial expanded source assertion used a nonexistent read helper; corrected before this final identical-SHA RED/GREEN.

Fix: three HTTP routers supply server-derived registry lookup callback; common accept service reobserves registered authority, persisted context and actual file identity after preview/trusted receipt awaits, then registry/expiry last. Snapshot and terminal state are checked immediately before accepted. Direct service callers retain their existing session contract. No global lock; this is explicit post-await observation, not a claim of linearizable revocation against external processes.

Final command (venv python):
```
python -m pytest -q -o addopts='' smart_reporting/reporting/tests/test_regular_accept_authority.py smart_reporting/reporting/tests/test_native_ai_shutdown_terminal.py smart_reporting/reporting/tests/test_slides_native_ai.py smart_reporting/reporting/tests/test_workbook_native_ai.py -k 'not real_engine'
```
46 passed, 3 deselected, 1 third-party imghdr warning, 8.29s. Includes all 24 new cases; no skip. Two legacy controlled Editor fixtures add read_file to support the new boundary, with no old assertions removed.

Earlier broader attempt: 45 passed, 4 failed, 2 errors. Two real-engine tests and two cancellation-fixture errors lacked local Node/tsx runtime. Two controlled HTTP Editor failures lacked read_file and were corrected in test fixtures only. No dependencies installed to mask these errors; final run deliberately excludes engine tests and omits engine-dependent cancel fixture. No full suite claim.

Ruff passes four modified production files and new test. Two modified legacy test files have 43 pre-existing lint diagnostics, confirmed against HEAD source with stdin lint; no mass formatting applied. git diff --check passes.

Evidence logs: regular-accept-evidence under executor workspace (red.log/red2.log setup failures, red3/red4 intermediate, red-final.log exact final RED, green-final.log broader attempt, green-focused.log final, ruff-baseline.log). No pushed commits, PR, deployment, GUI/DSH, business credentials or real Codex. Temporary test workspaces owned by pytest only; no runtime links/processes created.
