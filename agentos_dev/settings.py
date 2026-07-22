import os
from collections.abc import MutableMapping
from dataclasses import dataclass
from urllib.parse import quote

from dotenv import dotenv_values

DEFAULT_ENV_FILE = "/home/junge/pros/agents_app/.env"
DEFAULT_MODEL_ID = "qwen3.6-35b-a3b"
DEFAULT_OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_AGENT_DB_URL = "postgresql+psycopg://odoo@127.0.0.1:55432/dev"
DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:18069",
    "http://localhost:18069",
)


def _flag(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _positive_int(
    values: MutableMapping[str, str],
    name: str,
    default: int,
    *,
    maximum: int | None = None,
) -> int:
    raw = values.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} 必须是整数") from error
    if value < 1:
        raise ValueError(f"{name} 必须大于 0")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} 必须小于或等于 {maximum}")
    return value


def _database_url(values: MutableMapping[str, str]) -> str:
    configured = values.get("AGENT_DB_URL") or values.get("DATABASE_URL")
    if configured:
        return configured.strip()
    names = (
        "AGENT_POSTGRES_HOST",
        "AGENT_POSTGRES_PORT",
        "AGENT_POSTGRES_DB",
        "AGENT_POSTGRES_USER",
        "AGENT_POSTGRES_PASSWORD",
    )
    if not any(name in values for name in names):
        return DEFAULT_AGENT_DB_URL
    user = quote((values.get("AGENT_POSTGRES_USER") or "odoo").strip(), safe="")
    password = values.get("AGENT_POSTGRES_PASSWORD") or ""
    credentials = f"{user}:{quote(password, safe='')}" if password else user
    host = (values.get("AGENT_POSTGRES_HOST") or "127.0.0.1").strip()
    port = (values.get("AGENT_POSTGRES_PORT") or "55432").strip()
    database = quote((values.get("AGENT_POSTGRES_DB") or "dev").strip(), safe="")
    return f"postgresql+psycopg://{credentials}@{host}:{port}/{database}"


def database_url_from_environment(
    environ: MutableMapping[str, str] | None = None,
) -> str:
    values = os.environ if environ is None else environ
    return _database_url(values)


@dataclass(frozen=True)
class AgentSettings:
    env_file: str
    model_id: str
    openai_base_url: str
    openai_api_key: str | None
    host: str
    port: int
    workers: int
    reload: bool
    access_log: bool
    debug: bool
    cors_allowed_origins: tuple[str, ...]
    database_url: str
    skills_dir: str | None
    workspace_hmac_secret: str

    @classmethod
    def from_environment(
        cls,
        environ: MutableMapping[str, str] | None = None,
        *,
        load_env_file: bool = True,
    ) -> "AgentSettings":
        values = os.environ if environ is None else environ
        env_file = (values.get("AGENT_ENV_FILE") or DEFAULT_ENV_FILE).strip() or DEFAULT_ENV_FILE
        if load_env_file:
            for key, value in dotenv_values(env_file).items():
                if value is not None and key not in values:
                    values[key] = value
        origins = tuple(
            origin.strip()
            for origin in values.get("AGENTOS_CORS_ORIGINS", ",".join(DEFAULT_CORS_ORIGINS)).split(
                ","
            )
            if origin.strip()
        )
        return cls(
            env_file=env_file,
            model_id=values.get("MODEL", DEFAULT_MODEL_ID),
            openai_base_url=values.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
            openai_api_key=values.get("OPENAI_API_KEY"),
            host=values.get("AGENT_OS_HOST", "127.0.0.1"),
            port=_positive_int(values, "AGENT_OS_PORT", 7777, maximum=65535),
            workers=_positive_int(values, "AGENT_OS_WORKERS", 4),
            reload=_flag(values.get("AGENT_OS_RELOAD")),
            access_log=_flag(values.get("AGENT_OS_ACCESS_LOG")),
            debug=_flag(values.get("AGENT_DEBUG")),
            cors_allowed_origins=origins,
            database_url=database_url_from_environment(values),
            skills_dir=values.get("AGENT_SKILLS_DIR"),
            workspace_hmac_secret=values.get("AGUI_WORKSPACE_HMAC_SECRET", ""),
        )
