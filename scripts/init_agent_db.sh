#!/usr/bin/env bash
set -euo pipefail

PGHOST=${PGHOST:-${AGENT_POSTGRES_HOST:-127.0.0.1}}
PGPORT=${PGPORT:-${AGENT_POSTGRES_PORT:-55432}}
PGUSER=${PGUSER:-${AGENT_POSTGRES_USER:-odoo}}
PGDATABASE=${PGDATABASE:-postgres}
PGPASSWORD=${PGPASSWORD:-${AGENT_POSTGRES_PASSWORD:-}}
AGENT_POSTGRES_DB=${AGENT_POSTGRES_DB:-dev}
export PGHOST PGPORT PGUSER PGDATABASE
[[ -n "$PGPASSWORD" ]] && export PGPASSWORD

command -v psql >/dev/null 2>&1 || {
    printf '错误：缺少 psql。\n' >&2
    exit 1
}

exists=$(printf '%s\n' "SELECT 1 FROM pg_database WHERE datname = :'db_name';" | \
    psql -XAt --set=ON_ERROR_STOP=1 --set=db_name="$AGENT_POSTGRES_DB")
if [[ "$exists" == "1" ]]; then
    printf '数据库 %s 已存在，未做修改。\n' "$AGENT_POSTGRES_DB"
    exit 0
fi

printf '%s\n' "SELECT format('CREATE DATABASE %I', :'db_name')" '\gexec' | \
    psql -X --set=ON_ERROR_STOP=1 --set=db_name="$AGENT_POSTGRES_DB"
printf '已创建数据库 %s。\n' "$AGENT_POSTGRES_DB"
