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

New configuration records start with Chat disabled, no runtime addresses, and
cross-origin development disabled. Existing records are not rewritten during
an upgrade. Configure the shared HMAC secret and both runtime addresses before
enabling Chat, then enable in this order:

1. `chat_enabled`
2. `host_tools_enabled`
3. exact entries in `enabled_commands`
4. exact entries in `enabled_business_commands`
5. `write_tools_enabled` when write commands are required

An empty command list enables no commands. A matching tool policy restricts the
exact command, user group, model, field, and visible button allowlist. Missing
policies fail closed for stage/patch/save/discard, protected object/create/
delete/state controls, and every `odoo.business.*` command. Read-only and
navigation page commands without a policy receive no additional model
restriction but remain bound to the current visible snapshot. Kill switches disable the
affected feature without RPC, CRUD, or simulated-state fallback.

The module includes a read-only `odoo.apply_filter` policy that restricts
`hr.employee` filtering to internal users. It only applies on the current bound
List or Kanban view; Odoo access controls, record rules, and the snapshot
`filterFields` allowlist still determine which records and fields can be
filtered. Add model-specific policies where additional user-group or field
restrictions are required.

### Report Administration

The filter report command is installed as command master data but does not
enter `enabled_business_commands` automatically. To enable reporting:

1. Add `odoo.business.report.filters` to the existing enabled business command
   selection.
2. Create one `agui.chat.tool.policy` per allowed model and user-group scope.
3. Set access level to `read`, fill an exact `model_name`, and provide a
   non-empty comma-separated `field_names` allowlist.
4. Keep sensitive, binary, one2many, and many2many fields out of the allowlist;
   saving such a policy is rejected.
5. Include the currency field, normally `currency_id`, whenever a monetary
   field may be aggregated.

The command remains available when `write_tools_enabled` is off. Existing
business commands default to `write` and remain unavailable in that state.
Test each policy with a non-administrator account because Odoo ACL, record
rules, current company, filter visibility, and menu visibility still apply.

## Deployment

Deploy the Python module and versioned React bundle together, then purge old
asset caches. A module/bundle mismatch fails the handshake and keeps Chat
disabled.

AgentOS keeps its built-in `/health` endpoint for liveness. Use `/ready` for
traffic readiness: it returns success only when PostgreSQL is reachable, the
sandbox registry is initialized, and the HMAC secret is at least 32 bytes.
Compose uses `/ready` and restarts the Agent service automatically.

The Agent image installs pandas, openpyxl, matplotlib, Plotly, and Noto CJK
fonts. Rebuild the image whenever `agentos_dev/requirements.txt` changes; do
not install these packages interactively in a running production container.

## Isolated Workspaces

The repository includes the complete AgentOS, PostgreSQL, and Daytona topology
in `docker-compose.yml`, based on the official Daytona OSS Compose baseline at
`v0.189.0`. This is the last upstream version
that includes the supported OSS Compose baseline used by this project. Upstream
has since ended on-premises support, so treat this pinned stack as software the
operator must maintain and security-patch independently.

The default Compose project name remains `agui-daytona`, matching the former
two-file production deployment and preserving its named volumes. A deployment
that previously ran only the base file under another project name must set
`COMPOSE_PROJECT_NAME` to that existing name or migrate `agent_db_data` before
the first unified-stack start.

Both PostgreSQL 18 services mount their named volumes at `/var/lib/postgresql`,
which is the parent data path required by the PostgreSQL 18 image layout. The
former files used the pre-18 `/var/lib/postgresql/data` target. Before replacing
a running deployment created from those files, take logical dumps from both
databases and verify a restore; do not assume that the old named volumes contain
the PostgreSQL 18 cluster.

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
- `agent-db`, the dedicated PostgreSQL backend for Agno sessions and workspace
  sandbox registrations; it is also published on localhost port `55432` for
  the host-side `agentos_dev`, while Daytona's `db` remains private to Daytona

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
- `AGENT_POSTGRES_PASSWORD` for the dedicated AgentOS PostgreSQL service
- `AGENT_POSTGRES_BIND` and `AGENT_POSTGRES_PORT` for the localhost-only
  development connection; defaults are `127.0.0.1:55432`
- `AGUI_SHARED_NETWORK`, the pre-created external Docker network used by all
  AgentOS and Daytona services; it defaults to `hrp_network`

Initialize or update the file interactively with:

```bash
bash scripts/configure_daytona_env.sh
```

Direct host execution requires `openssl` and `htpasswd`. The Compose setup image
below includes both tools.

The same script can run through the one-shot Compose setup profile before
`.env` exists. Pass the host identity so the generated mode-`600` file remains
owned by the operator:

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) \
  docker compose --env-file .env.example --profile setup run --rm env-init
```

The setup container has no runtime network and mounts only the project working
directory. Compose uses `.env.example` solely to resolve the stack before the
script writes the real `.env`; placeholder values are not started as services.
`HOST_UID` and `HOST_GID` make the generated file belong to the invoking host
user. `--rm` removes only the stopped one-shot container; it does not remove
`.env` or any runtime volume.

The script writes atomically with mode `600` and saves an existing file under
the ignored `.env.backups/` directory. On an existing deployment it separates
runtime-key rotation from encryption, Runner, and storage credentials; the
latter must not be changed without migrating the corresponding services or
rebuilding the Daytona data volumes.

For a new `.env`, the script generates the runtime and persistent random
secrets, 12-character Base64URL service passwords, and a 12-character Dex login password.
It writes the Dex bcrypt hash to `.env` and prints the clear-text login password
once; record it immediately. Existing files rotate secrets only after the
corresponding confirmation. Only `OPENAI_API_KEY` must be replaced before
validation; `OPENAI_BASE_URL`, `MODEL`, and the default `DEX_ADMIN_EMAIL` may be
changed when required.

Cryptographic HMAC, encryption, Proxy, health, and Runner values remain
32-byte random secrets and are intentionally longer than service passwords.
`DAYTONA_API_KEY` remains empty only until the first Dashboard bootstrap
described below: Daytona does not allow an unauthenticated client to create the
first API Key. Generate any additional independent secret with, for example,
`openssl rand -hex 32`.

In Odoo, set the same HMAC secret as a server-only system parameter and set
`AgentOS 内部服务地址` to the address Odoo can reach, for example
`http://127.0.0.1:7777`. This internal address is never returned by
`/agui_chat/config`.

Archiving or deleting a Chat session commits a sandbox-cleanup task in the same
database transaction. A cron processes up to 50 tasks every five minutes;
failures retry with exponential backoff capped at 24 hours. HTTP 200, 204, and
404 are successful idempotent outcomes.

Historical sandboxes whose original thread IDs were deleted before this task
model existed cannot be reconstructed automatically. Audit Daytona sandboxes
by the `agui-thread` label and compare them with the AgentOS registry and Odoo
cleanup tasks. Preserve an export before manually deleting an unmatched
sandbox, and record the sandbox ID, label hash, review time, and operator.

### First Start

Create the shared external network before validating or starting the stack:

```bash
docker network create hrp_network
```

Compose reads `.env`, but the current shell does not automatically export it.
If `AGUI_SHARED_NETWORK` was changed in `.env`, replace `hrp_network` above with
that exact value.

The Compose file intentionally attaches AgentOS, both PostgreSQL services, and
all Daytona infrastructure services to this one network. Any other container
attached to it can attempt direct connections to those internal services. Use a
dedicated deployment-specific network name, do not attach untrusted workloads,
keep internal service ports unpublished, and enforce host/network policy around
the Docker daemon. Deployments requiring stronger tenant isolation should use
separate stacks and separate shared networks.

Validate interpolation before startup:

```bash
docker compose --profile daytona config
```

If the network was not created, `docker compose up` fails with an external
network-not-found error by design. Create the configured network and retry; do
not change the Compose file to an implicitly created network.

Start Daytona without AgentOS first. `DAYTONA_API_KEY` may be empty only during
this bootstrap step:

```bash
docker compose --profile daytona up -d \
  api runner db redis minio registry dex proxy dashboard
```

Open `http://127.0.0.1:13000/dashboard`, sign in with the configured Dex user,
activate the default snapshot, and create an API key with sandbox write and
delete permissions. Store it as `DAYTONA_API_KEY`, then start AgentOS:

```bash
docker compose --profile daytona up -d agent
```

The Dashboard binds to `127.0.0.1:13000` and Proxy to `127.0.0.1:14000` by
default. Local previews use `*.proxy.localhost`. A remote deployment must set
the public Dashboard/OIDC/Proxy variables consistently and place both endpoints
behind TLS with a wildcard DNS record and certificate for the Proxy domain.

### Backup and Recovery

Back up `agent_db_data`, the Daytona `daytona_db_data` volume, MinIO, Registry,
Runner, and Dex data. The dedicated AgentOS PostgreSQL database contains both
Agno sessions and workspace registrations. PostgreSQL and object/registry data must
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
