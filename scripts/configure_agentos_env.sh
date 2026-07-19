#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TEMPLATE_FILE="$ROOT_DIR/.env.example"
ENV_FILE=${1:-"$ROOT_DIR/.env"}
ENV_DIR=$(dirname "$ENV_FILE")
BACKUP_DIR="$ENV_DIR/.env.backups"
DEFAULT_SKILLS_DIR="$ROOT_DIR/deploy/agentos/skills"
WORK_FILE=

die() {
    printf '错误：%s\n' "$*" >&2
    exit 1
}

cleanup() {
    [[ -z "$WORK_FILE" || ! -e "$WORK_FILE" ]] || rm -f "$WORK_FILE"
}

trap cleanup EXIT

command -v openssl >/dev/null 2>&1 || die "缺少 openssl。"
command -v awk >/dev/null 2>&1 || die "缺少 awk。"
command -v stat >/dev/null 2>&1 || die "缺少 stat。"
[[ -f "$TEMPLATE_FILE" ]] || die "未找到 $TEMPLATE_FILE。"

ask_yes_no() {
    local prompt=$1
    local default=${2:-n}
    local answer
    read -r -p "$prompt [y/N] " answer
    answer=${answer:-$default}
    [[ "$answer" =~ ^[Yy]$ ]]
}

set_env() {
    local key=$1
    local value=$2
    local temporary
    temporary=$(mktemp "$ENV_DIR/.env.update.XXXXXX")
    ENV_UPDATE_VALUE=$value awk -v key="$key" '
        BEGIN { found = 0 }
        index($0, key "=") == 1 {
            print key "=" ENVIRON["ENV_UPDATE_VALUE"]
            found = 1
            next
        }
        { print }
        END { if (!found) print key "=" ENVIRON["ENV_UPDATE_VALUE"] }
    ' "$WORK_FILE" > "$temporary"
    chmod 600 "$temporary"
    mv "$temporary" "$WORK_FILE"
}

env_value() {
    awk -F= -v key="$1" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$WORK_FILE"
}

set_random_env() {
    local key=$1
    local bytes=$2
    set_env "$key" "$(openssl rand -base64 "$bytes" | tr '/+' '_-' | tr -d '=')"
}

is_new=false
mkdir -p "$ENV_DIR"
WORK_FILE=$(mktemp "$ENV_DIR/.env.pending.XXXXXX")
if [[ ! -f "$ENV_FILE" ]]; then
    cp "$TEMPLATE_FILE" "$WORK_FILE"
    is_new=true
    printf '将从 %s 创建 %s。\n' "$TEMPLATE_FILE" "$ENV_FILE"
else
    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"
    backup="$BACKUP_DIR/$(basename "$ENV_FILE").$(date +%Y%m%d%H%M%S)"
    cp "$ENV_FILE" "$backup"
    cp "$ENV_FILE" "$WORK_FILE"
    chmod 600 "$backup"
    printf '已备份现有配置到 %s。\n' "$backup"
fi
chmod 600 "$WORK_FILE"

[[ ! -L "$DEFAULT_SKILLS_DIR" ]] || die "默认技能目录不能是符号链接：$DEFAULT_SKILLS_DIR"
mkdir -p "$DEFAULT_SKILLS_DIR"
chmod -R go-w "$DEFAULT_SKILLS_DIR"
skills_uid=$(stat -c %u "$DEFAULT_SKILLS_DIR")
set_env AGENT_SKILLS_TRUSTED_UID "$skills_uid"
printf '已校验默认技能目录权限，可信所有者 UID：%s。\n' "$skills_uid"
unset skills_uid

if [[ "$is_new" == true ]]; then
    set_random_env AGENT_POSTGRES_PASSWORD 9
    set_random_env AGUI_WORKSPACE_HMAC_SECRET 32
else
    if ask_yes_no '重新生成 AgentOS 工作区 HMAC 密钥？' n; then
        set_random_env AGUI_WORKSPACE_HMAC_SECRET 32
    fi
    password=$(env_value AGENT_POSTGRES_PASSWORD)
    [[ -n "$password" && "$password" != 'generated-by-env-init' ]] || set_random_env AGENT_POSTGRES_PASSWORD 9
    unset password
fi

if ask_yes_no '现在写入已创建的 Daytona API Key？' n; then
    read -r -s -p 'Daytona API Key: ' daytona_api_key
    printf '\n'
    [[ -n "$daytona_api_key" ]] || die "Daytona API Key 不能为空。"
    set_env DAYTONA_API_KEY "$daytona_api_key"
    unset daytona_api_key
fi

chmod 600 "$WORK_FILE"
mv "$WORK_FILE" "$ENV_FILE"
WORK_FILE=
printf '完成：%s（权限 600）。重启 AgentOS 后新值才会生效。\n' "$ENV_FILE"
