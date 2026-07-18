#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TEMPLATE_FILE="$ROOT_DIR/.env.example"
ENV_FILE=${1:-"$ROOT_DIR/.env"}
ENV_DIR=$(dirname "$ENV_FILE")
BACKUP_DIR="$ENV_DIR/.env.backups"

die() {
    printf '错误：%s\n' "$*" >&2
    exit 1
}

command -v openssl >/dev/null 2>&1 || die "缺少 openssl。"
command -v htpasswd >/dev/null 2>&1 || die "缺少 htpasswd。"
command -v awk >/dev/null 2>&1 || die "缺少 awk。"
command -v stat >/dev/null 2>&1 || die "缺少 stat。"
[[ -f "$TEMPLATE_FILE" ]] || die "未找到 $TEMPLATE_FILE。"

ask_yes_no() {
    local prompt=$1
    local default=${2:-n}
    local suffix='[y/N]'
    local answer
    [[ "$default" == 'y' ]] && suffix='[Y/n]'
    read -r -p "$prompt $suffix " answer
    answer=${answer:-$default}
    [[ "$answer" =~ ^[Yy]$ ]]
}

bcrypt_password() {
    printf '%s\n' "$1" | htpasswd -niBC 10 admin | awk -F: 'NR == 1 { print $2 }'
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
        END {
            if (!found) print key "=" ENVIRON["ENV_UPDATE_VALUE"]
        }
    ' "$ENV_FILE" > "$temporary"
    chmod 600 "$temporary"
    mv "$temporary" "$ENV_FILE"
}

set_random_env() {
    local key=$1
    local bytes=$2
    local value
    value=$(openssl rand -hex "$bytes")
    set_env "$key" "$value"
}

set_random_password_env() {
    local key=$1
    local value
    value=$(openssl rand -base64 9 | tr '/+' '_-')
    set_env "$key" "$value"
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
dex_admin_password=''

if [[ "$is_new" == false ]]; then
    if ask_yes_no '重新生成工作区 HMAC、Proxy 和健康检查密钥？' n; then
        rotate_runtime=true
    fi
    printf '%s\n' '警告：下组值包含 Daytona 加密密钥、Runner Token、Dex 登录密码和持久化服务口令。'
    printf '%s\n' '已运行的部署不能只修改 .env；还必须迁移数据库/服务凭据，或重建 Daytona 数据卷。'
    if ask_yes_no '确认这是首次部署或已安排完整凭据迁移，并重新生成这些值？' n; then
        rotate_persistent=true
    fi
fi

if [[ "$rotate_runtime" == true ]]; then
    set_random_env AGUI_WORKSPACE_HMAC_SECRET 32
    set_random_env DAYTONA_PROXY_API_KEY 32
    set_random_env DAYTONA_HEALTH_API_KEY 32
    printf '%s\n' '已更新工作区和无状态服务密钥。'
fi

if [[ "$rotate_persistent" == true ]]; then
    set_random_password_env AGENT_POSTGRES_PASSWORD
    set_random_env DAYTONA_ENCRYPTION_KEY 32
    set_random_env DAYTONA_ENCRYPTION_SALT 32
    set_random_env DAYTONA_RUNNER_TOKEN 32
    set_random_password_env DAYTONA_POSTGRES_PASSWORD
    set_random_password_env DAYTONA_REDIS_PASSWORD
    set_random_password_env DAYTONA_REGISTRY_PASSWORD
    set_random_password_env DAYTONA_MINIO_PASSWORD
    dex_admin_password=$(openssl rand -base64 9 | tr '/+' '_-')
    dex_password_hash=$(bcrypt_password "$dex_admin_password")
    set_env DEX_STATIC_PASSWORD_HASH "'$dex_password_hash'"
    unset dex_password_hash
    printf '%s\n' '已更新 Daytona 持久化服务密钥、口令和 Dex 登录密码。'
    printf 'Dex 登录密码（账号见 DEX_ADMIN_EMAIL）：%s\n' "$dex_admin_password"
fi

skills_dir=$(awk -F= '$1 == "AGENT_SKILLS_DIR" {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE")
skills_dir=${skills_dir:-./deploy/daytona/skills}
[[ "$skills_dir" = /* ]] || skills_dir="$ROOT_DIR/$skills_dir"
if [[ -d "$skills_dir" ]]; then
    chmod -R go-w "$skills_dir"
    set_env AGENT_SKILLS_TRUSTED_UID "$(stat -c %u "$skills_dir")"
    printf '已记录技能目录宿主 UID。\n'
fi

if ask_yes_no '现在写入已创建的 Daytona API Key？' n; then
    read -r -s -p 'Daytona API Key: ' daytona_api_key
    printf '\n'
    [[ -n "$daytona_api_key" ]] || die "Daytona API Key 不能为空。"
    set_env DAYTONA_API_KEY "$daytona_api_key"
    unset daytona_api_key
    printf '%s\n' '已更新 Daytona API Key。'
fi

chmod 600 "$ENV_FILE"
printf '完成：%s（权限 600）。重启相关服务后新值才会生效。\n' "$ENV_FILE"
