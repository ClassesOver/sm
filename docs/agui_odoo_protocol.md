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
  "module_version": "12.0.8.6.0",
  "bundle_version": "12.0.8.6.0",
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
sizes, and keep x2many IDs/count bounded. Standard one2many subviews additionally
export operation capabilities, child field metadata, and up to 40 loaded rows.

## Client Tools

Odoo publishes standard AG-UI client tool schemas in the current
`RunAgentInput.tools`:

- `odoo.read_mentioned_records`
- `odoo.open_mentioned_menu`
- `odoo.open_mentioned_record`
- `odoo.apply_mentioned_filter`
- `odoo.open_menu`
- `odoo.apply_filter`
- `odoo.open_record`
- `odoo.open_create`
- `odoo.enter_edit_mode`
- `odoo.activate_view_control`
- `odoo.search_relation`
- `odoo.stage_current_form`
- `odoo.patch_current_form`
- `odoo.validate_current_form`
- `odoo.save_current_form`
- `odoo.discard_current_form`

React executes a tool only if its exact name was declared for that run. Agno
server tools remain display-only until their `TOOL_CALL_RESULT` arrives.

Mention tools and `odoo.open_menu` carry a page target containing only
`snapshotId` and `hostRevision`. Commands bound to the current view carry the
full target with `controllerId`, `dataPointId`, `model`, and `resId`. Missing or
stale target members fail closed. Stage/patch/save/discard and all mention tools also
require a server-bound one-time authorization.

## Object References

User messages may contain up to five discriminated `mentions`. A message may
contain at most one action that changes the page. The legacy `menuMention`
field remains readable for stored sessions.

Search candidates expire after five minutes. An explicit action choice binds a
new two-hour opaque token to the current user, company, browser session,
resource kind, and exact action. AG-UI receives only the final token and display
metadata; record IDs and filter domain/context never enter the AG-UI request.

Record search runs `name_search` as the current user across at most twenty
models exposed by visible window-action menus. Saved filters come from
`ir.filters.get_filters`; temporary filters are evaluated and size-limited by
the native host before tokenization. Execution repeats menu, ACL, record-rule,
company, filter-visibility, expiry, and exact-action checks.

`odoo.read_mentioned_records` accepts one to five tokens bound to `read`. An
exact-model policy `field_names` allowlist wins; otherwise fields are derived
from the default form view. Secret-like, configured-sensitive, and binary
fields are always removed. HTML becomes plain text, scalar text is truncated,
many2one returns its display name, and x2many returns only a count. Results are
limited to twenty fields per record and 64 KB per call.

Mentioned filters replace the current query through Odoo 12 `FavoriteMenu` and
`SearchView`, including context, group-by, and sort. Cross-menu record actions
re-enter the token-bound menu before switching its native controller to the
form; dirty forms still reject navigation.

Relation search rules:

- `odoo.search_relation` only accepts fields from the current native form and
  supports writable many2one/many2many fields. A loaded one2many row is bound
  by its current `rowToken`; the relation field name remains the child field
  name from that row snapshot.
- A new row must first be created through its visible native create control.
  After staging scalar dependencies with the issued row token, relation search
  evaluates the resulting live child data point and its onchange state.
- The browser evaluates `record.getDomain({fieldName})` and
  `record.getContext({fieldName})` against the live BasicModel data point,
  including unsaved onchange/dirty state, then calls `name_search` as the
  current Odoo user.
- Raw domain/context values are never accepted from or returned to the Agent.
- One exact candidate may be used directly. Multiple candidates require an
  explicit user selection; the Agent must never guess an ID.
- Relation IDs are checked again against the latest domain before a patch is
  applied. Many2many unlink is limited to IDs currently selected.

Stage rules:

- `odoo.stage_current_form` uses the same visible/writable field validation,
  native `_applyChanges`, relation-domain recheck, and onchange completion as a
  patch, but never calls `saveRecord()`.
- Every successful stage publishes a fresh snapshot. Later relation searches,
  validation, and save must use that snapshot rather than stale tokens.

Patch rules:

- Fields must be present in `fieldsInfo.form` and currently visible/writable.
- Existing dirty fields conflict; partial application is not allowed.
- Scalars use Odoo field parsers; many2one accepts an explicit integer ID, an
  Odoo-style `[ID, displayName]` pair, or a snapshot-style `{id, displayName}`
  object.
- many2many supports only `link`, `unlink`, and `replace` of existing IDs.
- one2many accepts at most 40 total `create`, `update`, and `delete`
  operations across the patch. Update/delete IDs must be persisted rows loaded
  in the bound snapshot. Batch create accepts visible scalar child values;
  relational child values require a native row token. Loaded-row updates
  support the existing scalar, many2one, and many2many forms.
- Patches containing one2many use native BasicModel `CREATE`, `UPDATE`, and
  `DELETE`. Patch saves the parent once; stage keeps the parent dirty for a
  later explicit validate/save. There is no generic RPC fallback.

Patch policies expose `confirmation_mode` with `risk` (default), `always`, and
`never`, plus an optional high-risk field allowlist. In `risk` mode the server,
not the Agent, requires confirmation for multi-field patches, many2one or
many2many/one2many fields, and policy-marked fields. A high-risk prepare must include a
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

Synchronous server-side commands use exact names under
`odoo.business.<domain>.<verb>`. Only commands present in both the Python
registry and `enabled_business_commands` are published as client tools for the
current Run; their registered JSON schema is the tool's `parameters`.

The browser calls `/agui_chat/business/prepare`, reuses the normal confirmation
UI when required, and then calls `/agui_chat/business/execute` with the
server-bound payload and authorization token. Business commands require an
exact tool policy; missing policies fail closed. Each plugin owns its model
ACL, record-rule, state, and domain checks. The executor additionally applies
server-side schema validation, user/company/run/tool-call payload binding,
authorization expiry, idempotency locking, a database savepoint, stored result
replay, default sensitive-key redaction, and redacted audit. There is no generic
business handler, RPC, CRUD, or arbitrary model-method fallback.

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
