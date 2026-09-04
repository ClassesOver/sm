import os
from collections.abc import MutableMapping
from dataclasses import dataclass
from ipaddress import IPv4Network, ip_network
from urllib.parse import quote, urlsplit

from dotenv import dotenv_values

DEFAULT_ENV_FILE = ".env"
DEFAULT_MODEL_FAST_ID = "qwen3.6-35b-a3b"
DEFAULT_MODEL_STANDARD_ID = "deepseek-v4-flash-0731"
DEFAULT_MODEL_STRONG_ID = "deepseek-v4-flash-0731"
DEFAULT_REPORT_VISION_MODEL_ID = "qwen3.6-flash"
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


def _temperature(values: MutableMapping[str, str], name: str, default: float) -> float:
    raw = values.get(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} 必须是数字") from error
    if not 0 <= value <= 2:
        raise ValueError(f"{name} 必须在 0 到 2 之间")
    return value


def _report_reasoning_effort(
    values: MutableMapping[str, str], name: str, default: str = "high"
) -> str:
    value = values.get(name, default).strip().lower()
    if value not in {"high", "max"}:
        raise ValueError(f"{name} 必须是 high 或 max")
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


def _report_public_base_url(values: MutableMapping[str, str]) -> str | None:
    raw = values.get("AGENT_REPORT_PUBLIC_BASE_URL", "").strip()
    if not raw:
        return None
    if len(raw) > 2048:
        raise ValueError("AGENT_REPORT_PUBLIC_BASE_URL 长度不能超过 2048")
    parsed = urlsplit(raw)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("AGENT_REPORT_PUBLIC_BASE_URL 必须是有效的 HTTP(S) 地址")
    return raw.rstrip("/")


@dataclass(frozen=True)
class AgentSettings:
    env_file: str
    model_fast_id: str
    model_standard_id: str
    model_strong_id: str
    model_timeout_seconds: int
    model_vllm_reasoning: bool
    openai_base_url: str
    openai_api_key: str | None
    host: str
    port: int
    workers: int
    reload: bool
    access_log: bool
    log_file_path: str | None
    log_file_max_bytes: int
    log_file_backup_count: int
    debug: bool
    cors_allowed_origins: tuple[str, ...]
    reporting_mcp_allowed_hosts: tuple[str, ...]
    database_url: str
    skills_dir: str | None
    report_data_sources_dir: str | None
    report_metadata_url: str | None
    report_metadata_token: str | None
    report_public_base_url: str | None
    workspace_hmac_secret: str
    workspace_snapshot: str
    daytona_network_allow_list: str | None
    enable_tool_result_compression: bool
    enable_session_summaries: bool
    report_coding_enable_thinking: bool
    report_coding_temperature: float
    report_coding_reasoning_effort: str
    report_coding_thinking_budget: int
    report_enable_thinking: bool
    report_planner_reasoning_effort: str
    report_planner_thinking_budget: int
    report_enable_vision: bool
    report_vision_model: str
    tracing_enabled: bool
    context_token_budget: int
    output_token_reserve: int
    report_context_token_budget: int
    report_output_token_reserve: int
    report_analysis_concurrency: int
    report_section_concurrency: int
    report_coding_execution_mode: str

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
        output_token_reserve = _positive_int(
            values,
            "AGENT_OUTPUT_TOKEN_RESERVE",
            32768,
        )
        if output_token_reserve >= context_token_budget:
            raise ValueError("AGENT_OUTPUT_TOKEN_RESERVE 必须小于 AGENT_CONTEXT_TOKEN_BUDGET")
        report_context_token_budget = _positive_int(
            values,
            "AGENT_REPORT_CONTEXT_TOKEN_BUDGET",
            1048576,
        )
        report_output_token_reserve = _positive_int(
            values,
            "AGENT_REPORT_OUTPUT_TOKEN_RESERVE",
            393216,
        )
        if report_output_token_reserve >= report_context_token_budget:
            raise ValueError(
                "AGENT_REPORT_OUTPUT_TOKEN_RESERVE 必须小于 AGENT_REPORT_CONTEXT_TOKEN_BUDGET"
            )
        report_analysis_concurrency = _positive_int(
            values,
            "AGENT_REPORT_ANALYSIS_CONCURRENCY",
            1,
            maximum=4,
        )
        report_section_concurrency = _positive_int(
            values,
            "AGENT_REPORT_SECTION_CONCURRENCY",
            1,
            maximum=5,
        )
        report_coding_execution_mode = (
            values.get("AGENT_REPORT_CODING_EXECUTION_MODE", "sequential").strip().lower()
        )
        if report_coding_execution_mode not in {"sequential", "parallel"}:
            raise ValueError("AGENT_REPORT_CODING_EXECUTION_MODE 必须是 sequential 或 parallel")
        model_vllm_reasoning = _flag(values.get("AGENT_MODEL_VLLM_REASONING"))
        return cls(
            env_file=env_file,
            model_fast_id=(
                values.get("AGENT_MODEL_FAST", DEFAULT_MODEL_FAST_ID).strip()
                or DEFAULT_MODEL_FAST_ID
            ),
            model_standard_id=(
                values.get("AGENT_MODEL_STANDARD", DEFAULT_MODEL_STANDARD_ID).strip()
                or DEFAULT_MODEL_STANDARD_ID
            ),
            model_strong_id=(
                values.get("AGENT_MODEL_STRONG", DEFAULT_MODEL_STRONG_ID).strip()
                or DEFAULT_MODEL_STRONG_ID
            ),
            model_timeout_seconds=_positive_int(
                values,
                "AGENT_MODEL_TIMEOUT_SECONDS",
                DEFAULT_MODEL_TIMEOUT_SECONDS,
                maximum=3600,
            ),
            model_vllm_reasoning=model_vllm_reasoning,
            openai_base_url=values.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
            openai_api_key=values.get("OPENAI_API_KEY"),
            host=values.get("AGENT_OS_HOST", "127.0.0.1"),
            port=_positive_int(values, "AGENT_OS_PORT", 7777, maximum=65535),
            workers=_positive_int(values, "AGENT_OS_WORKERS", 1, maximum=1),
            reload=_flag(values.get("AGENT_OS_RELOAD")),
            access_log=_flag(values.get("AGENT_OS_ACCESS_LOG")),
            log_file_path=(values.get("AGENT_LOG_FILE", "").strip() or None),
            log_file_max_bytes=_positive_int(values, "AGENT_LOG_FILE_MAX_BYTES", 50 * 1024 * 1024),
            log_file_backup_count=_positive_int(values, "AGENT_LOG_FILE_BACKUP_COUNT", 5),
            debug=_flag(values.get("AGENT_DEBUG")),
            cors_allowed_origins=origins,
            reporting_mcp_allowed_hosts=tuple(
                item.strip()
                for item in values.get("AGENT_REPORTING_MCP_ALLOWED_HOSTS", "").split(",")
                if item.strip()
            ),
            database_url=database_url_from_environment(values),
            skills_dir=values.get("AGENT_SKILLS_DIR"),
            report_data_sources_dir=(
                values.get("AGENT_REPORT_DATA_SOURCES_DIR", "").strip() or None
            ),
            report_metadata_url=_report_metadata_url(values),
            report_metadata_token=(values.get("AGENT_REPORT_METADATA_TOKEN", "").strip() or None),
            report_public_base_url=_report_public_base_url(values),
            workspace_hmac_secret=values.get("AGENT_WORKSPACE_HMAC_SECRET", ""),
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
            report_coding_enable_thinking=_flag(
                values.get("AGENT_REPORT_CODING_ENABLE_THINKING"), default=True
            ),
            report_coding_temperature=_temperature(values, "AGENT_REPORT_CODING_TEMPERATURE", 0.1),
            report_coding_reasoning_effort=_report_reasoning_effort(
                values, "AGENT_REPORT_CODING_REASONING_EFFORT", default="high"
            ),
            report_coding_thinking_budget=_positive_int(
                values, "AGENT_REPORT_CODING_THINKING_BUDGET", 8192, maximum=131072
            ),
            report_enable_thinking=_flag(values.get("AGENT_REPORT_ENABLE_THINKING"), default=True),
            report_planner_reasoning_effort=_report_reasoning_effort(
                values, "AGENT_REPORT_PLANNER_REASONING_EFFORT", default="high"
            ),
            report_planner_thinking_budget=_positive_int(
                values, "AGENT_REPORT_PLANNER_THINKING_BUDGET", 8192, maximum=131072
            ),
            report_enable_vision=_flag(values.get("AGENT_REPORT_ENABLE_VISION"), default=False),
            report_vision_model=(
                values.get("AGENT_REPORT_VISION_MODEL", DEFAULT_REPORT_VISION_MODEL_ID).strip()
                or DEFAULT_REPORT_VISION_MODEL_ID
            ),
            tracing_enabled=_flag(values.get("AGENT_TRACING_ENABLED")),
            context_token_budget=context_token_budget,
            output_token_reserve=output_token_reserve,
            report_context_token_budget=report_context_token_budget,
            report_output_token_reserve=report_output_token_reserve,
            report_analysis_concurrency=report_analysis_concurrency,
            report_section_concurrency=report_section_concurrency,
            report_coding_execution_mode=report_coding_execution_mode,
        )
