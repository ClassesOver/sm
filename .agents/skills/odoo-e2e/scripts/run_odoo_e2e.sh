#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: run_odoo_e2e.sh [playwright arguments...]

Creates a new isolated Odoo database, starts a temporary Odoo 12 server, and
runs the project's Playwright Odoo tests. All test process groups are stopped
before this script exits.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

fail() {
  printf 'odoo-e2e: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

require_file() {
  [[ -f "$1" ]] || fail "required file not found: $1"
}

validate_db_name() {
  [[ "$1" =~ ^[A-Za-z0-9_]+$ ]] || fail "unsafe database name: $1"
  ((${#1} <= 63)) || fail "database name exceeds PostgreSQL's 63-byte limit: $1"
}

PROJECT_ROOT="${ODOO_E2E_PROJECT_ROOT:-$PWD}"
VENV="${ODOO_E2E_VENV:-/home/junge/.local/venvs/odoo12-e2e}"
ODOO_ROOT="${ODOO_E2E_ODOO_ROOT:-/home/junge/pros/odoo12}"
SOURCE_DB="${ODOO_E2E_SOURCE_DB:-odoo12_agui_e2e}"
PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-55432}"
PGUSER="${PGUSER:-odoo}"
PGDATABASE="${PGDATABASE:-postgres}"
SOURCE_DATA_DIR="${ODOO_E2E_SOURCE_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/Odoo}"
DRY_RUN="${ODOO_E2E_DRY_RUN:-0}"

if [[ -n "${ODOO_E2E_DB:-}" ]]; then
  TARGET_DB="$ODOO_E2E_DB"
else
  source_prefix="${SOURCE_DB:0:36}"
  TARGET_DB="${source_prefix}_$(date -u +%Y%m%d_%H%M%S)_$$"
fi

validate_db_name "$SOURCE_DB"
validate_db_name "$TARGET_DB"

PYTHON="$VENV/bin/python"
ODOO_BIN="$ODOO_ROOT/odoo-bin"
WIDGET_DIR="$PROJECT_ROOT/agui_chat/react_widget"
ADDONS_PATH="$ODOO_ROOT/addons,$PROJECT_ROOT"

require_file "$PYTHON"
require_file "$ODOO_BIN"
require_file "$WIDGET_DIR/package.json"
require_command psql
require_command pg_dump
require_command pg_restore
require_command createdb
require_command dropdb
require_command cp
require_command curl
require_command pnpm
require_command setsid

port_available() {
  "$PYTHON" - "$1" <<'PY'
import socket
import sys

sock = socket.socket()
try:
    sock.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
}

find_free_port() {
  "$PYTHON" - <<'PY'
import socket

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PY
}

if [[ -n "${ODOO_E2E_HTTP_PORT:-}" ]]; then
  HTTP_PORT="$ODOO_E2E_HTTP_PORT"
  [[ "$HTTP_PORT" =~ ^[0-9]+$ ]] || fail "ODOO_E2E_HTTP_PORT must be numeric"
  port_available "$HTTP_PORT" || fail "ODOO_E2E_HTTP_PORT is already in use: $HTTP_PORT"
else
  HTTP_PORT=18069
  if ! port_available "$HTTP_PORT"; then
    HTTP_PORT="$(find_free_port)"
  fi
fi
BASE_URL="http://127.0.0.1:$HTTP_PORT"

PSQL=(
  psql --host "$PGHOST" --port "$PGPORT" --username "$PGUSER"
  --dbname "$PGDATABASE" --no-psqlrc --tuples-only --no-align --quiet
  --set ON_ERROR_STOP=1
)

db_exists() {
  local result
  if ! result="$("${PSQL[@]}" --command \
    "SELECT 1 FROM pg_database WHERE datname = '$1'")"; then
    fail "cannot query PostgreSQL at $PGHOST:$PGPORT/$PGDATABASE as $PGUSER"
  fi
  [[ "$result" == "1" ]]
}

if db_exists "$TARGET_DB"; then
  fail "target database already exists; choose a new ODOO_E2E_DB: $TARGET_DB"
fi

SOURCE_EXISTS=0
if db_exists "$SOURCE_DB"; then
  SOURCE_EXISTS=1
fi

if [[ "$DRY_RUN" == "1" ]]; then
  printf 'ODOO_E2E_DRY_RUN=1\n'
  printf 'ODOO_E2E_DB=%s\n' "$TARGET_DB"
  printf 'ODOO_E2E_SOURCE_DB=%s\n' "$SOURCE_DB"
  printf 'ODOO_E2E_SOURCE_EXISTS=%s\n' "$SOURCE_EXISTS"
  printf 'ODOO_E2E_SOURCE_FILESTORE=%s\n' "$SOURCE_DATA_DIR/filestore/$SOURCE_DB"
  printf 'ODOO_E2E_URL=%s\n' "$BASE_URL"
  exit 0
fi

WORK_DIR="${ODOO_E2E_WORK_DIR:-${TMPDIR:-/tmp}/odoo-e2e-$TARGET_DB}"
DATA_DIR="$WORK_DIR/data"
PREP_LOG="$WORK_DIR/prepare.log"
SERVER_LOG="$WORK_DIR/odoo.log"
SOURCE_FILESTORE="$SOURCE_DATA_DIR/filestore/$SOURCE_DB"
TARGET_FILESTORE="$DATA_DIR/filestore/$TARGET_DB"
mkdir -p "$DATA_DIR"

CREATED_DB=0
drop_partial_database() {
  if [[ "$CREATED_DB" == "1" ]] && db_exists "$TARGET_DB"; then
    dropdb --host "$PGHOST" --port "$PGPORT" --username "$PGUSER" \
      --maintenance-db "$PGDATABASE" --if-exists "$TARGET_DB" >/dev/null
  fi
}

odoo_common=(
  "$PYTHON" "$ODOO_BIN"
  "--addons-path=$ADDONS_PATH"
  "--data-dir=$DATA_DIR"
  "--db_host=$PGHOST"
  "--db_port=$PGPORT"
  "--db_user=$PGUSER"
  "--max-cron-threads=0"
)

if [[ "$SOURCE_EXISTS" == "1" ]]; then
  dump_file="$(mktemp "$WORK_DIR/source.dump.XXXXXX")"
  if ! pg_dump --host "$PGHOST" --port "$PGPORT" --username "$PGUSER" \
    --format=custom --no-owner --no-privileges --file "$dump_file" "$SOURCE_DB"; then
    rm -f "$dump_file"
    fail "failed to dump source database: $SOURCE_DB"
  fi
  if ! createdb --host "$PGHOST" --port "$PGPORT" --username "$PGUSER" \
    --maintenance-db "$PGDATABASE" "$TARGET_DB"; then
    rm -f "$dump_file"
    fail "failed to create target database: $TARGET_DB"
  fi
  CREATED_DB=1
  if ! pg_restore --host "$PGHOST" --port "$PGPORT" --username "$PGUSER" \
    --dbname "$TARGET_DB" --exit-on-error --no-owner --no-privileges "$dump_file"; then
    rm -f "$dump_file"
    drop_partial_database
    fail "failed to restore target database: $TARGET_DB"
  fi
  rm -f "$dump_file"
  if [[ ! -d "$SOURCE_FILESTORE" ]]; then
    drop_partial_database
    fail "source filestore not found: $SOURCE_FILESTORE"
  fi
  mkdir -p "$DATA_DIR/filestore"
  if ! cp -a "$SOURCE_FILESTORE" "$TARGET_FILESTORE"; then
    drop_partial_database
    fail "failed to copy source filestore: $SOURCE_FILESTORE"
  fi
  if ! "${odoo_common[@]}" --database "$TARGET_DB" \
    --update agui_chat,agui_chat_test --stop-after-init --no-http \
    --logfile "$PREP_LOG"; then
    drop_partial_database
    fail "module update failed; see $PREP_LOG"
  fi
else
  if ! "${odoo_common[@]}" --database "$TARGET_DB" \
    --init agui_chat_test --without-demo all --stop-after-init --no-http \
    --logfile "$PREP_LOG"; then
    CREATED_DB=1
    drop_partial_database
    fail "database initialization failed; see $PREP_LOG"
  fi
  CREATED_DB=1
fi

SERVER_PID=""
TEST_PID=""

terminate_group() {
  local pid="$1"
  [[ -n "$pid" ]] || return 0

  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 50); do
    if ! kill -0 -- "-$pid" 2>/dev/null && ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid" 2>/dev/null || true
      return 0
    fi
    sleep 0.1
  done
  kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  terminate_group "$TEST_PID"
  terminate_group "$SERVER_PID"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

server_ready() {
  curl --fail --silent --show-error --max-time 2 \
    "$BASE_URL/web/login?db=$TARGET_DB" >/dev/null 2>&1
}

setsid "${odoo_common[@]}" --database "$TARGET_DB" "--db-filter=^${TARGET_DB}$" \
  --http-interface 127.0.0.1 --http-port "$HTTP_PORT" --workers 0 \
  --logfile "$SERVER_LOG" &
SERVER_PID=$!

for _ in $(seq 1 90); do
  if server_ready; then
    break
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    fail "Odoo server exited during startup; see $SERVER_LOG"
  fi
  sleep 1
done
server_ready || fail "Odoo server did not become ready; see $SERVER_LOG"

export ODOO_E2E_DB="$TARGET_DB"
export ODOO_E2E_URL="$BASE_URL"
export ODOO_E2E_LOGIN="${ODOO_E2E_LOGIN:-admin}"
export ODOO_E2E_PASSWORD="${ODOO_E2E_PASSWORD:-admin}"

printf 'ODOO_E2E_DB=%s\n' "$TARGET_DB"
printf 'ODOO_E2E_URL=%s\n' "$BASE_URL"
printf 'ODOO_E2E_SERVER_PID=%s\n' "$SERVER_PID"
printf 'ODOO_E2E_WORK_DIR=%s\n' "$WORK_DIR"

cd "$WIDGET_DIR"
if (($#)); then
  setsid pnpm run test:e2e:odoo "$@" &
else
  setsid pnpm run test:e2e:odoo &
fi
TEST_PID=$!

set +e
wait "$TEST_PID"
TEST_STATUS=$?
set -e

# The runner may exit before browser helpers. Always terminate its whole group.
terminate_group "$TEST_PID"
TEST_PID=""
exit "$TEST_STATUS"
