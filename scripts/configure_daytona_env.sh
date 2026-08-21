#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TEMPLATE_FILE="$ROOT_DIR/docker/.env.example"
ENV_FILE=${1:-"$ROOT_DIR/docker/.env"}
ENV_DIR=$(dirname "$ENV_FILE")
BACKUP_DIR="$ENV_DIR/.env.backups"
WORK_FILE=
DAYTONA_DATA_ROOT="$ROOT_DIR/docker/data"

die() {
    printf '错误：%s\n' "$*" >&2
    exit 1
}

restore_host_ownership() {
    [[ $(id -u) -eq 0 && -n ${HOST_UID:-} && -n ${HOST_GID:-} ]] || return 0
    if [[ -e "$ENV_FILE" ]]; then
        chown "$HOST_UID:$HOST_GID" "$ENV_FILE" || printf '警告：无法恢复 %s 的宿主所有权。\n' "$ENV_FILE" >&2
    fi
    if [[ -d "$BACKUP_DIR" ]]; then
        chown -R "$HOST_UID:$HOST_GID" "$BACKUP_DIR" || printf '警告：无法恢复 %s 的宿主所有权。\n' "$BACKUP_DIR" >&2
    fi
}

cleanup() {
    [[ -z "$WORK_FILE" || ! -e "$WORK_FILE" ]] || rm -f "$WORK_FILE"
    restore_host_ownership
}

prepare_persistent_data() {
    [[ $(id -u) -eq 0 ]] || die "持久化目录初始化必须以 root 运行。"
    mkdir -p "$DAYTONA_DATA_ROOT"/{db,redis,registry,minio,runner,dex}
    # Dex 2.42.0 镜像固定以 1001:1001 运行；bind mount 首次由 Compose 创建时通常属于 root，
    # 必须在容器启动前修复目录身份，否则入口的 dex.db touch 会直接失败。
    chown -R 1001:1001 "$DAYTONA_DATA_ROOT/dex"
}

trap cleanup EXIT

for command in openssl htpasswd awk; do
    command -v "$command" >/dev/null 2>&1 || die "缺少 $command。"
done
[[ -f "$TEMPLATE_FILE" ]] || die "未找到 $TEMPLATE_FILE。"
prepare_persistent_data
if [[ -n ${HOST_UID:-} || -n ${HOST_GID:-} ]]; then
    [[ ${HOST_UID:-} =~ ^[0-9]+$ && ${HOST_GID:-} =~ ^[0-9]+$ ]] || die "HOST_UID 和 HOST_GID 必须同时为数字。"
fi

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

rotate_runtime=$is_new
rotate_persistent=$is_new

if [[ "$is_new" == false ]]; then
    if ask_yes_no '重新生成 Proxy、健康检查和 SSH Gateway API Key？' n; then
        rotate_runtime=true
    fi
    printf '%s\n' '警告：下组值包含 Daytona 加密密钥、Runner Token、Dex 登录密码和持久化服务口令。'
    printf '%s\n' '已运行的部署不能只修改环境文件；还必须迁移对应凭据，或重建 Daytona 数据卷。'
    if ask_yes_no '确认这是首次部署或已安排完整凭据迁移，并重新生成这些值？' n; then
        rotate_persistent=true
    fi
fi

if [[ "$rotate_runtime" == true ]]; then
    set_random_env DAYTONA_PROXY_API_KEY 32
    set_random_env DAYTONA_HEALTH_API_KEY 32
    set_random_env DAYTONA_SSH_GATEWAY_API_KEY 32
    printf '%s\n' '已更新 Daytona 无状态服务密钥。'
else
    for key in DAYTONA_PROXY_API_KEY DAYTONA_HEALTH_API_KEY DAYTONA_SSH_GATEWAY_API_KEY; do
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
    dex_admin_password=$(openssl rand -base64 9 | tr '/+' '_-')
    dex_password_hash=$(bcrypt_password "$dex_admin_password")
    [[ ${#dex_password_hash} -eq 60 && "$dex_password_hash" == '$2'* ]] || die "生成的 Dex bcrypt 哈希无效。"
    set_env DEX_STATIC_PASSWORD_HASH "'$dex_password_hash'"
    printf '%s\n' '已更新 Daytona 持久化服务密钥、口令和 Dex 登录密码。'
    unset dex_password_hash
else
    for key in DAYTONA_ENCRYPTION_KEY DAYTONA_ENCRYPTION_SALT DAYTONA_RUNNER_TOKEN DAYTONA_POSTGRES_PASSWORD DAYTONA_REDIS_PASSWORD DAYTONA_REGISTRY_PASSWORD DAYTONA_MINIO_PASSWORD DEX_STATIC_PASSWORD_HASH; do
        needs_value "$key" && die "配置 $key 尚未初始化，请重新运行并确认生成持久化凭据。"
    done
fi

chmod 600 "$WORK_FILE"
mv "$WORK_FILE" "$ENV_FILE"
WORK_FILE=
restore_host_ownership
if [[ -n ${dex_admin_password:-} ]]; then
    printf 'Dex 登录密码（默认账号 admin@example.com）：%s\n' "$dex_admin_password"
    unset dex_admin_password
fi
printf '完成：%s（权限 600）。重启 Daytona 后新值才会生效。\n' "$ENV_FILE"
