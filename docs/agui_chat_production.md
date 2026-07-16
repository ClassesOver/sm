# AG-UI Chat v2 Production Deployment

## Topology

The browser posts standard AG-UI input directly to the same-origin AgentOS
proxy and consumes SSE. Odoo serves configuration, UI sessions, host-command
policy, and named synchronous business commands. Odoo never proxies SSE.

Configure one public runtime path:

- `runtime_url`: AgentOS AG-UI POST endpoint, for example
  `/contract-review/agui`.

Odoo derives `/contract-review/config` from that value for the protocol
handshake. AgentOS must expose the derived JSON declaration endpoint.

The declaration must contain the deployed `agui.odoo.v2` protocol, bundle
version, and Odoo command catalog hash. Nginx must not retry the AG-UI POST.
Disable proxy buffering, caching, and compression for SSE, and size connection
limits for at least 200 concurrent streams.

## Rollout Controls

New installs and upgrades start with Chat disabled. Enable in this order:

1. `chat_enabled`
2. `host_tools_enabled`
3. exact entries in `enabled_commands`
4. `write_tools_enabled`
5. exact entries in `enabled_business_commands`

An empty command list enables no commands. Tool policies still default-deny by
exact command, user group, model, and field allowlist. Kill switches disable
the affected feature without RPC, CRUD, or simulated-state fallback.

The module includes a read-only `odoo.apply_filter` policy for `hr.employee`
and internal users. It only applies on the current bound List or Kanban view;
Odoo access controls, record rules, and the snapshot `filterFields` allowlist
still determine which employee records and fields can be filtered. Keep
model-specific policies for any additional models instead of adding a global
filter policy.

## Deployment

Deploy the Python module and versioned React bundle together, then purge old
asset caches. A module/bundle mismatch fails the handshake and keeps Chat
disabled.

## Security

- Production runtime URLs are same-origin. Absolute URLs require the explicit
  development flag and exact credentialed CORS origin.
- Every modifying browser command uses one payload-bound authorization and an
  idempotency key derived from user/company/thread/run/tool call.
- Business command handlers run with the current Odoo user, never `sudo`, and
  execute inside a savepoint. Failed handlers roll back their business writes.
- Binary fields and secrets are not sent in host snapshots. Audit details are
  recursively redacted and bounded.
- Session saves use `expectedSessionRevision` plus `SELECT ... FOR UPDATE`.

## Failure Acceptance

Inject AgentOS 401/403/429/500, non-SSE responses, malformed/oversized events,
disconnects, and timeouts. Also test missing bundles, handshake mismatches,
onchange/save failures, stale controllers, duplicated tool events, replayed
tokens, and multi-tab session conflicts.

In every case Odoo navigation, form editing, onchange, validation, save, and
discard must remain available. WebClient startup never waits for Chat. There
must be one React root, one active run, and one session save queue.

Run the load baseline with:

```bash
node scripts/agui_sse_load.js https://odoo.example.com/contract-review/agui 200
```

The production target is below 1% transport errors, with aborted browser runs
releasing upstream connections promptly.
