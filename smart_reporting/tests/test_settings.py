from pathlib import Path

import pytest

from smart_reporting.reporting.agent import _report_model
from smart_reporting.runtime.settings import (
    DEFAULT_AGENT_DB_URL,
    DEFAULT_MPLCONFIGDIR,
    DEFAULT_REPORTING_HOST_WORKSPACE_ROOT,
    DEFAULT_WORKSPACE_SNAPSHOT,
    AgentSettings,
)


def settings(values=None, **overrides):
    environ = {} if values is None else values
    environ.update(overrides)
    return AgentSettings.from_environment(environ, load_env_file=False)


def test_settings_defaults():
    environ: dict[str, str] = {}

    current = settings(environ)

    assert current.env_file == ".env"
    assert environ["MPLCONFIGDIR"] == DEFAULT_MPLCONFIGDIR
    assert current.reporting_host_workspace_root == DEFAULT_REPORTING_HOST_WORKSPACE_ROOT
    assert current.port == 7777
    assert current.workers == 1
    assert current.log_file_path is None
    assert current.log_file_max_bytes == 50 * 1024 * 1024
    assert current.log_file_backup_count == 5
    assert current.database_url == DEFAULT_AGENT_DB_URL
    assert current.workspace_snapshot == DEFAULT_WORKSPACE_SNAPSHOT
    assert current.daytona_network_allow_list is None
    assert current.sandbox_provider == "daytona"
    assert current.sandbox_local_profile is None
    assert current.sandbox_local_endpoint is None
    assert current.sandbox_rootfs_digest is None
    assert current.cors_allowed_origins == (
        "http://127.0.0.1:18069",
        "http://localhost:18069",
    )
    assert current.reporting_mcp_allowed_hosts == ()
    assert current.enable_tool_result_compression is True
    assert current.enable_session_summaries is True
    assert current.model_vllm_reasoning is False
    assert current.model_fast_id == "qwen3.6-35b-a3b"
    assert current.model_standard_id == "deepseek-v4-flash-0731"
    assert current.model_strong_id == "deepseek-v4-flash-0731"
    assert current.model_fast_structured_mode == "json_schema"
    assert current.model_standard_structured_mode == "json_schema"
    assert current.model_strong_structured_mode == "json_schema"
    assert current.model_structured_strict is True
    assert current.report_phase_enable_thinking is True
    assert current.report_phase_temperature == 0.1
    assert current.report_phase_reasoning_effort == "low"
    assert current.report_phase_thinking_budget == 8192
    assert current.report_enable_thinking is True
    assert current.report_planner_reasoning_effort == "high"
    assert current.report_planner_thinking_budget == 8192
    assert current.report_enable_vision is False
    assert current.report_vision_model == "qwen3.6-flash"
    assert current.model_timeout_seconds == 900
    assert current.tracing_enabled is False
    assert current.report_context_token_budget == 1048576
    assert current.report_output_token_reserve == 393216
    assert current.report_analysis_concurrency == 1
    assert current.report_section_concurrency == 1
    assert current.report_data_sources_dir is None
    assert current.report_metadata_url is None
    assert current.report_metadata_token is None
    assert current.report_public_base_url is None


def test_runtime_directory_defaults_allow_environment_overrides(tmp_path: Path) -> None:
    matplotlib_root = tmp_path / "matplotlib"
    workspace_root = tmp_path / "reporting-workspaces"
    environ = {
        "MPLCONFIGDIR": str(matplotlib_root),
        "REPORTING_HOST_WORKSPACE_ROOT": str(workspace_root),
    }

    current = settings(environ)

    assert environ["MPLCONFIGDIR"] == str(matplotlib_root)
    assert current.reporting_host_workspace_root == str(workspace_root)


def test_agent_feature_flags_can_be_disabled():
    current = settings(
        AGENT_ENABLE_TOOL_RESULT_COMPRESSION="false",
        AGENT_ENABLE_SESSION_SUMMARIES="0",
        AGENT_REPORT_CODING_ENABLE_THINKING="no",
        AGENT_REPORT_CODING_TEMPERATURE="0.35",
        AGENT_REPORT_CODING_REASONING_EFFORT="max",
        AGENT_REPORT_CODING_THINKING_BUDGET="4096",
        AGENT_REPORT_ENABLE_THINKING="false",
        AGENT_REPORT_PLANNER_REASONING_EFFORT="high",
        AGENT_REPORT_PLANNER_THINKING_BUDGET="2048",
        AGENT_REPORT_ENABLE_VISION="true",
        AGENT_REPORT_VISION_MODEL="vision-model",
        AGENT_REPORT_CONTEXT_TOKEN_BUDGET="524288",
        AGENT_REPORT_OUTPUT_TOKEN_RESERVE="131072",
        AGENT_REPORT_ANALYSIS_CONCURRENCY="3",
        AGENT_REPORT_SECTION_CONCURRENCY="4",
    )

    assert current.enable_tool_result_compression is False
    assert current.enable_session_summaries is False
    assert current.report_phase_enable_thinking is False
    assert current.report_phase_temperature == 0.35
    assert current.report_phase_reasoning_effort == "max"
    assert current.report_phase_thinking_budget == 4096
    assert current.report_enable_thinking is False
    assert current.report_planner_reasoning_effort == "high"
    assert current.report_planner_thinking_budget == 2048
    assert current.report_enable_vision is True
    assert current.report_vision_model == "vision-model"
    assert current.report_context_token_budget == 524288
    assert current.report_output_token_reserve == 131072
    assert current.report_analysis_concurrency == 3
    assert current.report_section_concurrency == 4


@pytest.mark.parametrize("value", ["0", "6", "invalid"])
def test_report_section_concurrency_is_bounded(value):
    with pytest.raises(ValueError, match="AGENT_REPORT_SECTION_CONCURRENCY"):
        settings(AGENT_REPORT_SECTION_CONCURRENCY=value)


@pytest.mark.parametrize("value", ["0", "5", "invalid"])
def test_report_analysis_concurrency_is_bounded(value):
    with pytest.raises(ValueError, match="AGENT_REPORT_ANALYSIS_CONCURRENCY"):
        settings(AGENT_REPORT_ANALYSIS_CONCURRENCY=value)


def test_model_timeout_comes_from_environment():
    assert settings(AGENT_MODEL_TIMEOUT_SECONDS="3600").model_timeout_seconds == 3600


def test_vllm_reasoning_flag_is_preserved():
    current = settings(AGENT_MODEL_VLLM_REASONING="true")

    assert current.model_vllm_reasoning is True


def test_model_tier_ids_come_from_environment():
    current = settings(
        AGENT_MODEL_FAST="fast-model",
        AGENT_MODEL_STANDARD="standard-model",
        AGENT_MODEL_STRONG="strong-model",
    )

    assert current.model_fast_id == "fast-model"
    assert current.model_standard_id == "standard-model"
    assert current.model_strong_id == "strong-model"


def test_reporting_phase_model_uses_standard_tier_configuration():
    model = _report_model(settings(AGENT_MODEL_STANDARD="tier-standard"), enable_thinking=True)

    assert model.id == "tier-standard"
    assert model.strict_output is True


def test_reporting_structured_modes_can_be_overridden_per_tier():
    current = settings(
        AGENT_MODEL_FAST_STRUCTURED_MODE="json_object",
        AGENT_MODEL_STANDARD_STRUCTURED_MODE="json_schema",
        AGENT_MODEL_STRONG_STRUCTURED_MODE="json_object",
    )

    assert current.model_fast_structured_mode == "json_object"
    assert current.model_standard_structured_mode == "json_schema"
    assert current.model_strong_structured_mode == "json_object"


def test_reporting_structured_strict_can_be_disabled_globally():
    current = settings(AGENT_MODEL_STRUCTURED_STRICT="false")
    model = _report_model(current, enable_thinking=True)

    assert current.model_structured_strict is False
    assert model.strict_output is False


def test_report_vision_model_comes_from_environment():
    assert settings(AGENT_REPORT_VISION_MODEL="custom-vision").report_vision_model == (
        "custom-vision"
    )


@pytest.mark.parametrize("name", ["AGENT_REPORT_CODING_TEMPERATURE"])
@pytest.mark.parametrize("value", ["invalid", "-0.1", "2.1"])
def test_invalid_reporting_phase_temperature_is_rejected(name, value):
    with pytest.raises(ValueError, match=name):
        settings(**{name: value})


@pytest.mark.parametrize(
    "name",
    [
        "AGENT_REPORT_CODING_REASONING_EFFORT",
        "AGENT_REPORT_PLANNER_REASONING_EFFORT",
    ],
)
def test_invalid_reporting_phase_reasoning_effort_is_rejected(name):
    with pytest.raises(ValueError, match=name):
        settings(**{name: "unbounded"})


@pytest.mark.parametrize(
    "name",
    [
        "AGENT_REPORT_CODING_REASONING_EFFORT",
        "AGENT_REPORT_PLANNER_REASONING_EFFORT",
    ],
)
@pytest.mark.parametrize("value", ["minimal", "medium", "xhigh"])
def test_reporting_reasoning_effort_only_accepts_deepseek_v4_levels(name, value):
    with pytest.raises(ValueError, match=name):
        settings(**{name: value})


def test_reporting_coding_reasoning_effort_accepts_low():
    current = settings(AGENT_REPORT_CODING_REASONING_EFFORT="low")
    assert current.report_phase_reasoning_effort == "low"


def test_reporting_planner_reasoning_effort_accepts_low():
    current = settings(AGENT_REPORT_PLANNER_REASONING_EFFORT="low")
    assert current.report_planner_reasoning_effort == "low"


@pytest.mark.parametrize(
    "name",
    [
        "AGENT_REPORT_CODING_THINKING_BUDGET",
        "AGENT_REPORT_PLANNER_THINKING_BUDGET",
    ],
)
@pytest.mark.parametrize("value", ["invalid", "0", "131073"])
def test_invalid_reporting_phase_thinking_budget_is_rejected(name, value):
    with pytest.raises(ValueError, match=name):
        settings(**{name: value})


@pytest.mark.parametrize("value", ["invalid", "0", "3601"])
def test_model_timeout_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="AGENT_MODEL_TIMEOUT_SECONDS"):
        settings(AGENT_MODEL_TIMEOUT_SECONDS=value)


def test_agent_tracing_can_be_enabled():
    current = settings(AGENT_TRACING_ENABLED="true")

    assert current.tracing_enabled is True


def test_workspace_snapshot_comes_from_environment():
    assert settings(DAYTONA_DEFAULT_SNAPSHOT=" custom-snapshot ").workspace_snapshot == (
        "custom-snapshot"
    )
    assert settings(DAYTONA_DEFAULT_SNAPSHOT=" ").workspace_snapshot == DEFAULT_WORKSPACE_SNAPSHOT


def test_daytona_network_allow_list_is_validated_and_normalized():
    current = settings(DAYTONA_NETWORK_ALLOW_LIST=" 203.0.113.10/32, 192.168.1.0/24 ")

    assert current.daytona_network_allow_list == "203.0.113.10/32,192.168.1.0/24"


@pytest.mark.parametrize(
    "value",
    [
        "203.0.113.10",
        "203.0.113.10/24",
        "2001:db8::/32",
        ",".join(f"10.0.0.{index}/32" for index in range(11)),
    ],
)
def test_daytona_network_allow_list_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="DAYTONA_NETWORK_ALLOW_LIST"):
        settings(DAYTONA_NETWORK_ALLOW_LIST=value)


def test_local_sandbox_configuration_is_validated_and_normalized() -> None:
    current = settings(
        SANDBOX_PROVIDER=" LOCAL ",
        SANDBOX_LOCAL_PROFILE=" OPENEULER ",
        SANDBOX_LOCAL_ENDPOINT=" unix:///run/local-sandboxd.sock ",
        SANDBOX_ROOTFS_DIGEST="sha256:" + "a" * 64,
    )

    assert current.sandbox_provider == "local"
    assert current.sandbox_local_profile == "openeuler"
    assert current.sandbox_local_endpoint == "unix:///run/local-sandboxd.sock"
    assert current.sandbox_rootfs_digest == "sha256:" + "a" * 64


@pytest.mark.parametrize(
    "missing",
    ["SANDBOX_LOCAL_PROFILE", "SANDBOX_LOCAL_ENDPOINT", "SANDBOX_ROOTFS_DIGEST"],
)
def test_local_sandbox_requires_complete_configuration(missing: str) -> None:
    values = {
        "SANDBOX_PROVIDER": "local",
        "SANDBOX_LOCAL_PROFILE": "ubuntu",
        "SANDBOX_LOCAL_ENDPOINT": "unix:///run/local-sandboxd.sock",
        "SANDBOX_ROOTFS_DIGEST": "sha256:" + "a" * 64,
    }
    values.pop(missing)

    with pytest.raises(ValueError, match=missing):
        settings(values)


@pytest.mark.parametrize(
    "name,value",
    [
        ("SANDBOX_PROVIDER", "docker"),
        ("SANDBOX_LOCAL_PROFILE", "centos"),
        ("SANDBOX_LOCAL_ENDPOINT", "http://sandbox.internal"),
        ("SANDBOX_LOCAL_ENDPOINT", "unix://relative.sock"),
        ("SANDBOX_ROOTFS_DIGEST", "latest"),
    ],
)
def test_local_sandbox_rejects_unsafe_configuration(name: str, value: str) -> None:
    values = {
        "SANDBOX_PROVIDER": "local",
        "SANDBOX_LOCAL_PROFILE": "ubuntu",
        "SANDBOX_LOCAL_ENDPOINT": "unix:///run/local-sandboxd.sock",
        "SANDBOX_ROOTFS_DIGEST": "sha256:" + "a" * 64,
    }
    values[name] = value

    with pytest.raises(ValueError, match=name):
        settings(values)


def test_local_https_endpoint_requires_complete_mtls_configuration() -> None:
    values = {
        "SANDBOX_PROVIDER": "local",
        "SANDBOX_LOCAL_PROFILE": "ubuntu",
        "SANDBOX_LOCAL_ENDPOINT": "https://sandbox.internal:8443",
        "SANDBOX_ROOTFS_DIGEST": "sha256:" + "a" * 64,
    }

    with pytest.raises(ValueError, match="SANDBOX_LOCAL_CA_CERT"):
        settings(values)


def test_daytona_provider_does_not_validate_unused_local_fields() -> None:
    current = settings(
        SANDBOX_PROVIDER="daytona",
        SANDBOX_LOCAL_PROFILE="invalid",
        SANDBOX_LOCAL_ENDPOINT="http://unsafe.internal",
        SANDBOX_ROOTFS_DIGEST="latest",
    )

    assert current.sandbox_provider == "daytona"
    assert current.sandbox_local_profile is None


def test_report_data_sources_dir_is_trimmed():
    assert settings(
        AGENT_REPORT_DATA_SOURCES_DIR=" /run/agentos/reporting "
    ).report_data_sources_dir == ("/run/agentos/reporting")


def test_report_metadata_config_is_normalized():
    current = settings(
        AGENT_REPORT_METADATA_URL=" https://metadata.internal/ ",
        AGENT_REPORT_METADATA_TOKEN=" token ",
    )

    assert current.report_metadata_url == "https://metadata.internal"
    assert current.report_metadata_token == "token"


@pytest.mark.parametrize(
    "value",
    ["ftp://metadata.internal", "https://user@metadata.internal", "https://metadata/x?q=1"],
)
def test_report_metadata_url_rejects_unsafe_values(value):
    with pytest.raises(ValueError, match="AGENT_REPORT_METADATA_URL"):
        settings(AGENT_REPORT_METADATA_URL=value)


def test_report_public_base_url_is_normalized() -> None:
    current = settings(AGENT_REPORT_PUBLIC_BASE_URL=" http://10.233.32.64:27018/ ")

    assert current.report_public_base_url == "http://10.233.32.64:27018"


@pytest.mark.parametrize(
    "value",
    [
        "ftp://reports.example.com",
        "https://user:secret@reports.example.com",
        "https://reports.example.com/path?token=secret",
        "https://reports.example.com/path#fragment",
    ],
)
def test_report_public_base_url_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError, match="AGENT_REPORT_PUBLIC_BASE_URL"):
        settings(AGENT_REPORT_PUBLIC_BASE_URL=value)


def test_reporting_host_workspace_root_is_normalized(tmp_path: Path) -> None:
    root = tmp_path / "reporting-workspaces"

    current = settings(REPORTING_HOST_WORKSPACE_ROOT=str(root))

    assert current.reporting_host_workspace_root == str(root)
    assert root.is_dir()


@pytest.mark.parametrize("value", ["", "relative/path"])
def test_reporting_host_workspace_root_rejects_non_absolute_values(value: str) -> None:
    with pytest.raises(ValueError, match="REPORTING_HOST_WORKSPACE_ROOT"):
        settings(REPORTING_HOST_WORKSPACE_ROOT=value)


def test_reporting_host_workspace_root_rejects_file(tmp_path: Path) -> None:
    target = tmp_path / "workspace-file"
    target.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ValueError, match="REPORTING_HOST_WORKSPACE_ROOT"):
        settings(REPORTING_HOST_WORKSPACE_ROOT=str(target))


def test_reporting_host_workspace_root_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "workspace-target"
    target.mkdir()
    link = tmp_path / "workspace-link"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="REPORTING_HOST_WORKSPACE_ROOT"):
        settings(REPORTING_HOST_WORKSPACE_ROOT=str(link))


def test_context_budget_rejects_invalid_reserve():
    with pytest.raises(ValueError, match="AGENT_REPORT_OUTPUT_TOKEN_RESERVE"):
        settings(
            AGENT_REPORT_CONTEXT_TOKEN_BUDGET="1024",
            AGENT_REPORT_OUTPUT_TOKEN_RESERVE="1024",
        )


def test_model_tiers_ignore_obsolete_model_variable_and_prefer_process_environment(tmp_path):
    env_file = tmp_path / "agent.env"
    env_file.write_text(
        "MODEL=obsolete-file-model\nAGENT_MODEL_STANDARD=file-standard\nOPENAI_API_KEY=file-key\n",
        encoding="utf-8",
    )
    environ = {
        "AGENT_ENV_FILE": str(env_file),
        "MODEL": "obsolete-process-model",
        "AGENT_MODEL_STANDARD": "process-standard",
        "REPORTING_HOST_WORKSPACE_ROOT": str(tmp_path / "reporting-workspaces"),
    }

    current = AgentSettings.from_environment(environ)

    assert not hasattr(current, "model_id")
    assert current.model_standard_id == "process-standard"
    assert current.openai_api_key == "file-key"
    assert environ["OPENAI_API_KEY"] == "file-key"


@pytest.mark.parametrize(
    "name,value",
    [
        ("AGENT_OS_PORT", "x"),
        ("AGENT_OS_PORT", "0"),
        ("AGENT_OS_PORT", "65536"),
        ("AGENT_OS_WORKERS", "-1"),
        ("AGENT_OS_WORKERS", "2"),
    ],
)
def test_invalid_port_and_workers(name, value):
    with pytest.raises(ValueError, match=name):
        settings(**{name: value})


def test_smart_reporting_env_example_matches_settings_contract() -> None:
    env_path = Path(__file__).parents[1] / ".env.example"
    values = dict(
        line.split("=", 1)
        for line in env_path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )

    current = AgentSettings.from_environment(values, load_env_file=False)

    assert values["AGENT_ENV_FILE"] == ".env"
    assert current.workers == 1


def test_cors_discards_empty_entries():
    assert settings(
        AGENTOS_CORS_ORIGINS=" https://one.example, ,https://two.example "
    ).cors_allowed_origins == (
        "https://one.example",
        "https://two.example",
    )


def test_reporting_mcp_allowed_hosts_discards_empty_entries():
    assert settings(
        AGENT_REPORTING_MCP_ALLOWED_HOSTS=" reporting.internal:7777, ,localhost:7777 "
    ).reporting_mcp_allowed_hosts == (
        "reporting.internal:7777",
        "localhost:7777",
    )


def test_database_precedence_and_url_escaping():
    assert (
        settings(
            DATABASE_URL="postgresql://database/db", AGENT_DB_URL="postgresql://agent/db"
        ).database_url
        == "postgresql://agent/db"
    )
    current = settings(
        AGENT_POSTGRES_USER="agent user",
        AGENT_POSTGRES_PASSWORD="p@ss:/word",
        AGENT_POSTGRES_DB="agent data",
    )
    assert current.database_url == (
        "postgresql+psycopg://agent%20user:p%40ss%3A%2Fword@127.0.0.1:55432/agent%20data"
    )


def test_report_editor_export_timeout_is_configurable_and_bounded():
    assert settings().report_editor_export_timeout_seconds == 1200
    assert (
        settings(
            AGENT_REPORT_EDITOR_EXPORT_TIMEOUT_SECONDS="1800"
        ).report_editor_export_timeout_seconds
        == 1800
    )
    with pytest.raises(ValueError, match="AGENT_REPORT_EDITOR_EXPORT_TIMEOUT_SECONDS"):
        settings(AGENT_REPORT_EDITOR_EXPORT_TIMEOUT_SECONDS="3601")


def test_unused_generic_token_budget_settings_do_not_block_startup():
    # Reporting 只使用 AGENT_REPORT_* 预算；旧的通用预算变量既不生效，也不能因
    # 相互校验阻止启动。
    current = settings(AGENT_CONTEXT_TOKEN_BUDGET="1000", AGENT_OUTPUT_TOKEN_RESERVE="5000")

    assert current.report_context_token_budget == 1048576
    assert not hasattr(current, "context_token_budget")
