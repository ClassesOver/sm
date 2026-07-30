import os
from collections.abc import MutableMapping
from dataclasses import dataclass
from ipaddress import IPv4Network, ip_network
from urllib.parse import quote, urlsplit

from dotenv import dotenv_values

DEFAULT_ENV_FILE = ".env"
DEFAULT_MODEL_ID = "qwen3.6-35b-a3b"
DEFAULT_MODEL_TIMEOUT_SECONDS = 900
DEFAULT_WORKSPACE_SNAPSHOT = "sandbox-tools"
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


def _daytona_network_allow_list(values: MutableMapping[str, str]) -> str | None:
    raw = values.get("DAYTONA_NETWORK_ALLOW_LIST", "").strip()
    if not raw:
        return None
    entries = [entry.strip() for entry in raw.split(",")]
    if any(not entry for entry in entries) or len(entries) > 10:
        raise ValueError("DAYTONA_NETWORK_ALLOW_LIST 必须包含 1 到 10 个 IPv4 CIDR")
    networks: list[str] = []
    for entry in entries:
        if "/" not in entry:
            raise ValueError("DAYTONA_NETWORK_ALLOW_LIST 必须使用 IPv4 CIDR")
        try:
            network = ip_network(entry, strict=True)
        except ValueError as error:
            raise ValueError("DAYTONA_NETWORK_ALLOW_LIST 包含无效 IPv4 CIDR") from error
        if not isinstance(network, IPv4Network):
            raise ValueError("DAYTONA_NETWORK_ALLOW_LIST 仅支持 IPv4 CIDR")
        networks.append(str(network))
    return ",".join(networks)


def _phoenix_endpoint(values: MutableMapping[str, str]) -> str | None:
    raw = values.get("AGENT_TRACING_PHOENIX_ENDPOINT", "").strip()
    if not raw:
        return None
    if len(raw) > 2048:
        raise ValueError("AGENT_TRACING_PHOENIX_ENDPOINT 长度不能超过 2048")
    parsed = urlsplit(raw)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("AGENT_TRACING_PHOENIX_ENDPOINT 必须是有效的 HTTP(S) 地址")
    endpoint = raw.rstrip("/")
    if not endpoint.endswith("/v1/traces"):
        endpoint = f"{endpoint}/v1/traces"
    return endpoint


def _report_metadata_url(values: MutableMapping[str, str]) -> str | None:
    raw = values.get("AGENT_REPORT_METADATA_URL", "").strip()
    if not raw:
        return None
    if len(raw) > 2048:
        raise ValueError("AGENT_REPORT_METADATA_URL 长度不能超过 2048")
    parsed = urlsplit(raw)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("AGENT_REPORT_METADATA_URL 必须是有效的 HTTP(S) 地址")
    return raw.rstrip("/")


def _phoenix_project_name(values: MutableMapping[str, str]) -> str:
    name = values.get("AGENT_TRACING_PHOENIX_PROJECT", "agentos").strip()
    if not name or len(name) > 128:
        raise ValueError("AGENT_TRACING_PHOENIX_PROJECT 长度必须为 1 到 128")
    return name


@dataclass(frozen=True)
class AgentSettings:
    env_file: str
    model_id: str
    model_timeout_seconds: int
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
    report_data_sources_dir: str | None
    report_metadata_url: str | None
    report_metadata_token: str | None
    workspace_hmac_secret: str
    workspace_snapshot: str
    daytona_network_allow_list: str | None
    enable_tool_result_compression: bool
    enable_session_summaries: bool
    assistant_enable_thinking: bool
    coding_enable_thinking: bool
    report_enable_thinking: bool
    report_enable_vision: bool
    tracing_enabled: bool
    tracing_phoenix_endpoint: str | None
    tracing_phoenix_api_key: str | None
    tracing_phoenix_project_name: str
    context_token_budget: int
    history_token_budget: int
    output_token_reserve: int

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
        context_token_budget = _positive_int(
            values,
            "AGENT_CONTEXT_TOKEN_BUDGET",
            262144,
        )
        history_token_budget = _positive_int(
            values,
            "AGENT_HISTORY_TOKEN_BUDGET",
            196608,
            maximum=context_token_budget,
        )
        output_token_reserve = _positive_int(
            values,
            "AGENT_OUTPUT_TOKEN_RESERVE",
            32768,
        )
        if output_token_reserve >= context_token_budget:
            raise ValueError("AGENT_OUTPUT_TOKEN_RESERVE 必须小于 AGENT_CONTEXT_TOKEN_BUDGET")
        return cls(
            env_file=env_file,
            model_id=values.get("MODEL", DEFAULT_MODEL_ID),
            model_timeout_seconds=_positive_int(
                values,
                "AGENT_MODEL_TIMEOUT_SECONDS",
                DEFAULT_MODEL_TIMEOUT_SECONDS,
                maximum=3600,
            ),
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
            report_data_sources_dir=(
                values.get("AGENT_REPORT_DATA_SOURCES_DIR", "").strip() or None
            ),
            report_metadata_url=_report_metadata_url(values),
            report_metadata_token=(values.get("AGENT_REPORT_METADATA_TOKEN", "").strip() or None),
            workspace_hmac_secret=values.get("AGUI_WORKSPACE_HMAC_SECRET", ""),
            workspace_snapshot=(
                values.get("DAYTONA_DEFAULT_SNAPSHOT") or DEFAULT_WORKSPACE_SNAPSHOT
            ).strip()
            or DEFAULT_WORKSPACE_SNAPSHOT,
            daytona_network_allow_list=_daytona_network_allow_list(values),
            enable_tool_result_compression=_flag(
                values.get("AGENT_ENABLE_TOOL_RESULT_COMPRESSION"), default=True
            ),
            enable_session_summaries=_flag(
                values.get("AGENT_ENABLE_SESSION_SUMMARIES"), default=True
            ),
            assistant_enable_thinking=_flag(
                values.get("AGENT_ASSISTANT_ENABLE_THINKING"), default=False
            ),
            coding_enable_thinking=_flag(values.get("AGENT_CODING_ENABLE_THINKING"), default=True),
            report_enable_thinking=_flag(values.get("AGENT_REPORT_ENABLE_THINKING"), default=True),
            report_enable_vision=_flag(values.get("AGENT_REPORT_ENABLE_VISION"), default=False),
            tracing_enabled=_flag(values.get("AGENT_TRACING_ENABLED")),
            tracing_phoenix_endpoint=_phoenix_endpoint(values),
            tracing_phoenix_api_key=(
                values.get("AGENT_TRACING_PHOENIX_API_KEY", "").strip() or None
            ),
            tracing_phoenix_project_name=_phoenix_project_name(values),
            context_token_budget=context_token_budget,
            history_token_budget=history_token_budget,
            output_token_reserve=output_token_reserve,
        )
