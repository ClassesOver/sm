# AG-UI / HRP v2 Protocol

Version: `agui.odoo.v2`

This module integrates one chat runtime with the current native HRP 12
`BasicModel` / `Controller` / `Renderer`. React does not render or persist a
second HRP form model.

## Version Handshake

Before React is mounted, HRP `/agui_chat/config`, the loaded bundle, and the
configured AgentOS protocol endpoint must agree on:

```json
{
  "protocol": "agui.odoo.v2",
  "module_version": "12.0.8.8.3",
  "bundle_version": "12.0.8.8.3",
  "command_catalog_hash": "sha256"
}
```

AgentOS exposes `protocol`, `bundle_version`, and `command_catalog_hash` at the
`/config` URL derived from the configured `/agui` runtime URL. Missing or
mismatched declarations disable Chat and host tools. They never reject HRP
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

- `host` is projected only from the HRP `agui_host` snapshot. The browser
  `HostBridge` retains the complete local snapshot; AgentOS receives the
  model-facing projection, not a second business-state copy.
- `STATE_SNAPSHOT`, `STATE_DELTA`, and JSON Patch events write only `agent`.
  Attempts to patch `/host` are ignored and reported.
- `hostRevision` is a browser page revision. `sessionRevision` is the database
  session revision. They are never compared or restored into each other.
- The visible menu catalog is a separate host-owned snapshot. It is never stored
  in `RunAgentInput.state` or counted against the page snapshot budget, and a
  catalog-only change does not increment `hostRevision`.
- Session restore loads messages, `agentState`, and UI preferences. It never
  restores `hostState`.

For List/Kanban projections, `selection` contains only `model`, host-selected
`scope`, and `selectedCount`. Window-action and selection domain/context,
selected IDs, visible row candidates, and row-bound control labels stay in the
browser. Field metadata, aggregate view capabilities, and the exact
`viewTarget` remain available. Form snapshots keep their existing record and
control semantics.

Snapshots preserve metadata for every field in the final native view, including
binary and unsupported widget fields, while binary values remain omitted and
sensitive values remain redacted. `capabilities.x2many` discovers every
one2many directly from the complete Form `fieldsInfo`; it exports schema source,
schema hash/count, collection counts, operation state, a field token, and light
loaded-row tokens without child values or duplicated child-field maps.

The snapshot budget is 256 KiB. When necessary, the host removes non-dirty
record values, one2many values, and nonessential row display text in that order.
It never removes field metadata, dirty values, or required operation tokens. If
the remaining metadata and required state still exceed the budget, the host
returns `snapshot_too_large` instead of silently dropping fields.

## Client Tools

HRP publishes standard AG-UI client tool schemas in the current
`RunAgentInput.tools`:

- `odoo.read_mentioned_records`
- `odoo.open_mentioned_menu`
- `odoo.open_mentioned_record`
- `odoo.apply_mentioned_filter`
- `odoo.search_menu`
- `odoo.open_menu`
- `odoo.apply_filter`
- `odoo.apply_group`
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

Mention tools carry a page target containing `snapshotId` and `hostRevision`.
`odoo.search_menu` and `odoo.open_menu` use a dedicated menu target that also
contains `catalogId` and `catalogRevision`. Commands bound to the current view
carry the full target with `controllerId`, `dataPointId`, `model`, and `resId`.
Missing or stale target members fail closed. The server idempotency binding also
includes the menu catalog identity when present.

List/Kanban snapshots expose native grouping as host-owned capabilities:

```json
{
  "group": true,
  "groupFields": {
    "document_type": {
      "name": "document_type",
      "string": "单据类型",
      "type": "selection",
      "intervals": []
    },
    "document_date": {
      "name": "document_date",
      "string": "单据日期",
      "type": "date",
      "intervals": ["day", "week", "month", "quarter", "year"]
    }
  },
  "groupBy": [{"field": "document_date", "interval": "month"}]
}
```

`groupFields` contains only sortable, non-sensitive fields exposed by the native
SearchView Group By menu. Supported types are `many2one`, `char`, `boolean`,
`selection`, `date`, and `datetime`. Form views and views with grouping disabled
return `group: false`, an empty field map, and an empty current state.

`odoo.apply_group` accepts the exact current `viewTarget` and a required
`groupBy` array with at most three items. Each item requires `field`; date and
datetime items may also provide `interval` as `day`, `week`, `month`, `quarter`,
or `year`, with `month` as the default. The array replaces the complete current
grouping in the given order; `[]` clears grouping. It is never an incremental
add/remove operation.

The page command is declared with this complete JSON Schema:

```json
{
  "name": "odoo.apply_group",
  "parameters": {
    "type": "object",
    "additionalProperties": false,
    "required": ["target", "groupBy"],
    "properties": {
      "target": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "snapshotId",
          "hostRevision",
          "controllerId",
          "dataPointId",
          "model",
          "resId"
        ],
        "properties": {
          "snapshotId": {"type": "string"},
          "hostRevision": {"type": "integer"},
          "controllerId": {"type": "string"},
          "dataPointId": {"type": ["string", "boolean"]},
          "model": {"type": ["string", "boolean"]},
          "resId": {"type": ["integer", "boolean"]}
        }
      },
      "groupBy": {
        "type": "array",
        "maxItems": 3,
        "items": {
          "type": "object",
          "additionalProperties": false,
          "required": ["field"],
          "properties": {
            "field": {
              "type": "string",
              "minLength": 1,
              "maxLength": 128
            },
            "interval": {
              "type": "string",
              "enum": ["day", "week", "month", "quarter", "year"]
            }
          }
        }
      }
    }
  }
}
```

The host removes only `groupByCategory` facets, reuses or creates native
`Filter`/`FilterGroup` mappings and menu items, updates date intervals, and
triggers one query reset. Other filter facets, domains, ordering, and context are
preserved. An active favorite keeps its domain, ordering, and other context, but
its own `group_by` is stripped so it cannot overwrite the requested grouping.
The host never writes `BasicModel.groupedBy` directly.

The command is a read-level page command, is not a member of `WRITE_COMMANDS`,
and does not require write confirmation. Stable grouping failures are
`group_unavailable`, `invalid_group_by`, `invalid_group_field`, and
`invalid_group_interval`. A successful result returns `applied: true`, the
normalized effective `groupBy`, and the refreshed `snapshotId` and
`hostRevision`.

Navigation without an explicit `@` selection is available only when both menu
tools are declared. The agent first calls `odoo.search_menu` with the user's
original name or path. The host normalizes wrappers, whitespace, separators, and
case, then prefers exact full-path or leaf-name matches and uses contains matches
only when no exact result exists. Results include `matchType`, `matchCount`,
`truncated`, catalog metadata, and at most eight candidates. Any ambiguous result
stops for user selection.

An immediately following ordinal reply from `第一个` through `第八个` (including
Arabic digits and optional `选择`) becomes an explicit menu selection only when
that candidate still has the same menu/action IDs in the current catalog and the
search result catalog ID and revision are unchanged. React then exposes only
`odoo.open_menu` for the first page action and supplies the selected catalog
binding to the host. Missing, out-of-range, stale, or already completed choices
remain ordinary conversation input and never authorize navigation.

For an explicit `打开`, `进入`, `导航到`, or `跳转到` request whose target exactly
matches a visible leaf name or full path, React adds `HRP 菜单导航请求` without
menu/action IDs. The initial phase requires `odoo.search_menu`; a same-catalog,
non-truncated unique result advances the next continuation to a required
`odoo.open_menu` only when its echoed query normalizes to the original request;
otherwise the continuation remains in the required search phase. AgentOS uses a
forced tool choice for each phase and rejects
plain text or a different first executable event with `required_tool_violation`.
Questions, unknown targets, ambiguous results, stale catalogs, and completed
opens do not receive this forced-navigation context.

The full visible directory is not sent on the first Run. Only after a same-catalog
`matchType=none` result does the immediately following client-tool continuation
receive `当前用户可见 HRP 菜单`. This context contains only catalog metadata,
completeness, and original `fullPath` strings, never menu/action IDs. Its UTF-8
budget is 128 KiB and paths are never truncated. If `complete=false`, semantic
rewrites are forbidden and the user must select with `@`. From a complete catalog
the agent may retry at most two original paths. `odoo.open_menu` still requires a
unique result in the same page, catalog, thread, and Run, or an explicit current
selection. Catalog changes return `stale_menu_catalog`; action changes return
`menu_action_conflict`; missing evidence returns `menu_search_required`.

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

Saved and current filters support separate `read` and `apply` bindings. `read`
is available only when `odoo.business.report.filters` is enabled and the
current user matches an exact-model report policy. It is not a page action and
up to five filters may coexist. `apply` remains a page action. Record `read`
authorization never authorizes filter data access because validation includes
both resource kind and action.

`odoo.read_mentioned_records` accepts one to five tokens bound to `read`. An
exact-model policy `field_names` allowlist wins; otherwise fields are derived
from the default form view. Secret-like, configured-sensitive, and binary
fields are always removed. HTML becomes plain text, scalar text is truncated,
many2one returns its display name, and x2many returns only a count. Results are
limited to twenty fields per record and 64 KB per call.

Mentioned filters replace the current query through HRP 12 `FavoriteMenu` and
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
  current HRP user.
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
- Scalars use HRP field parsers; many2one accepts an explicit integer ID, an
  HRP-style `[ID, displayName]` pair, or a snapshot-style `{id, displayName}`
  object.
- many2many supports only `link`, `unlink`, and `replace` of existing IDs.
- one2many accepts at most 40 total `create`, `update`, and `delete`
  operations across the patch. Parent-form batch operations are rejected with
  `requires_form_activation` unless the complete child schema is already loaded.
  Normal create/open/edit flows use `odoo.open_x2many_create` and
  `odoo.open_x2many_record`; large imports use the registered schema hash flow.
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

### One2many Import Preview

`agui_chat_import` does not embed the legacy ImportView and never calls
`execute_import()` or `load()`. `POST /agui_chat_import/prepare` copies an owned
Chat attachment into a persistent import job and immediately creates a
server-side preview. `POST /agui_chat_import/preview` accepts only `jobToken`,
`expectedRevision`, `parseOptions`, `mapping`, and the JSON boolean `finalize`.
Status recovery uses `POST /agui_chat_import/status`; bounded error reports use
`GET /agui_chat_import/error/<jobToken>`.

The server creates a temporary `base_import.import` wizard in the submitting
user and company environment and calls `parse_preview(options, count=20)`.
Odoo's full field tree and generic matches are discarded. The returned
`preview.kind` is `x2many_import`; its `import` value contains the file summary,
row count, headers, at most 20 truncated rows, profile-only target fields,
mapping, normalized CSV options, errors, revision, mapping hash, target, and
schema hashes. Files are limited to 50 columns and 80-character headers. The
preview envelope has a 96 KiB budget, so wide previews can return fewer rows.
Full converted rows never enter Chat messages or AG-UI events.

Mappings may use only registered profile source columns and target fields. A
target field cannot be selected twice and every required target must be mapped.
Each preview update locks the job and compares `expectedRevision`. Only
`finalize=true` performs full conversion of at most 2,000 rows and changes
`preview` to `ready`. React then sends a hidden bounded user message containing
only `kind=x2many_import_ready`, `jobToken`, `revision`, and `mappingHash`; this
starts an ordinary Agent run rather than a custom interrupt.

The business authorization can be prepared only while the job is `ready` and
includes the same trusted preview. Approval synchronously locks authorization,
job, and parent record, then rechecks user/company, ACL, record rules,
`write_date`, profile, file, and mapping hashes. A single parent One2many write
runs inside a savepoint. Existing command execution idempotency stores the
result, so a lost response cannot create the rows twice. Terminal jobs clear the
source attachment, full converted rows, and preview rows immediately. The
existing audit-retention cron later deletes all expired import jobs and their
source/error attachments, including abandoned previews; there is no import
execution cron.

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

Registered commands default to `write`. A command explicitly registered as
`read` remains published and executable while `write_tools_enabled` is off.
Both access levels still require an exact matching policy. A binding resolver
may bind current-message opaque tokens and emit per-model policy inputs; it is
run again during execution so token visibility, ACL, record rules, company,
browser session, expiry, and policy revocation fail the whole batch atomically.

The browser calls `/agui_chat/business/prepare`, reuses the normal confirmation
UI when required, and then calls `/agui_chat/business/execute` with the
server-bound payload and authorization token. Business commands require an
exact tool policy; missing policies fail closed. Each plugin owns its model
ACL, record-rule, state, and domain checks. The executor additionally applies
server-side schema validation, user/company/run/tool-call payload binding,
authorization expiry, idempotency locking, a database savepoint, stored result
replay, default sensitive-key redaction, and redacted audit. There is no generic
business handler, RPC, CRUD, or arbitrary model-method fallback.

### Filter Reports

`odoo.business.report.filters` is a read-only command and is not enabled by
default. The legacy source contains one to five filter tokens selected in the
current message. It supports:

- `describe`: row count, allowed fields/types, original grouping, and allowed
  aggregations;
- `detail`: up to 30 fields and at most 5000 rows per filter, with no silent
  truncation;
- `aggregate`: up to two dimensions, five `count/sum/avg/min/max` metrics, and
  5000 result groups.

Saved filter expressions are parsed in HRP's restricted evaluation
environment. Temporary filters use their bound structured values. Domain,
sort, original grouping, requested dimensions, and metrics must use policy
fields. Sensitive, binary, one2many, and many2many fields are always rejected.
Date grouping uses the HRP user's timezone. Monetary metrics require their
currency field as a dimension; no implicit conversion is performed.

Detail and aggregate output is uploaded as `reports/data/<uuid>.jsonl` plus a
`.meta.json` file through the existing thread capability. Metadata contains the
filter label, model, fields, row count, aggregation basis, timezone, currency
rule, generation time, and a domain fingerprint, but no token or full domain.
An upload failure removes files created by that call.

The same command also accepts a `current_view` source for the current
interactive List/Kanban. The Agent sends only `source.kind`, the exact
`viewTarget`, a mode, and one request. Before business preparation, the browser
reads the complete domain, context, sort, grouping, and selected IDs directly
from the current BasicModel and calls `/agui_chat/report/source/bind`. The
binding is limited to 256 KiB and 5000 selected IDs and is tied to user,
company, browser session, thread, snapshot, controller, menu, action, expiry,
and a scope fingerprint. The returned `sourceHandle` is not authorization.

`current_view` scope is host-defined: selected rows mean the intersection of
the current domain and selected IDs; no selection means the full current
domain. Selected IDs must all survive ACL, record-rule, company, and domain
checks or the whole request fails. Preparation and execution repeat source,
policy, expiry, and selection checks. A changed page returns
`stale_report_source`; the Agent cannot submit domain/context/IDs or switch
between selected and domain scope.

`current_view/describe` returns only the handle, scope/counts, model, field
schema, timezone, generation time, and fingerprint. `detail` preserves the
BasicModel ordering and exports at most 100000 rows and 30 fields. Odoo writes
up to 16 JSONL fragments of 8 MiB each (100 MiB total, 128 MiB estimated
expanded memory) under `报表/原始数据/<dataset-uuid>/分片/`, uploads
`数据集.json` last, and rolls back every uploaded file if any upload fails. The
manifest contains paths, sizes, SHA-256 values, schema, counts, scope, timezone,
time, and fingerprint but no query state or record values. A successful detail
or aggregate consumes the source and immediately clears its stored query state
and IDs. Oversized detail requires a narrower page range or explicit Odoo
aggregate mode.

AgentOS registers seven model-facing adapters: `pandas_profile_dataset`,
`pandas_sample_dataset`, `pandas_group_dataset`, `pandas_pivot_dataset`,
`pandas_concat_datasets`, `pandas_generate_chart`, and
`pandas_create_report_config`. Each call downloads only from the current thread,
creates a fresh Agno `PandasTools` instance over temporary local files, and
releases all frames immediately. Native arbitrary Pandas functions are not
published. Inputs are limited to 100000 rows, 100 columns, 128 MiB expanded
memory, and model-visible results to 32 KiB. Manifest datasets additionally
limit schema to 30 columns and validate canonical UUID paths, fragment order,
size, SHA-256, total rows, and total bytes while keeping only one fragment in
memory. `profile` never returns raw rows; `sample` alone may return at most 20
rows and 10 columns. CSV and JSONL loaders read at most
100001 rows before rejecting an over-limit dataset. Top-level JSON arrays are
shape-scanned before Pandas materializes them; XLSX archives are checked for
member count, expanded size, and selected-sheet dimensions before loading.
New analysis, chart, config, and final artifacts use structured UUID paths under
`报表/分析数据/`, `报表/图表/`, `报表/配置/`, and `报表/生成结果/`.
Historical `reports/` paths are not migrated. Text reads reject controlled raw
JSONL paths in both layouts; user downloads remain available.

The trusted `odoo-current-view-report` skill creates a non-raw config through
the config adapter, then requires one confirmation before running its bundled
script. The script revalidates config, manifest, fragment paths/sizes/hashes,
and all rows before rendering. Its `agui.odoo.report.skill.v1` command protocol
exposes `capabilities`, `validate`, and `render`; the normal agent path calls
only `render`, which atomically publishes `分析报告.pdf`. Chart PNG data is
temporary and is removed before publication. The final config and PDF never
contain raw-row samples; bounded samples remain an analysis-only tool. Stdout
contains one versioned JSON result envelope and never contains raw rows.

`DELETE /workspace/file` accepts only `threadId`, `path`, and the optional JSON
boolean `recursive`; string or numeric boolean lookalikes and unknown fields are
rejected. Workspace downloads send an ASCII `filename` fallback plus RFC 5987
`filename*=UTF-8''...`, so non-ASCII names remain valid without putting Unicode
directly into the Latin-1 response header.

## Sessions And Surfaces

Session JSON endpoints remain under `/agui_chat/session/*`. Payload fields are
`messages`, `agentState`, `uiPreferences`, and `sessionRevision`.

`POST /agui` uses incremental run messages. A normal run sends only the latest
user message. A client-tool continuation sends only the consecutive trailing
`tool` result messages, in their original order. Tool declarations, the current
page context and the state envelope are still sent in full on every request. The
separate menu path directory is sent only on the no-result continuation described
above.
AgentOS PostgreSQL is the conversation-history authority and loads the latest
10 runs. HRP `session/save` continues to persist the complete UI message
snapshot for restoration and revision merging.

Every final assistant message stores its AgentOS run identifier in
`extra_data.agent_run_id`. All client-tool continuations belonging to one turn
reuse that identifier. `forwardedProps` is empty for ordinary runs; branch runs
allow only `branch.sourceThreadId`, `branch.sourceRunId`, and
`branch.targetMessageId`. Identity and arbitrary backend parameters are never
forwarded there.

`session/fork` locks and refreshes the source session, creates a new session
named `原名称（分支）`, records `parent_session_id`, and copies only messages
before the selected final answer. Referenced HRP attachments are copied to the
new session and their IDs are rewritten. The branch inherits UI preferences,
agent state, surface and agent selection, but receives a fresh `thread_id`.

AgentOS verifies capabilities for both source and target threads and requires
the same database, user, company and browser-session identity. It copies source
runs only through the selected run, assigns every copied run a fresh ID, emits
the old-to-new mapping, and calls Agno regeneration with `regenerate=true` and
`replace_original=true`. The selected run's completed tool exchanges remain in
history and are not executed again. The source session is never modified.

Branch workspaces copy the source session's current files, not a historical
snapshot at the selected run. Inventory is validated before the target sandbox
is created: at most 2000 regular files, 256 MiB total and 25 MiB per file are
allowed. Symbolic links, non-regular files, invalid paths and all over-limit
workspaces reject the whole operation. A failure before `RUN_STARTED` removes
prepared AgentOS/workspace state; React archives the HRP branch and stays in
the source session. A model error after `RUN_STARTED` remains visible in the
branch. Agent session persistence and branch workspace copy/rollback use the
native asynchronous PostgreSQL and Daytona clients, so branch preparation does
not block the AG-UI SSE event loop. Controlled branch failures emit their stable
`branch_*` value in `RUN_ERROR.code`; unexpected failures use `branch_failed`.
Client messages never contain raw backend exception text.

Every save supplies `expectedSessionRevision`. On the first revision conflict,
React reloads the session, merges local and remote messages by message ID, and
retries once. A second conflict leaves the in-memory messages and confirmation
result intact and reports an explicit error; it never silently drops them.

Only `dock` and `standalone` surfaces exist. `standalone` is a movable,
resizable floating window inside the WebClient; the protocol value is retained
for compatibility with existing sessions.
Switching surfaces moves the one stable React host node; it does not unmount,
reload a session, or cancel the active SSE run.

Upgrading to `12.0.8.8.0` archives every previously active HRP chat session and
enqueues its workspace for the existing cleanup worker. HRP and AgentOS audit
data are retained, but old threads are never reused. The first chat entry after
upgrade creates a new run-ID-capable session automatically.
