# AG-UI / Odoo v2 Protocol

Version: `agui.odoo.v2`

This module integrates one React AG-UI runtime with the current native Odoo 12
`BasicModel` / `Controller` / `Renderer`. React does not render or persist a
second Odoo form model.

## Version Handshake

Before React is mounted, Odoo `/agui_chat/config`, the loaded bundle, and the
configured AgentOS protocol endpoint must agree on:

```json
{
  "protocol": "agui.odoo.v2",
  "module_version": "12.0.7.0.0",
  "bundle_version": "12.0.7.0.0",
  "command_catalog_hash": "sha256"
}
```

AgentOS exposes `protocol`, `bundle_version`, and `command_catalog_hash` at the
`/config` URL derived from the configured `/agui` runtime URL. Missing or
mismatched declarations disable Chat and host tools. They never reject Odoo
WebClient startup.

## State Ownership

Every `RunAgentInput.state` has exactly this envelope:

```json
{
  "protocol": "agui.odoo.v2",
  "host": {
    "snapshotId": "agui-...",
    "hostRevision": 8,
    "interactive": true,
    "surface": "dock",
    "controller": {}
  },
  "agent": {}
}
```

- `host` is written only by the Odoo `agui_host` service from the current
  ActionManager controller and BasicModel data point.
- `STATE_SNAPSHOT`, `STATE_DELTA`, and JSON Patch events write only `agent`.
  Attempts to patch `/host` are ignored and reported.
- `hostRevision` is a browser page revision. `sessionRevision` is the database
  session revision. They are never compared or restored into each other.
- Session restore loads messages, `agentState`, and UI preferences. It never
  restores `hostState`.

Snapshots omit binary fields, redact sensitive fields, bound text and relation
sizes, and export x2many values as persisted IDs/count only.

## Client Tools

Odoo publishes standard AG-UI client tool schemas in the current
`RunAgentInput.tools`:

- `odoo.search_relation`
- `odoo.patch_current_form`
- `odoo.validate_current_form`
- `odoo.save_current_form`
- `odoo.discard_current_form`

React executes a tool only if its exact name was declared for that run. Agno
server tools remain display-only until their `TOOL_CALL_RESULT` arrives.

Every host command carries a `target` containing `snapshotId`, `hostRevision`,
`controllerId`, `dataPointId`, `model`, and `resId`. Missing or stale target
members fail closed. Patch/save/discard also require a server-bound one-time
authorization.

Relation search rules:

- `odoo.search_relation` only accepts fields from the current native form and
  supports writable many2one/many2many fields.
- The browser evaluates `record.getDomain({fieldName})` and
  `record.getContext({fieldName})` against the live BasicModel data point,
  including unsaved onchange/dirty state, then calls `name_search` as the
  current Odoo user.
- Raw domain/context values are never accepted from or returned to the Agent.
- One exact candidate may be used directly. Multiple candidates require an
  explicit user selection; the Agent must never guess an ID.
- Relation IDs are checked again against the latest domain before a patch is
  applied. Many2many unlink is limited to IDs currently selected.

Patch rules:

- Fields must be present in `fieldsInfo.form` and currently visible/writable.
- Existing dirty fields conflict; partial application is not allowed.
- Scalars use Odoo field parsers; many2one accepts an explicit integer ID or
  an Odoo-style `[ID, displayName]` pair.
- many2many supports only `link`, `unlink`, and `replace` of existing IDs.
- Generic one2many create/update/delete is rejected.
- Changes use `FormController._applyChanges`; there is no RPC fallback.

Patch policies expose `confirmation_mode` with `risk` (default), `always`, and
`never`, plus an optional high-risk field allowlist. In `risk` mode the server,
not the Agent, requires confirmation for multi-field patches, many2one or
many2many fields, and policy-marked fields. A high-risk prepare must include a
preview built from the live BasicModel. Each preview change contains the field
name and label, field type, old value, new value, and risk reasons. Sensitive
values are shown only as `[redacted]`.

The preview and authorization are bound to the current controller, record,
snapshot, and `hostRevision`. If that binding changes before approval, the old
authorization is rejected and a fresh preview requires a new confirmation. A
low-risk patch may refresh and rebind once when only the snapshot of the same
record is stale. Dirty-field conflicts, ACL failures, validation errors,
onchange failures, and save failures are never retried automatically.

Save uses `saveRecord()`. Validation uses the current Renderer. Approved
discard calls the native discard path once. Navigation refuses a dirty form.

Host results use stable `code` values and include `operation`, `hostRevision`,
and `retryable` when execution reached the browser host. Patch results also
include the structured `preview` and a `receipt` describing the saved changes.
Examples of terminal failures include `dirty_conflict`, `validation_failed`,
`onchange_failed`, `save_failed`, `stale_snapshot`, and `undo_conflict`.

## Browser Authorization

`/agui_chat/host_command` is the single browser-command policy endpoint. Its
prepare/confirm/complete phases bind the exact command payload to user,
company, run, thread, and tool call IDs. Replayed idempotency keys return a
stored result or fail as in-progress; payload changes are rejected.

Confirmation approval or rejection is persisted before React starts exactly
one follow-up Agent run. Duplicate confirmation events are ignored or replay
the stored result, so they cannot execute the command or resume the Agent
twice.

A successful eligible patch receives a one-time undo authorization that expires
after ten minutes. Undo is an internal host operation and is not published in
the Agent tool catalog. It supports the existing scalar, many2one, and
many2many patch forms; sensitive fields, binary fields, and one2many fields do
not produce an undo authorization. Before applying the inverse patch, the host
requires the same current record, no related dirty fields, and current values
equal to the values written by the original patch. Otherwise it returns
`undo_conflict` without overwriting newer data. Undo execution and its failure
result are stored for idempotent replay.

Action simulation, generic RPC/CRUD, and arbitrary model methods are not part
of this protocol.

## Business Commands

Synchronous server-side commands use `/agui_chat/business/execute` and exact
names under `odoo.business.<domain>.<verb>`. Each command must be registered in
the Python registry with a schema and handler. The executor applies schema
validation, current-user ACL/record rules, payload-bound authorization,
idempotency locking, a database savepoint, stored result replay, and redacted
audit. There is no generic business handler.

## Sessions And Surfaces

Session JSON endpoints remain under `/agui_chat/session/*`. Payload fields are
`messages`, `agentState`, `uiPreferences`, and `sessionRevision`.

Every save supplies `expectedSessionRevision`. On the first revision conflict,
React reloads the session, merges local and remote messages by message ID, and
retries once. A second conflict leaves the in-memory messages and confirmation
result intact and reports an explicit error; it never silently drops them.

Only `dock` and `standalone` surfaces exist. `standalone` is a movable,
resizable floating window inside the WebClient; the protocol value is retained
for compatibility with existing sessions.
Switching surfaces moves the one stable React host node; it does not unmount,
reload a session, or cancel the active SSE run.
