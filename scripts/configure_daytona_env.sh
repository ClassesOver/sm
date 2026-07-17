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
command -v awk >/dev/null 2>&1 || die "缺少 awk。"
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

random_secret() {
    openssl rand -hex 32
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

bcrypt_hash() {
    local password=$1
    local value
    if command -v htpasswd >/dev/null 2>&1; then
        value=$(printf '%s\n' "$password" | htpasswd -niBC 10 admin)
        printf '%s' "${value#admin:}"
        return
    fi
    command -v python3 >/dev/null 2>&1 || die "生成 Dex bcrypt 需要 htpasswd 或支持 crypt 的 python3。"
    value=$(printf '%s' "$password" | python3 -W ignore::DeprecationWarning -c '
import secrets
import sys
try:
    import crypt
except ImportError as error:
    raise SystemExit("python crypt unavailable") from error
alphabet = "./ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
salt = "$2b$10$" + "".join(secrets.choice(alphabet) for _ in range(22))
result = crypt.crypt(sys.stdin.read(), salt)
if not result or not result.startswith("$2"):
    raise SystemExit("system crypt does not support bcrypt")
print(result, end="")
') || die "系统无法生成 Dex bcrypt；请安装 apache2-utils/htpasswd。"
    printf '%s' "$value"
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
configure_dex=$is_new

if [[ "$is_new" == false ]]; then
    if ask_yes_no '重新生成工作区 HMAC、Proxy 和健康检查密钥？' n; then
        rotate_runtime=true
    fi
    printf '%s\n' '警告：下组值包含 Daytona 加密密钥、Runner Token 和持久化服务口令。'
    printf '%s\n' '已运行的部署不能只修改 .env；还必须迁移数据库/服务凭据，或重建 Daytona 数据卷。'
    if ask_yes_no '确认这是首次部署或已安排完整凭据迁移，并重新生成这些值？' n; then
        rotate_persistent=true
    fi
    if ask_yes_no '更新 Dex 管理员登录？' n; then
        configure_dex=true
    fi
fi

if [[ "$rotate_runtime" == true ]]; then
    set_env AGUI_WORKSPACE_HMAC_SECRET "$(random_secret)"
    set_env DAYTONA_PROXY_API_KEY "$(random_secret)"
    set_env DAYTONA_HEALTH_API_KEY "$(random_secret)"
    printf '%s\n' '已更新工作区和无状态服务密钥。'
fi

if [[ "$rotate_persistent" == true ]]; then
    set_env DAYTONA_ENCRYPTION_KEY "$(random_secret)"
    set_env DAYTONA_ENCRYPTION_SALT "$(random_secret)"
    set_env DAYTONA_RUNNER_TOKEN "$(random_secret)"
    set_env DAYTONA_POSTGRES_PASSWORD "$(random_secret)"
    set_env DAYTONA_REDIS_PASSWORD "$(random_secret)"
    set_env DAYTONA_REGISTRY_PASSWORD "$(random_secret)"
    set_env DAYTONA_MINIO_PASSWORD "$(random_secret)"
    printf '%s\n' '已更新 Daytona 持久化服务密钥和口令。'
fi

if [[ "$configure_dex" == true ]]; then
    read -r -p 'Dex 管理员邮箱 [admin@example.com]: ' dex_email
    dex_email=${dex_email:-admin@example.com}
    [[ "$dex_email" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] || die "Dex 管理员邮箱格式无效。"
    while true; do
        read -r -s -p 'Dex 管理员密码（至少 12 个字符）: ' dex_password
        printf '\n'
        [[ ${#dex_password} -ge 12 ]] || { printf '%s\n' '密码太短。' >&2; continue; }
        read -r -s -p '再次输入 Dex 管理员密码: ' dex_password_confirm
        printf '\n'
        [[ "$dex_password" == "$dex_password_confirm" ]] && break
        printf '%s\n' '两次密码不一致。' >&2
    done
    dex_hash=$(bcrypt_hash "$dex_password")
    unset dex_password dex_password_confirm
    set_env DEX_ADMIN_EMAIL "$dex_email"
    set_env DEX_STATIC_PASSWORD_HASH "'$dex_hash'"
    printf '%s\n' '已更新 Dex 管理员登录。'
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
