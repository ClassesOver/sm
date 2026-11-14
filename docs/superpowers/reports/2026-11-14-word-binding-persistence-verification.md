# Word binding persistence: verification ledger

Status: **targeted private-persistence/CAS stage validated for Draft PR review**.
Independent disposable PG18 validation of exact commit 44181e6 reports 78 passed,
0 failed, 0 skipped, exit 0, with one third-party deprecation warning. The original
real PG RED regression is GREEN with the same test file. This is not a full-suite,
production-ready or real-Codex-connected claim; the project suite collection blocker
below remains open. Root authorized Draft review, not merging or deployment.
Production is not enabled. No HTTP authentication, ticket minting, MCP registration,
Codex/provider startup, worker environment or editor acceptance integration is added.

## Baseline and ownership

- Remote code baseline: b29f8d8b9f2c136e1d97cab83cfb54e3042bc67d.
- Reviewed lease fix eb00a19 imported without conflict as 3fb6511c2da1e000258dde8e2423200fb9425302.
- Root's independent disposable PG18 validation of that baseline reported 36 passed:
  14 real PostgreSQL tests and 22 SQLite cancellation/fence tests. This report does
  not turn that earlier baseline result into proof of the new schema/CAS code.
- This worktree is the sole repository/schema owner for this phase.

## Implemented boundary

Four dedicated nullable columns on the existing task row, paired CHECK constraints,
receipt-requires-input constraint, and schema version 2.2.0. Migration reuses the
existing initialization advisory lock. Old workers must be stopped/drained before
Word use; no rolling compatibility is claimed. Private values stay out of generic
TaskSnapshot/TaskExecutionTask/result projections. Existing task-row retention applies:
terminal tasks eligible for deletion after the existing seven-day retention lose
private columns atomically with their row; active-task retention and actual cleanup
scheduling remain existing operational responsibilities, not a new guarantee.

Input creation shares the existing task+attempt+initial-instruction transaction.
The private typed input includes only selected paragraph data, full tenant scope,
document/revision/context/source/draft snapshot identities, selection digest, initial
instruction hash and an internal server session reference. Initial instruction text
is not duplicated; whole documents/unselected draft content are not stored here.
Input max is 256 KiB UTF-8; candidate receipt max 512 KiB. Strict JSON/version/digest
and uniqueness checks are enforced. These server-owned DTOs do not derive or prove
actual editor authority; that trusted integration is deliberately absent.

The narrow repository validates task scope, native tenant scope, immutable input,
initial instruction, run/attempt/owner/epoch, current executable state and lease/deadline.
It acquires a task row lock, reads fresh clock_timestamp() after waiting and repeats
clock-based conditions in the final SQL mutation. Registered-versus-final proposal
size/equality checks happen before the row lock; operation validation reuses the
existing native Word schema and word_candidate. The trusted server must supply the
actual registered receipt; the repository API is not a model-facing surface or proof
of tool read coverage by itself.

Candidate semantic digest excludes commit metadata; exact retry returns the original
receipt only after a current valid execution fence. New-attempt recovery returns
that same receipt without replacing origin metadata or calling a provider. FINISHING
recovery is read-only: current task claim remains mandatory, current run must be
FINISH_REQUESTED, but its historical run epoch is allowed. Commit is never allowed
through that exception. No generic lifecycle transition was changed for this rule.

FINISHING/COMPLETED private results require a versioned finish reference containing
both input and candidate digests. COMPLETED additionally requires the current run
CLOSED with FINISH_ACCEPTED; generic legacy complete_task does not prove Word completion.
The completed private accessor does not require an old executor lease and is NOT
an editor grant verification or document acceptance API. A current editor grant and
matching source/draft still must be verified by a future integration. Generic cancel
of a completed task is a no-op, not a durable candidate revocation promise.

## Actual local RED/GREEN evidence

All commands below targeted production modules or real SQL-backed SQLite fixtures;
no Codex/provider or real PostgreSQL was run locally.

- DTO tests written first: initial import failed because the contracts module was
  absent; subsequent implementation passed 12 initial cases. This collection error
  is not presented as sufficient behavioral RED evidence for the whole feature.
- Finish-reference test initially failed in five cases because the helper was missing.
  After implementation, a deliberate mutation replacing that guard with a no-op
  produced five DID NOT RAISE assertion failures (exit 1). Restoring it produced
  18 passing contract cases (exit 0), including the literal invalid pointer cases.
- Canonical JSON key coercion test first failed (DID NOT RAISE for an integer key);
  rejecting non-string keys made that exact test pass. This prevents digest aliasing
  between Python integer keys and JSON string keys.
- Private DTO repr test first failed because selected text was visible. Hiding private
  binding/selection/proposal fields from repr made that exact test pass. Repr protection
  is defense in depth, not a claim that logging raw dictionaries would be safe.
- Latest focused local command:
  `python /tmp/run_word_binding_tests.py smart_reporting/task_execution/tests/test_native_word_contracts.py smart_reporting/task_execution/tests/test_task_cancel_lease_fence.py -q`
  Result: 44 passed, exit 0 (22 contract/preflight cases + 22 existing SQLite cases).
  This bootstrap isolates unrelated application assembly; it is not a full application
  startup or pinned Agno compatibility test.
- Ruff over all five touched Python files: pass, exit 0.
- compileall over touched Python files and git diff --check: pass, exit 0.

## Project suite attempt: blocked, not green

The project's default command was actually attempted once:

`PYTHONPATH=/tmp/sm-word-mcp-deps:/tmp/sm-harness-deps python -m pytest -q`

Result: exit 2, 84 deselected, **780 collection errors**, 85.29 seconds. Main missing
packages were data_profiling, openai, openinference, pwdlib, dingyi_agno, duckdb, requests,
unidiff, dill and psycopg. The exact local log is retained in
`/tmp/word-binding-project-tests.log`; every failed module is listed in
`/tmp/word-binding-project-collection-failures.txt` (780 names). These are environment
collection blockers, not evidence that unrun application tests passed. No unrelated
dependencies were installed, and the project suite was not repeatedly rerun.

## Independent PostgreSQL18 GREEN validation (completed)

The new PG test file contains 20 cases (19 functions, one two-case parametrization).
It ran on a dedicated disposable PostgreSQL18 database. Fixtures TRUNCATE
agentos_coding tasks CASCADE and the migration test temporarily drops the four new
columns, so future reruns must likewise never use business/shared databases.

The independent run used real locked project dependencies and env -i with a clean
HOME and only a synthetic disposable database DSN. The test invocation explicitly
overrode default pytest integration deselection:

```bash
python -m pytest -q -o addopts='' \
  smart_reporting/task_execution/tests/test_native_word_contracts.py \
  smart_reporting/task_execution/tests/test_native_word_repository.py \
  smart_reporting/task_execution/tests/test_repository.py \
  smart_reporting/task_execution/tests/test_repository_execution.py \
  smart_reporting/task_execution/tests/test_task_cancel_lease_fence.py
```

Required behavior includes immutable creation and generic snapshot privacy, same and
different concurrent candidates, full scope/input/current-attempt mismatch, stale
owner rejection, new-owner/new-attempt recovery, FINISHING crash recovery, fresh time
after row-lock waiting, rollback after SQL write before commit, storage corruption,
changed instruction rejection, paired-column constraints, migration of old null rows,
concurrent initializers, completed-after-lease behavior, wrong/missing finish reference,
legacy-completion rejection, cancellation competition and takeover/expiry competition.
The three final races use explicit barriers and pg_blocking_pids rather than assuming
that asyncio.gather created real contention. All targeted cases passed in the
independent run: PG34 (new Word repository20 + existing repository14), existing
SQLite22, and pure contracts22, for 78 total. This proves this targeted review gate,
not the whole project or a production/provider integration.

Additional direct paragraph repr test produced an actual assertion RED for before/after/draft/style text; setting their repr=False made it GREEN. This does not change serialized content; the separate mutable-proposal PG regression is covered by the real RED/GREEN evidence below.

## Mutable caller proposal TOCTOU: real PG RED, then minimal correction

Root confirmed independent cloud validation of exact HEAD
0c937cd01f9c8e8caa084d6fa8bb4c862118e2dc / tree
c42937b39062696bfe643954f9c7e27ec6d9126e: the single node
`test_native_word_waiting_commit_uses_registered_snapshot_not_mutated_caller_dict`
produced **1 failed / 0 errors**, with actual text `Caller changed while waiting`
versus expected `Synthetic replacement`. pg_blocking_pids proved that the real commit
was blocked on the external row lock after preflight. The disposable PG container
was cleaned. Import or fixture failures were not counted as RED.

Only after that evidence, commit now canonical-serializes proposal and registration
exactly once each before any await, bounds and compares those immutable bytes, and
parses a private proposal snapshot from the verified bytes. The locked code uses only
that snapshot, never the caller-owned proposal dictionary. This is the root-cause
correction, not a later comparison of already-mutated data.

GREEN is independently confirmed for exact commit
44181e624e108d18efd76ed74d6df342374d1035 / tree
702e6b6f71763adcb9e9ab04ced6696624dc79b9. The actual pytest log summary is
`78 passed, 1 warning in 19.55s`; pytest exit code is 0. JUnit records the original
RED node with no failure/error/skipped child. RED and GREEN use the same test file:
SHA256 `68fa1e1285a4ee815953f5e28d8f9281b510f3f09adb7ae80cffecce4745f094`,
Git blob `c2fc215f2a2595a18ebdadf0e652a1b09aceebfb`. The only executable-code change
from RED to GREEN was the private canonical-bytes snapshot correction; the other
change was this verification ledger. No test was weakened to obtain GREEN.

The one warning is a third-party `DeprecationWarning` from
`visions/utils/monkeypatches/imghdr_patch.py:2` (`from imghdr import tests`):
`'imghdr' is deprecated and slated for removal in Python 3.13`.
It was associated with
`test_native_word_concurrent_commit_exact_retry_and_mismatch[asyncio]` and was not
silently suppressed or misreported as warning-free output.

The original command, pytest output, exit code, JUnit, source hashes and cleanup
records were independently read from the completed cloud validation thread. Container
and anonymous-volume inspect both returned no-such-resource after cleanup. These
records support the exact tested commit/tree; they do not authorize a provider or
production environment. This documentation-only follow-up must preserve all tested
source/test/configuration blobs, which are compared against 44181e6 before publication.

Astra's final independent review found no remaining blocker for this limited Draft
candidate. No additional hard gate on provider agno_status is introduced: receipt-only
recovery may not execute a provider at all. The gate is the versioned candidate/input
finish reference plus the persisted CLOSED/FINISH_ACCEPTED current run. A future
coordinator must distinguish provider success from receipt-only recovery and must
never relabel provider ERROR/unknown status as a successful provider run.
