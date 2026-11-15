# Native revision-event stage

This stage adds repository-only durable metadata events. It does not expose an
HTTP/SSE consumer, AgentEventLog integration, token streaming, document-object
synchronization, retention or historical backfill.

## Migration and rollout boundary

`create_schema` uses a transaction-scoped advisory lock keyed by current schema
before SQLAlchemy existence checks and DDL. Updated workers serialize fresh table
creation and additive migration. Existing documents receive counter zero; old
revisions remain readable; the first subsequent updated-writer transition emits
sequence one. Repeated migration is safe. Transactions atomically update revision,
counter and event. Consumers resume from nextSequence, not latestSequence.

The new nullable-independent counter has a server default so legacy inserts still
work. **Legacy writers do not append events.** Mixed-version writes therefore do
not provide a complete event stream; never enable consumers during mixed-writer
rollout. Drain old writers, run schema migration, verify all writers upgraded,
and require a full revision-state read as consumer baseline before any future
consumer launch. The advisory lock does not coordinate older startup code that
never takes it: do not run old/new schema initialization concurrently. This stage
does not claim zero-downtime mixed-version event completeness.

## Acceptance

Tests cover atomic rollback after event insertion, idempotent retry, scoped paging,
legacy migration with both table and counter absent, concurrent schema startup,
same/different reservation completion, and append between pages. The four-format
durable lifecycle test injects failure after a real event insertion, verifies
publication still returns an independently readable persisted download, rebuilds
services and retries without re-executing the engine, then checks exactly one
saved event for the recovered revision.

PostgreSQL acceptance must use an explicitly disposable NATIVE_TEST_DATABASE_URL;
never application connection settings. SQLite adapter checks are SQL rollback
checks only and make no PostgreSQL concurrency claim.
