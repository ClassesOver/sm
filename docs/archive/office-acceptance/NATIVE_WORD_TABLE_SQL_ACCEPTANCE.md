# Word tables: HTTP and real PostgreSQL delivery acceptance

2026-11-06. This closes the exercised SQL boundary left open by
`NATIVE_WORD_TABLE_ACCEPTANCE.md`, not production deployment or Office desktop
acceptance. The four-table operation sequence matches the frontend protocol:
insert row, delete row, insert column and delete column on independent source
objects, followed by a new edit after reopening the next revision.

## Primary material and method

`test_native_word_table_postgres.py` creates a real nonuniform fixed-width DOCX
with four tables, original `mirrorIndents`/`rsidR`, mixed row properties and
header/footer package parts. It uploads through actual workspace capability and
native ASGI routes. All table/cell identities are inspected from actual bytes;
no generated client XML or synthetic repository rows are accepted as outcomes.

The `postgres` variant uses the production SQL implementations for **all four**
persistence boundaries in the same isolated PostgreSQL schema:

- Native document/revision repository.
- Report artifact metadata and actual byte chunks.
- Download grants, including revocation on retry.
- Editor grants and sessions, including reopen/context lookup.

The table test uses PostgreSQL 18.0 and two independent SQLAlchemy engines. Its
initial source and downloaded revisions 2/3 are independently read with
python-docx/lxml; source paragraphs and unrelated ZIP member bytes must remain
unchanged. An independent SQL connection checks row state/counters, saved file
identities and concatenated persisted chunks against actual downloaded bytes.
This is stronger than merely seeing a successful API response or parser roundtrip.

## Observed sequence

| Step | Required independent outcome |
| --- | --- |
| Source upload/open | One saved revision; next revision 2. |
| Wrong source SHA and same-table duplicate preview | HTTP 409/422 respectively; preview's actual `batch_conflict` reason checked; no reservation/counter change. |
| One injected engine failure | HTTP 422 for the injected ValueError; revision 2 persisted as `failed/native_engine_failed`; no successful-file claim. |
| Two simultaneous identical retries | Both return registered revision 2 with identical file SHA; only one real transform executes after the injected fault; SQL still has two revisions, next revision 3. This exercises a single service's request lock, not independent deployed workers. |
| Download and independent file readback | Four expected matrices and integer widths, source paragraph XML and unrelated package files match. Failed semantic validation remains recorded and the actual download succeeds. |
| Changed retry note | HTTP 409; stored revision/counter unchanged. |
| Reopen revision 2 and try old anchor | Preview rejects the old source table identity; no new revision. |
| Fresh source anchor, second edit on first table | New revision 3, parent 2; odd 2401-twip width splits to 1200/1201. Download hashes/chunks and matrices independently match. |
| Immutable prior revisions and foreign scope | Original and revision-2 bytes unchanged; revision 3 reopens; foreign-user repository read returns no row. SQL has saved revisions 1/2/3, next revision 4. |

Same-revision publication **intentionally rotates download grants**. The initial
experiment incorrectly used the first concurrent response's now-revoked token
and got HTTP 403. The corrected check verifies the designed `[403, 200]`
revoked/active outcome, checks both successful save identities and downloads the
active grant. The production SQL grant rows independently show one revoked and
one active revision-2 grant, plus an active revision-3 grant. The grant policy
was not weakened to make this test pass.

The original mixed-preview experiment also included an unsupported `requestId`
field. It was corrected to send the strict preview schema and require the real
engine `batch_conflict` reason; a generic schema 422 is not accepted as proof.

## Recorded runs and retained scope

- Existing DOCX composite HTTP test connected to real native SQL, now including
  column insertion plus body/link/spacing/section changes: **1 passed** in the
  initial selected run (that run also reported the new scenario's first failure).
- Four-table failure/retry/revision-chain scenario with native SQL and explicit
  memory delivery stores: **1 passed, 9.28s**.
- Same scenario with native, artifact bytes, download grants and editor
  grants/sessions all in PostgreSQL: **1 passed, 8.81s**, no skips.
- Ruff passed for the new test. Existing repository/concurrency and other-format
  selections were not repeated. These are three selected passing checks across
  runs with different scopes; do not add duplicate reruns to old totals.

The last case independently observed two artifact files (revisions 2/3), exact
stored chunk bytes, the three expected download grant rows and at least three
actual editor session/grant records. Full structured evidence and actual DOCX
files are in `/tmp/pr190-word-table-all-sql-evidence`; the native-only variant
is in `/tmp/pr190-word-table-sql-evidence`. Logs preserve both the first failed
assumption and final passing results.

For reproduction, start a **new disposable** PostgreSQL instance and set
`NATIVE_TEST_DATABASE_URL` to its `postgresql+psycopg://...` URL. The fixture has
no fallback to application database configuration, uses a random schema, and
drops only that schema. With the required public test-only app import settings:

```sh
NATIVE_SQL_EVIDENCE_DIR=/tmp/word-table-sql-new-evidence \
AGENT_REPORTING_SLIDES_ENGINE_DIR=/tmp/pr190-word-table-final-runtime \
AGENT_WORKSPACE_HMAC_SECRET=public-test-only-native-acceptance-secret \
AGENT_REPORT_PUBLIC_BASE_URL=https://reports.test.invalid \
.venv/bin/python -m pytest -q -o addopts='' \
  'smart_reporting/reporting/tests/test_native_word_table_postgres.py::test_word_structure_sql_failure_retry_concurrent_save_and_revision_chain[postgres]'
```

After the actual run, an independent PostgreSQL query confirmed **zero** remaining
`native_acceptance_*` / `native_test_*` schemas. The root agent removed only its
new tmpfs-backed container `pr190-word-table-sql-pg`; the pre-existing onboarding
container/volume and shared images were left intact. Audit receipt:
`/workspace/scratch/pr190-word-table-sql-final-audit.json`.

## Remaining boundaries

HTTP is in-process ASGI, source identities/tenants are synthetic fixtures and
validation/one engine failure are deliberate injections. No deployed TCP/TLS,
production tenant identity/provider, production permissions, distributed worker
save race or Microsoft Word desktop acceptance is claimed. This SQL table
scenario does not exercise the concurrently added Word vertical-alignment,
Excel rotation, PPTX/PDF bulk commands. It also does not replace the full clean
application-image acceptance. Feature flags remain off; no deployment or merge.
