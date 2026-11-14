# PDF form/review accept authority boundary

Base: `94f188b1d366226246a31fde9fc2263fd1096727`.
Only the PDF form/review task services and their existing HTTP routers are changed.

## Confirmed defect and minimal fix

The previous code validated a session before preview, then reused that session after
preview and the final context lookup. Deleting its registered session, allowing its
future expiry to elapse, or replacing registered capabilities during either await
still returned HTTP 200 with candidate operations. Changing the stored job snapshot
also escaped the final check. Changing actual source bytes while preserving stored
context was not detected after preview.

HTTP routes now pass a server-owned optional lookup callback. After preview, the
service obtains context, verifies current source bytes with the existing editor
read method, re-reads the actual registered grant (including expiry), compares
session binding/capabilities, and rechecks the job snapshot/base before returning
operations. Existing candidate identity/status/context/receipt checks remain.
Direct trusted service calls retain the optional-callback contract; HTTP always
supplies the callback. No save or provider action is added.

## TDD and exact evidence

Final unchanged test SHA256:
`33810ac049103027ad05ff5ccdb3c53a01a5aafafe6611412384516dbf865db1`.

Command (with writable TMPDIR/MPLCONFIGDIR/XDG_CACHE_HOME):

```sh
/workspace/scratch/638db2129bf9/pptx-real-validation-venv/bin/python -m pytest -q -o addopts='' smart_reporting/reporting/tests/test_pdf_accept_authority.py
```

- Final test against original base production: **20 failed, 8 passed**, exit 1,
  8.47s. All 20 are business assertions: actual 200 instead of expected 403/409.
- Same final test against fixed production: **28 passed**, exit 0, 7.64s.
- One existing third-party `imghdr` deprecation warning in each run.
- Two formats x two await windows (preview and final context) x seven cases:
  positive, deletion, actual natural expiry from a future session deadline,
  context identity, stored snapshot, actual workspace source overwrite,
  replacement capabilities. Context changes already failed closed on the base.
- Real FastAPI routes/HTTPX ASGITransport, grant service/in-memory repository,
  task service and workspace byte identity validation. Seeded server candidate;
  controlled preview/context fixture, not an actual PDF engine or provider.
- Negative responses assert exact status/domain code and no returned operations.
  These specialized services do not maintain an `accepted` boolean. No save was
  called, and workspace source bytes remain either original or precisely the
  externally injected bytes, never rewritten by accept.
- Ruff on five changed Python files and `git diff --check`: passed.

Local evidence directory: `pdf-accept-evidence` under the execution workspace;
final logs `red-final-28.log`, `green-final-28.log`.

## Preserved execution history / limits

Initial sparse checkout lacked tracked `semantics`, producing a collection error;
tracked sources were restored, not stubbed. An initial over-broad local text edit
introduced a syntax error outside accept; that edit was reverted before further
verification. Neither is counted as a business RED.

Earlier narrowed matrices: 6 failed/4 passed, then 12 failed/8 passed, then
16 failed/8 passed, followed by 24 passed. These are superseded by the final
same-file 20-failure/28-pass pair, not additional unique passing cases.

The two existing engine-backed task test files were attempted: **22 setup errors**
(`pdf_engine/node_modules/.bin/tsx` missing), alongside the then-current 10 new
passing cases. Those 22 are NOT claimed passing. No dependency installation,
GUI, browser/socket retry, DSH, business data, full suite, push or deployment.

This is final-boundary observation, not cross-service linearizable revocation:
independent external stores can still change after their last observation; no
new global lock or transaction is claimed. Real PDF rendering remains outside
this new controlled-preview test, and the existing engine regressions are blocked
on their runtime dependency in this worktree.
