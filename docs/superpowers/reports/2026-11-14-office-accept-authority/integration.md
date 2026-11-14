# Combined accept-authority integration

Base 94f188b1; local isolated branch stage/office-accept-integrated-20261114.
Production integration HEAD d2d93dd4 consists of cherry-picks ceb734e5
(original 90fdf0df) and d2d93dd4 (original a6b3a056). No conflicts or
additional production edits. Source worktrees left unchanged.

## Fresh verification

```
TMPDIR=/tmp MPLCONFIGDIR=/tmp/accept-integration-cache XDG_CACHE_HOME=/tmp/accept-integration-cache \
/workspace/scratch/638db2129bf9/pptx-real-validation-venv/bin/python -m pytest -q -o addopts='' \
 smart_reporting/reporting/tests/test_regular_accept_authority.py \
 smart_reporting/reporting/tests/test_pdf_accept_authority.py \
 smart_reporting/reporting/tests/test_native_ai_shutdown_terminal.py \
 smart_reporting/reporting/tests/test_slides_native_ai.py \
 smart_reporting/reporting/tests/test_workbook_native_ai.py -k 'not real_engine'
```

74 passed, 3 deselected, 1 third-party imghdr warning, 10.62s, exit 0.
This includes the unchanged 24 ordinary and 28 PDF specialized authority cases.
Both new test SHA256 values match their original final RED/GREEN reports.
Ruff passes all 8 modified production files and both new test files;
`git diff 94f188b1 --check` passes. No full-suite claim.

Initial combined attempt had 5 collection errors because sparse checkout omitted
tracked smart_reporting.management. Added tracked smart_reporting to sparse
checkout, without stubs/dependency installation; final run above then passed.
Logs: accept-integrated-evidence/collection-error.log and combined.log outside repo.

## Preserved history and limits

Original reports remain untouched: ordinary verification.md and pdf-specialized.md.
They preserve final business RED counts, initial fixture/syntax/sparse setup errors,
and prior broader failures. Specifically PDF engine task tests previously had
22 missing-tsx setup errors; ordinary broader attempt had 45 passed, 4 failed,
2 errors, with missing Node/tsx engine/cancel fixture dependency and subsequently
corrected controlled read_file fixtures. Two legacy test files retain 43 historical
lint diagnostics; they are not included in the new-files/production Ruff claim.

Not verified here: real engines/providers/Codex, PG, browser/UI, save/export,
publication aggregate/full suite, deployment or cross-process linearizability.
These are controlled-preview ASGI/grant/workspace identity regressions, not full
rendering. Previously blocked DSH checks and browser permissions were not touched.
No push, PR, merge to main, deployment, credentials or external network actions.

## Review hardening after initial integration

Independent review reproduced a real deadline defect: lookup_registered_session
captured its default clock before awaiting the repository. A delayed final lookup
could return authority already expired. Move the default clock read after that
await, preserving explicit `now` semantics. Add a barrier test using real grant
service/repository inheritance, a future deadline and natural time elapsing.
Separately pin ordinary accept's proposal object and reject replacement after
preview, trusted receipt and final authority awaits. Replacement is defensive
hardening of a controlled injected job mutation; no production actor replacing
completed proposals was established. In-place dictionary mutation is not covered.

Final unchanged test SHA256:
- regular matrix: 854ae4246a006ae2af9b4e05847d1a9abaa6b49a0f047762fc94999df3e7203d
- registry expiry: c0bda38f2a8444a3acdaadcff3d66b38e4fb24e77ac10731f3279f783c218325

Exact final tests against pre-hardening production a985e854:
`pytest -q -o addopts='' test_session_lookup_expiry.py test_regular_accept_authority.py -k 'proposal or expiring'`
(full paths as above): 5 failed, 24 deselected, 1 warning, 7.41s. Failures:
registry lookup did not raise; four HTTP routes returned 200 accepted true rather
than existing native_ai_not_ready 422 rejection. hardening-red-final.log records it.

Final GREEN uses initial combined command plus test_session_lookup_expiry.py and
`test_report_editor.py::test_editor_grant_is_reusable_but_rejects_tampering_and_expiry`:
80 passed, 3 deselected, 1 third-party warning, 10.91s, exit 0.
This includes 28 ordinary, 28 specialized PDF, 1 delayed-registry expiry and
23 existing related checks. No full suite repeated, per repository prohibition.
All 9 changed production Python files and 3 new/updated focused test files pass
Ruff; diff --check passes. Final log hardening-green-final.log.

Preserved intermediate execution errors: initial test import used nonexistent
reporting.errors (collection error); corrected to existing reporting.models.
Initial proposal expectation used 409 while existing domain mapping is 422;
first GREEN therefore had 4 assertion failures/75 passes. Corrected test then
re-ran the identical final-file business RED and GREEN described above.
A guessed old grant node name was not found (exit 4), then corrected by inspecting
its actual declaration. These are not hidden or counted as business RED.

Independent reviewer initially found expiry defect, then read the intended final
hardening diff and found no additional Important/Critical issues. Review was
read-only; database-backed registry delay and real engines remain untested.
