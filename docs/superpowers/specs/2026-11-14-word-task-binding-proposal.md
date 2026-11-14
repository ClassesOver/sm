# Word task binding and trusted MCP identity: review proposal

Historical design proposal: the private persistence/CAS subset is now implemented
and independently targeted-tested for Draft review in 44181e6; see the verification
ledger for exact evidence and the full-suite collection blocker. Authentication,
HTTP/MCP production registration, worker isolation and real Codex execution remain
unimplemented/not enabled. The proposal below retains its original design context.

Original proposal status: **not implemented or enabled at the time of writing**. No task lifecycle, repository,
schema, shared authentication, HTTP route, provider or worker changes in this slice.

## Verified existing seams and gaps

- `report_editor/service.py:629` lookup_registered_session accepts a server-registered
  session hash, checks registration and expiry; HTTP must not accept this hash from
  model/browser input as an authorization shortcut.
- `report_editor/native.py:191-217` context_for_session validates native_editor,
  NativeScope (database/companyId/userId/threadId), saved revision, format and context
  digest. `read_file:219-232` checks actual source size/SHA in the scoped workspace.
- `report_editor/native_ai.py:193` snapshot binds context digest, source SHA and draft
  operations. start_edit:202 onward restores allowed selection objects from original
  source preview plus draft operations via selected_word_objects, then validates draft
  preview. These server results, not model fields, are the binding source.
- `task_execution/repository_impl.py:193-228` task columns have no dedicated native
  input/document binding. acceptance_contract is strictly a quality schema; finish
  payload/receipt have existing lifecycle semantics. Neither is an authorization root.
- execution operation_receipt is mutable through update_execution:969; execution rows
  additionally require a Daytona session identifier. Do not invent a fake execution
  session or overload this receipt for Word authorization.
- validate_execution_fence:874 performs a read; update_execution:969 checks neither
  the lease nor document binding. A read followed by that update has TOCTOU. The
  helper named _locked_task_for_execution does not itself issue FOR UPDATE in this
  checkout. Do not infer atomicity from its name.
- TaskSession.assert_alive checks its local heartbeat/lease snapshot. It is useful for
  early cancellation but cannot authorize durable candidate publication.
- Current reporting_mcp capability verifies workflow/thread access, not a Word
  document selection or task execution attempt. It cannot be reused unmodified.

## Proposed minimal persistence, pending review

Add dedicated nullable columns on the existing task row, not a new task platform:

1. native_word_input JSONB: a strict versioned WordTaskInput envelope.
2. native_word_input_sha256: canonical digest for immutable compare/idempotence/CAS.
3. native_word_candidate_receipt JSONB: one immutable committed candidate receipt.
4. native_word_candidate_sha256: canonical receipt identity.

Alternative under review: two JSONB envelopes each embedding its digest. Separate
scalar digest columns make SQL compare-and-set clearer and avoid JSON path coupling.
Legacy null rows stay valid for existing work but cannot execute Word tools.
Do not change acceptance_contract or overload generic finish fields.

WordTaskInput is server-owned and immutable. Proposed nested WordTaskBinding contains
version/kind; full NativeScope; documentId/revision/contextSha256/sourceSha256;
snapshotSha256/draftOperationsSha256; normalized selected-object digest; and a
server-resolved editor-session reference used only by the coordinator. The envelope
also retains the validated instruction, base draft operations and frozen authorized
paragraph objects needed to replay a task after a restart. Canonical serialization
must reject unknown keys, NaN and non-JSON values, and enforce explicit size limits
before persistence. Limits remain a review decision, not a silent production default.
No raw grant token, database credential, source path or session bearer is sent to the
model. The full input remains application-side; MCP exposes only authorized blocks.

Binding must not include a model-selected owner/epoch. Task identity is stable across
attempts; current owner/epoch/internal run/attempt come from repository lease claim and
are checked separately. Each new attempt reconstructs the same binding and gets a new
execution ticket. Input changes require a new task, not mutation of a running binding.

## Proposed trusted request authentication

Reuse existing server credential/signature infrastructure, but add a distinct,
short-lived purpose/audience for native Word MCP. Do not introduce a new OAuth system,
provider proxy loop, generic authority service, or long-lived all-task worker token.

Only after the existing editor grant, context/source/draft/selection checks and a real
repository claim may the trusted coordinator mint a task ticket bound to:

- audience/purpose native-word-task-mcp;
- task ID and immutable input/binding digest;
- complete NativeScope;
- current internal run ID, attempt number, lease owner and epoch;
- issue/expiry and nonce/JTI, using existing signature validation primitives.

MCP authentication verifies signature, purpose and expiry and reloads current binding
and lease from trusted storage. Tool task_id must match that principal; authorization
must not trust user/session/scope/lease fields supplied as tool arguments. No existing
workflow capability may satisfy this new audience. The MCP server owns DB/signing
access; the restricted Codex worker receives only its current task bearer through the
transport auth channel, never DB credentials or the signing key. Do not expose bearer
values in model input, errors, logs or candidate receipts. Production errors must be
masked; current synthetic debug errors are not a production setting.

Identity scope is full tenant + document binding, not the synthetic bridge's current
user/session/task triple. Worker environment, HOME/CODEX_HOME/config and filesystem
read isolation are independently required and remain unproven. No runtime startup is
authorized by this design or by source inspection alone.

## Proposed atomic candidate commit

A narrow repository method, reviewed separately from unrelated lifecycle work, must
perform one transaction/conditional mutation rather than fence-read then update:

- select/lock or UPDATE-CAS the exact task row;
- compare server-supplied expected immutable input digest;
- require current internal run, attempt, owner, epoch and task/run executable state;
- require unexpired lease and task deadline, using DB time rather than worker clock;
- recheck cancellation and binding and validate proposal equals registered operations;
- write the immutable receipt once (or return the exact existing receipt for an
  idempotent retry); a different receipt must conflict, never overwrite;
- return the authoritative persisted receipt, not the runner's uncommitted output.

Receipt contains binding identity, canonical proposal and operations digest, commit
identity/time and claimed attempt fence. No source file or arbitrary harness scratch
output can become an accepted document edit. Advisory pre-tool lease checks do not
replace this atomic commit. Parallel attempts, lease takeover, deadline/cancel race,
retries and rollback need real PostgreSQL regression coverage.

## Human acceptance is a different authorization boundary

Later explicit user acceptance must verify a current valid editor session/grant,
full NativeScope, document/revision/context/source and current draft snapshot against
the committed receipt. It must use the existing true preview and acceptance engine,
then save and independently read back. The old executor lease and old MCP ticket may
have expired legitimately after completion: do not require them still alive to accept
an immutable completed receipt. Conversely, an expired executor cannot append a new
receipt even if an earlier one exists.

Open review question: require task completion and reject cancelled/failed tasks even
if a candidate receipt committed before the later terminal transition? Conservative
proposal: only a completed task's receipt is available for human acceptance. Do not
silently decide this lifecycle policy while other agents edit the task machinery.

## Verification required before any enablement

- binding mismatch matrix: tenant/company/user/thread/document/revision/context/source,
  draft selection and capability changes; no model-supplied binding field trusted;
- actual MCP request authentication and wrong audience/nonce/attempt/expiry failures;
- real PostgreSQL CAS races: cancel, expiry, owner takeover, stale attempt, duplicate
  different candidate, exact retry, transaction rollback;
- crash/restart reconstructs immutable input and receipt, without replaying writes;
- completed receipt remains inspectable after lease expiry, but current grant/snapshot
  changes reject acceptance;
- complete real Word preview/explicit acceptance/save/readback with source hash and
  other-paragraph preservation;
- independent native harness runtime canary proof that production source/secrets are
  unreadable and scratch edits never enter document acceptance;
- real current-provider execution only after those boundaries are established.

No production capability is claimed by the existing 30 synthetic/offline tests.

## Review refinements: durable receipt recovery and cancellation

These refine the proposal only. Repository/schema implementation is intentionally
blocked until root integrates the shared lease fixes and assigns a single file owner.
The initial checkout's lifecycle code is evidence, not a promise that its exact APIs
or transaction behavior survive that integration unchanged.

### Persistence and confidentiality decisions

Use four dedicated nullable columns, pending the integrated baseline. Enforce at
schema and typed repository boundaries:

- input and input digest are both NULL or both non-NULL;
- receipt and candidate semantic digest are both NULL or both non-NULL;
- a receipt requires a non-NULL input;
- null legacy tasks cannot execute Word tools;
- unknown input/receipt versions are rejected, never treated as generic runnable work.

Do not add these private payload fields to generic TaskSnapshot serialization, logs,
result_text, model history, export artifacts or terminal messages. They contain
confidential paragraph/draft/instruction data, not just harmless metadata. A dedicated
authorized accessor is needed; normal status projections should expose at most a
non-sensitive readiness state, not the binding or source reference.

Minimize duplication: the initial instruction already has an immutable content hash
in the task instruction table. Prefer a server-resolved instruction reference+digest
over another full copy. Persist only the authorized frozen paragraph data needed for
candidate recovery, its original source identities and capability list, and the draft
snapshot/digest. Do not copy the whole document or all unselected draft operations by
default. If replay actually needs additional draft material, justify and bound it
explicitly before extending WordTaskInput. Acceptance obtains the user's current base
draft through the existing editor flow and verifies its snapshot, not a model payload.

A session reference must be an internal non-bearer lookup key, not a cookie/raw editor
grant/raw session token. Do not expose even that internal reference through MCP. Before
any resumed generation, an expired/revoked original editor authorization must not be
silently renewed. Completed receipt recovery does not need another model call.

Input/candidate visibility is limited to the trusted application coordinator and
correct full NativeScope; the worker gets only task-bound MCP paragraph reads. Retain
private input and receipt only under an explicit bounded task-retention policy shared
with task cleanup. Exact retention duration and cleanup implementation are still review
requirements, not defaults invented here. Pairwise columns must clear atomically and
cleanup must not leave a receipt without its matching input. Generic retention/export
of result text is not an excuse to copy these private payloads there.

Initialization must reuse the repository's existing schema advisory lock. This does
not prove rolling compatibility: an old worker can misinterpret new work or rewrite
schema-version markers. Migrate first, stop/disable old workers, and only then consider
Word task enablement. No rolling-compatible rollout is claimed.

### Stable candidate semantics versus commit provenance

Define the scalar native_word_candidate_sha256 as a stable semantic digest of the
input/binding digest plus canonical proposal. Do not include clock time, owner, epoch
or attempt in that semantic digest. The immutable stored receipt additionally records
origin commit provenance (original run/attempt/owner/epoch and commit time), plus a
versioned full-payload integrity digest if needed. These are separate identities.

For an exact candidate retry, first authenticate the CURRENT caller/claim and satisfy
the CURRENT task fence/deadline using a fresh database time. Then compare immutable
input and candidate semantic digest; return the original stored receipt including its
original timestamp. Do not generate a new timestamp and compare entire newly-built
receipts; do not let an expired/old ticket use idempotence as an authorization bypass.
A different candidate always conflicts, even from a newer legitimate attempt.

The original receipt's attempt fence is historical provenance, not a permanent
requirement that all future readers/resumers have that old attempt. New attempts must
claim their own current fence. They may recover the existing receipt but never rewrite
its origin metadata or replace its candidate.

Database time must be fresh AFTER acquiring a contested lock, and checked again in the
final write predicate. PostgreSQL now()/CURRENT_TIMESTAMP use transaction-start time:
a transaction waiting on a lock could otherwise pass a stale pre-expiry timestamp.
Use database clock_timestamp() at the guarded point or equivalent verified semantics.
Candidate publication must atomically compare current task/run state, attempt, owner,
epoch, expiry, deadline and input identity; a pre-read or local TaskSession assertion
is not a substitute.

### Crash/recovery state table

| Durable state at restart | Required next action | Forbidden action |
| --- | --- | --- |
| No input or one half of a required column pair | Reject Word execution as invalid/incomplete; legacy null tasks remain legacy | Infer document authority from task user/thread |
| Input valid, no candidate, current task runnable | Claim current lease; revalidate authorization, input and source/selection before generation | Use old ticket or inherited environment; guess selection |
| Candidate committed, task ACTIVE/NEW/SUSPENDED | Under a fresh valid claim, recover stored immutable candidate and proceed toward existing finish protocol | Re-run model or call propose again; overwrite candidate |
| Candidate committed, finish receipt not yet persisted | Build the existing finish request from the recovered candidate reference and current claim | Insert authorization binding into quality acceptance_contract |
| Candidate committed, task FINISHING | Recover/validate existing finish receipt and invoke supported finalization under current claim after baseline review | Force resume_current, which currently rejects FINISHING; create a different candidate |
| Task COMPLETED with matching immutable candidate | Serve candidate-only result to correctly authorized editor; allow explicit acceptance after current grant/snapshot checks | Require original executor lease/ticket still alive; auto-accept |
| Task CANCELLED/FAILED, or deadline terminally rejected | Keep receipt only for authorized diagnosis/retention; do not offer acceptance | Turn receipt existence into task success or bypass cancellation |

The two stages are intentionally distinct: committed candidate does NOT mean task
completed, and task completed does NOT mean document accepted or saved. A recovered
worker's finish request references the same stable candidate digest. Existing lifecycle
recovery integration must be verified after shared lease fixes; no extra replacement
state machine or supervisor is proposed.

For recovery after a new attempt is created, a narrow current-fence guarded repository
read/return path can return the original receipt once input/receipt integrity is proven.
It must not compare originCommit.attempt to the current attempt as an equality gate,
which would permanently strand otherwise valid committed work. Pending new user
instructions or changed input require the existing successor-task mechanism, not
mutation/reinterpretation of a frozen candidate.

### Cancellation and completion race: exact meaning

Existing cancel_and_reject returns the current snapshot unchanged for COMPLETED,
FAILED and CANCELLED. Therefore:

- Cancellation that wins BEFORE completion must prevent finalization/acceptance;
  an already committed receipt can remain stored but is not usable for acceptance.
- Completion that wins first makes a subsequent generic cancel a no-op. Do not say
  the completed candidate was revoked or erased. Report that generation had already
  completed; the user can discard/decline to accept that candidate.
- Hiding/discarding a completed candidate in the current editor view need not change
  generic task state. Cross-device durable candidate revocation would need a separate
  narrow editor-level revocation contract, not a retroactive generic task cancellation.
- A completed task's candidate still requires an unexpired current editor grant and
  matching scope/document/source/draft snapshot at every human acceptance attempt.
  Saved source and other paragraphs are changed only by the existing real engine.

The conservative policy is completed-only acceptance. Lease expiry alone after
completion is not cancellation. No lease is kept alive indefinitely for a human to
review a candidate. An old executor cannot append a late candidate; read access to a
completed receipt is independently scoped and is not an execution write authority.

### Additional PostgreSQL recovery tests required

1. Crash immediately before and after receipt commit: rollback yields no receipt;
   successful commit recovers exactly the stored receipt without another model call.
2. Crash after receipt commit but before request_finish; new owner/epoch and a new
   attempt reuse the same candidate and origin provenance, never regenerate it.
3. Crash after request_finish: FINISHING recovery finalizes the same finish/candidate
   reference without forcing the generic active-attempt resume path.
4. Receipt/candidate exact retry after lease takeover: current valid owner can recover;
   stale owner/epoch/attempt cannot use idempotence to write or recover as an executor.
5. Concurrent different candidates: one immutable receipt wins; loser conflicts.
6. Block on a row lock until lease/deadline expires: fresh DB time rejects publication,
   even when transaction-start now() would have been pre-expiry.
7. Cancellation versus finalization race: one serial ordering; cancellation-first makes
   receipt unusable, completion-first leaves completed task unchanged on generic cancel.
8. Completion then lease expiry: current-grant human acceptance can still proceed if
   every editor/document/draft digest matches. Expired/revoked/changed grant or draft
   rejects acceptance without claiming the document was modified.
9. Pairwise field constraints, malformed digest, unknown version, legacy NULL task,
   cleanup atomicity and no private payload leakage in status/log/export projections.
