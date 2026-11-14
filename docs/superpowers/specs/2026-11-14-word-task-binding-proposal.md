# Word task binding and trusted MCP identity: review proposal

Status: **proposal only, not implemented or enabled**. No task lifecycle, repository,
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
