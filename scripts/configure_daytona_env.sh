#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TEMPLATE_FILE="$ROOT_DIR/docker/.env.example"
ENV_FILE=${1:-"$ROOT_DIR/docker/.env"}
ENV_DIR=$(dirname "$ENV_FILE")
BACKUP_DIR="$ENV_DIR/.env.backups"

die() {
    printf '错误：%s\n' "$*" >&2
    exit 1
}

for command in openssl ssh-keygen htpasswd awk; do
    command -v "$command" >/dev/null 2>&1 || die "缺少 $command。"
done
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
    ' "$ENV_FILE" > "$temporary"
    chmod 600 "$temporary"
    mv "$temporary" "$ENV_FILE"
}

env_value() {
    awk -F= -v key="$1" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE"
}

needs_value() {
    local value
    value=$(env_value "$1")
    [[ -z "$value" || "$value" == 'generated-by-env-init' || "$value" == "'generated-by-env-init'" ]]
}

set_random_env() {
    local key=$1
    local bytes=$2
    set_env "$key" "$(openssl rand -base64 "$bytes" | tr '/+' '_-' | tr -d '=')"
}

set_random_password_env() {
    set_random_env "$1" 9
}

bcrypt_password() {
    printf '%s\n' "$1" | htpasswd -niBC 10 admin | awk -F: 'NR == 1 { print $2 }'
}

generate_ssh_material() {
    local temporary private_key public_key host_key
    temporary=$(mktemp -d "$ENV_DIR/.ssh-keys.XXXXXX")
    ssh-keygen -q -t ed25519 -N '' -C daytona-gateway -f "$temporary/gateway"
    ssh-keygen -q -t ed25519 -N '' -C daytona-host -f "$temporary/host"
    private_key=$(base64 < "$temporary/gateway" | tr -d '\n')
    public_key=$(base64 < "$temporary/gateway.pub" | tr -d '\n')
    host_key=$(base64 < "$temporary/host" | tr -d '\n')
    set_env DAYTONA_SSH_PRIVATE_KEY "$private_key"
    set_env DAYTONA_SSH_PUBLIC_KEY "$public_key"
    set_env DAYTONA_SSH_HOST_KEY "$host_key"
    rm -rf "$temporary"
    unset private_key public_key host_key
}

is_new=false
if [[ ! -f "$ENV_FILE" ]]; then
    mkdir -p "$ENV_DIR"
    cp "$TEMPLATE_FILE" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    is_new=true
    printf '已从 %s 创建 %s。\n' "$TEMPLATE_FILE" "$ENV_FILE"
else
    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"
    backup="$BACKUP_DIR/$(basename "$ENV_FILE").$(date +%Y%m%d%H%M%S)"
    cp "$ENV_FILE" "$backup"
    chmod 600 "$backup"
    printf '已备份现有配置到 %s。\n' "$backup"
fi

rotate_runtime=$is_new
rotate_persistent=$is_new

if [[ "$is_new" == false ]]; then
    if ask_yes_no '重新生成 Proxy、健康检查、SSH Gateway 和 OTel 服务密钥？' n; then
        rotate_runtime=true
    fi
    printf '%s\n' '警告：下组值包含 Daytona 加密密钥、Runner Token、SSH 密钥、Dex 登录密码和持久化服务口令。'
    printf '%s\n' '已运行的部署不能只修改环境文件；还必须迁移对应凭据，或重建 Daytona 数据卷。'
    if ask_yes_no '确认这是首次部署或已安排完整凭据迁移，并重新生成这些值？' n; then
        rotate_persistent=true
    fi
fi

if [[ "$rotate_runtime" == true ]]; then
    set_random_env DAYTONA_PROXY_API_KEY 32
    set_random_env DAYTONA_HEALTH_API_KEY 32
    set_random_env DAYTONA_SSH_GATEWAY_API_KEY 32
    set_random_env DAYTONA_OTEL_COLLECTOR_API_KEY 32
    printf '%s\n' '已更新 Daytona 无状态服务密钥。'
else
    for key in DAYTONA_PROXY_API_KEY DAYTONA_HEALTH_API_KEY DAYTONA_SSH_GATEWAY_API_KEY DAYTONA_OTEL_COLLECTOR_API_KEY; do
        needs_value "$key" && set_random_env "$key" 32
    done
fi

if [[ "$rotate_persistent" == true ]]; then
    set_random_env DAYTONA_ENCRYPTION_KEY 32
    set_random_env DAYTONA_ENCRYPTION_SALT 32
    set_random_env DAYTONA_RUNNER_TOKEN 32
    set_random_password_env DAYTONA_POSTGRES_PASSWORD
    set_random_password_env DAYTONA_REDIS_PASSWORD
    set_random_password_env DAYTONA_REGISTRY_PASSWORD
    set_random_password_env DAYTONA_MINIO_PASSWORD
    set_random_password_env DAYTONA_PGADMIN_PASSWORD
    generate_ssh_material
    dex_admin_password=$(openssl rand -base64 9 | tr '/+' '_-')
    set_env DEX_STATIC_PASSWORD_HASH "'$(bcrypt_password "$dex_admin_password")'"
    printf '%s\n' '已更新 Daytona 持久化服务密钥、SSH 密钥、口令和 Dex 登录密码。'
    printf 'Dex 登录密码（默认账号 admin@example.com）：%s\n' "$dex_admin_password"
    unset dex_admin_password
else
    needs_value DAYTONA_PGADMIN_PASSWORD && set_random_password_env DAYTONA_PGADMIN_PASSWORD
    if needs_value DAYTONA_SSH_PRIVATE_KEY || needs_value DAYTONA_SSH_PUBLIC_KEY || needs_value DAYTONA_SSH_HOST_KEY; then
        generate_ssh_material
        printf '%s\n' '已补充 Daytona SSH Gateway 密钥。'
    fi
fi

chmod 600 "$ENV_FILE"
printf '完成：%s（权限 600）。重启 Daytona 后新值才会生效。\n' "$ENV_FILE"
