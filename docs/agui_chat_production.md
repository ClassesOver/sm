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

An empty command list enables no commands. A matching tool policy restricts the
exact command, user group, model, and field allowlist; without a matching
policy, no additional policy restriction is applied. Kill switches disable the
affected feature without RPC, CRUD, or simulated-state fallback.

The module includes a read-only `odoo.apply_filter` policy that restricts
`hr.employee` filtering to internal users. It only applies on the current bound
List or Kanban view; Odoo access controls, record rules, and the snapshot
`filterFields` allowlist still determine which records and fields can be
filtered. Add model-specific policies where additional user-group or field
restrictions are required.

## Deployment

Deploy the Python module and versioned React bundle together, then purge old
asset caches. A module/bundle mismatch fails the handshake and keeps Chat
disabled.

## Isolated Workspaces

The repository includes `docker-compose.daytona.yml`, based on the official
Daytona OSS Compose topology at `v0.189.0`. This is the last upstream version
that includes the supported OSS Compose baseline used by this project. Upstream
has since ended on-premises support, so treat this pinned stack as software the
operator must maintain and security-patch independently.

Daytona is licensed under AGPL-3.0. If a modified Daytona service is made
available over a network, provide the corresponding source, including those
modifications, to its users under AGPL-3.0. Keep the exact source revision and
container provenance with deployment records; this section is operational
guidance, not legal advice.

The project deploys only these Daytona services:

- `api`, `runner`, `db`, `redis`, `minio`, `registry`, and `dex`
- `dashboard`, as a localhost-only Nginx entry to the API UI and Dex
- `proxy`, as a localhost-only sandbox port-preview endpoint
- the existing `agent` service, which contains AgentOS and Agno

SSH Gateway, PgAdmin, Jaeger, and the OpenTelemetry collector are intentionally
not deployed. AgentOS Toolbox traffic uses `PROXY_TOOLBOX_BASE_URL=http://api:3000/api`;
the Proxy remains available only for sandbox HTTP previews.

### Requirements and Secrets

Allocate at least 4 GB RAM; 8 GB is recommended before running real sandbox
lifecycles. Concurrent code execution may require more. Docker and the Daytona
Runner require a Linux host with cgroup support. The Runner mounts the host
Docker socket and runs privileged, which is effectively host-level authority;
place it on a dedicated host or VM and restrict administrator access.

Set all required Compose variables in a protected environment file. Do not use
sample or default passwords in production. Required values include:

- `AGUI_WORKSPACE_HMAC_SECRET`, at least 32 random bytes, identical to the Odoo
  system parameter `agui_chat.workspace_hmac_secret`
- Daytona encryption key/salt, Runner token, Proxy key, and health-check key
- PostgreSQL, Redis, Registry, and MinIO credentials
- Dex administrator email and a bcrypt password hash
- `AGENT_SKILLS_DIR` when administrator-managed skills are installed; the
  default empty directory is mounted read-only

Initialize or update the file interactively with:

```bash
bash scripts/configure_daytona_env.sh
```

The script writes atomically with mode `600` and saves an existing file under
the ignored `.env.backups/` directory. On an existing deployment it separates
runtime-key rotation from encryption, Runner, and storage credentials; the
latter must not be changed without migrating the corresponding services or
rebuilding the Daytona data volumes.

Generate independent secrets, for example with `openssl rand -hex 32`. Generate
the Dex hash without placing the clear-text password in a project file:

```bash
htpasswd -BinC 10 admin | cut -d: -f2
```

In Odoo, set the same HMAC secret as a server-only system parameter and set
`AgentOS 内部服务地址` to the address Odoo can reach, for example
`http://127.0.0.1:7777`. This internal address is never returned by
`/agui_chat/config`.

### First Start

Validate interpolation before startup:

```bash
docker compose -f docker-compose.yml -f docker-compose.daytona.yml \
  --profile daytona config
```

Start Daytona without AgentOS first. `DAYTONA_API_KEY` may be empty only during
this bootstrap step:

```bash
docker compose -f docker-compose.yml -f docker-compose.daytona.yml \
  --profile daytona up -d api runner db redis minio registry dex proxy dashboard
```

Open `http://127.0.0.1:13000/dashboard`, sign in with the configured Dex user,
activate the default snapshot, and create an API key with sandbox write and
delete permissions. Store it as `DAYTONA_API_KEY`, then start AgentOS:

```bash
docker compose -f docker-compose.yml -f docker-compose.daytona.yml \
  --profile daytona up -d agent
```

The Dashboard binds to `127.0.0.1:13000` and Proxy to `127.0.0.1:14000` by
default. Local previews use `*.proxy.localhost`. A remote deployment must set
the public Dashboard/OIDC/Proxy variables consistently and place both endpoints
behind TLS with a wildcard DNS record and certificate for the Proxy domain.

### Backup and Recovery

Back up the PostgreSQL database and the `daytona_db_data`, MinIO, Registry,
Runner, Dex, and AgentOS data volumes. PostgreSQL and object/registry data must
come from the same recovery point. Protect the HMAC, encryption, API, Runner,
and Proxy secrets separately; losing or rotating them without a migration can
make existing data or capabilities unusable. Test restores with the same pinned
`v0.189.0` images before relying on a backup.

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
