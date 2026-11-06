# Native repository PostgreSQL acceptance

## Original result and scope

2026-11-06: **14 passed, 0 skipped** against real PostgreSQL **18.0** with
SQLAlchemy AsyncEngine and the psycopg driver. The run comprised five new
integration acceptance tests and nine existing native repository tests. Ruff
passed for the new test file. One unrelated third-party `imghdr` deprecation
warning was emitted.

Subsequent, separately selected HTTP-plus-PostgreSQL runs passed **all four**
formats: `docx`, `pdf`, `xlsx` in 10.82 seconds, then `pptx` in 7.32 seconds,
with no skips. The PPTX run used the updated list/indent/spacing acceptance,
including file and raw OOXML readback of numbering, start value, color, relative
bullet size, hanging indent and text direction. The combined evidence is
**18 passing checks** across the three targeted runs; the initial 14 were not
repeated.

This closes the repository persistence, transaction, retry and concurrency layer
for the exercised contracts. No application code changed. It does **not** prove
production tenant identity, deployed HTTP authentication, production database
permissions/configuration, network serving, actual Office file verification, or
the full deployed editor workflow. `complete_revision` checks file metadata;
it does not independently read or hash artifact bytes. The added HTTP cases do
read and verify actual transformed files and download hashes, using in-process
ASGI routes and the actual file engines; artifact/download and editor grant
repositories remain test doubles. Failed-to-saved recovery
still requires the service to verify the actual file before invoking completion.

## Primary evidence and method

The primary sources are `native_repository.py` (real SQL statements, transaction
boundaries, document row locks and immutable completion checks),
`native_models.py` (scope and revision identities), PostgreSQL's actual persisted
rows, and independently connected repository readers. Neither repository methods
nor the SQLAlchemy engine were mocked. PostgreSQL enforced JSONB, unique request
identity, primary keys and transaction semantics.

`reporting/tests/test_native_repository_postgres_integration.py` exercises:

| Contract | Independent observation |
| --- | --- |
| Same request racing across two engines | 16 tasks start at an asyncio barrier; all receive the identical revision; SQL sees two total rows and next revision 3, including after completion/retry. |
| Different requests racing across two engines | 16 tasks commit revisions 2–17 exactly once; another engine reads all identities; SQL sees 17 rows and next revision 18. |
| Scope boundary | Each of database, company, user and thread is changed independently; foreign reads return no row, and reserve/complete/fail reject without changing the original reservation. |
| Conflicting retry or completion | Changed SHA, parent or note is rejected; missing/unsaved parents and artifact/context mismatch are rejected; SQL count/counter and the stored reservation remain unchanged; the next valid request still gets revision 3. |
| Failure and immutable completion | Same failure is idempotent, a different failure conflicts, a failed parent is rejected, retry recovers the same row, validation failure remains visible after saving, and altered validation/file identity or late failure cannot overwrite a saved revision. |

The existing `test_native_editor_repository.py` additionally executed its real
two-**process** revision reservation test, schema reinitialization and legacy
`note` migration, create/open idempotency and source identity isolation. Its
pure model tests also passed. The new file is marked `integration`, so normal
default runs exclude it; the recorded acceptance command explicitly overrides
that default.

The parametrized `test_http_ribbon_roundtrip_persists_real_postgres` reuses the
existing `test_native_ribbon_http_roundtrip.py` HTTP acceptance function without
copying its flow. Only its native repository constructor is replaced with the
real PostgreSQL repository. It exercises upload, source open, preview, save,
download, same-request retry and revision reopen. SQL then independently checks
one document, exactly two saved revisions, next revision 3, and persisted
`native_validation_failed`; another repository engine reads back the saved
scope, revision identity and failed validation. This specifically closes the
previous gap between the ASGI route test and PostgreSQL persistence, while grant
storage and deployed-server behavior remain outside its evidence.

## Isolation and reproduction

The run used root agent's newly created disposable container
`pr190-native-acceptance-pg` from `postgres:18.0-alpine`, bound only to
`127.0.0.1:55432`. PostgreSQL data lived in an isolated 256 MiB tmpfs, with no
user volume and a read-only container root. Only public test-only credentials
were used. No user database URL was consulted or contacted.

Each test creates a random `native_acceptance_<uuid>` schema (existing tests use
`native_test_<uuid>`), applies the repository's actual `create_schema()`, and
connects independent engines using that schema's search path. Cleanup drops
only its generated schema and disposes engines. A post-run SQL query confirmed
**zero** remaining schemas with either test prefix in this disposable instance.
After all checks, the root agent independently confirmed PostgreSQL 18.0 and zero
remaining test schemas, then removed this disposable container. No user volume
was created or removed.

For reproduction, start a new disposable PostgreSQL instance and explicitly set
`NATIVE_TEST_DATABASE_URL` to its `postgresql+psycopg://...` URL. Do not point
either variable at an application database. Then run from the repository root:

```bash
REPORTING_TEST_DB_URL="$NATIVE_TEST_DATABASE_URL" .venv/bin/python -m pytest -q -o addopts='' \
  smart_reporting/reporting/tests/test_native_repository_postgres_integration.py \
  smart_reporting/reporting/tests/test_native_editor_repository.py -k 'not http_ribbon'
.venv/bin/python -m ruff check \
  smart_reporting/reporting/tests/test_native_repository_postgres_integration.py
```

The subsequently added HTTP cases also require the application's public
test-only import settings. To execute only those cases, without repeating the
14 repository/model checks:

```bash
AGENT_WORKSPACE_HMAC_SECRET=public-test-only-native-acceptance-secret \
AGENT_REPORT_PUBLIC_BASE_URL=https://reports.test.invalid \
.venv/bin/python -m pytest -q -o addopts='' \
  smart_reporting/reporting/tests/test_native_repository_postgres_integration.py \
  -k 'http_ribbon and not pptx'
AGENT_WORKSPACE_HMAC_SECRET=public-test-only-native-acceptance-secret \
AGENT_REPORT_PUBLIC_BASE_URL=https://reports.test.invalid \
.venv/bin/python -m pytest -q -o addopts='' \
  smart_reporting/reporting/tests/test_native_repository_postgres_integration.py \
  -k 'http_ribbon and pptx'
```

The first attempts omitted the required application import settings and failed
before reaching HTTP or repository behavior; adding these explicit test-only
settings produced the recorded passing run. No product workaround was required.

The new fixture has no fallback to application database settings. Without the
explicit test URL it skips; a skipped run is **not** acceptance evidence.
The exact recorded run finished in 11.77 seconds with `14 passed, 1 warning`.


Scope checkpoint: these 18 distinct checks were recorded before the later Word
table structural adapter. The shared DOCX HTTP fixture now also exercises column
insertion, but this phase did not rerun it against PostgreSQL. Do not infer new
structural-operation SQL acceptance from the earlier counts.


## Word table SQL delivery continuation

The later table-flow gap is now exercised in
`test_native_word_table_postgres.py`: four actual source-bound structure
operations, injected failure recovery in the same reservation, concurrent
idempotent saves, revision-2 reopen/old-anchor rejection and fresh revision 3.
The final `postgres` variant uses production SQL repositories for native
revisions, actual artifact bytes/chunks, download grants and editor
grants/sessions; independent SQL checks and actual downloaded-file readback
passed (1 passed, 8.81s). Thus the earlier statement that delivery stores are
doubles remains true for the original runs, not this new dedicated scenario.
Exact run counts, grant rotation behavior, cleanup and remaining synthetic
ASGI/tenant boundaries: `NATIVE_WORD_TABLE_SQL_ACCEPTANCE.md`.
