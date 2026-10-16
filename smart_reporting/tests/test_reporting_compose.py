import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml  # type: ignore[import-untyped]


def test_reporting_compose_uses_image_owned_package_entrypoint():
    repository_root = Path(__file__).parents[2]
    compose_path = repository_root / "docker-compose.yml"
    compose = yaml.load(compose_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    service = compose["services"]["reporting-os"]

    assert "command" not in service
    assert 'CMD ["/app/.venv/bin/python", "-m", "smart_reporting.app"]' in (
        repository_root / "Dockerfile"
    ).read_text(encoding="utf-8")
    assert service["environment"]["AGENT_OS_WORKERS"] == "1"
    assert service["environment"]["AGENT_REPORTING_MCP_ALLOWED_HOSTS"] == (
        "${AGENT_REPORTING_MCP_ALLOWED_HOSTS:-}"
    )


def test_reporting_runtime_image_includes_git_patch_kernel() -> None:
    repository_root = Path(__file__).parents[2]
    dockerfile = (repository_root / "Dockerfile").read_text(encoding="utf-8")
    runtime_stage = dockerfile.split("FROM base AS runtime", maxsplit=1)[1]
    system_dependencies = runtime_stage.split("COPY pyproject.toml uv.lock ./", maxsplit=1)[0]

    assert "git" in system_dependencies.split()


def test_reporting_runtime_image_owns_directory_defaults() -> None:
    repository_root = Path(__file__).parents[2]
    dockerfile = (repository_root / "Dockerfile").read_text(encoding="utf-8")
    runtime_environment = dockerfile.split("ENV AGENT_OS_HOST=0.0.0.0", maxsplit=1)[1]

    assert "MPLCONFIGDIR=/tmp/reporting-matplotlib" in runtime_environment
    assert "REPORTING_HOST_WORKSPACE_ROOT=/tmp/smart-reporting-workspaces" in runtime_environment


def test_reporting_deploy_configuration_has_no_sandbox_settings():
    repository_root = Path(__file__).parents[2]
    compose = yaml.load(
        (repository_root / "docker-compose.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    environment = compose["services"]["reporting-os"]["environment"]

    assert not [name for name in environment if "DAYTONA" in name or "SANDBOX" in name]
    for path in (
        repository_root / ".env.example",
        repository_root / "smart_reporting" / ".env.example",
        repository_root / "smart_reporting" / "README.md",
    ):
        assert "DAYTONA" not in path.read_text(encoding="utf-8").upper(), path
    assert not (repository_root / "scripts" / "configure_daytona_env.sh").exists()


def test_reporting_compose_disables_fg_data_profiling_analytics():
    repository_root = Path(__file__).parents[2]
    compose = yaml.load(
        (repository_root / "docker-compose.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    assert (
        compose["services"]["reporting-os"]["environment"]["YDATA_PROFILING_NO_ANALYTICS"] == "true"
    )


def test_reporting_db_publishes_host_port_and_readme_names_agno_version() -> None:
    repository_root = Path(__file__).parents[2]
    compose = yaml.load(
        (repository_root / "docker-compose.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    assert compose["services"]["reporting-db"]["ports"] == ["127.0.0.1:55432:5432"]
    assert "Agno 3.1.2" in (repository_root / "README.md").read_text(encoding="utf-8")


def test_smart_reporting_readme_uses_existing_database_service() -> None:
    repository_root = Path(__file__).parents[2]
    compose = yaml.load(
        (repository_root / "docker-compose.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    readme = (repository_root / "smart_reporting" / "README.md").read_text(encoding="utf-8")

    assert "reporting-db" in compose["services"]
    assert "docker compose up -d reporting-db" in readme


def test_reporting_compose_public_download_example_uses_published_port() -> None:
    repository_root = Path(__file__).parents[2]
    compose = yaml.load(
        (repository_root / "docker-compose.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    published_port = int(compose["services"]["reporting-os"]["ports"][0].split(":", 1)[0])
    env_values = dict(
        line.split("=", 1)
        for line in (repository_root / ".env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )

    assert urlsplit(env_values["AGENT_REPORT_PUBLIC_BASE_URL"]).port == published_port


def test_reporting_compose_mounts_writable_tiktoken_cache() -> None:
    repository_root = Path(__file__).parents[2]
    compose = yaml.load(
        (repository_root / "docker-compose.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    service = compose["services"]["reporting-os"]

    assert service["environment"]["TIKTOKEN_CACHE_DIR"] == "/opt/tiktoken-cache"
    cache_mount = next(
        mount
        for mount in service["volumes"]
        if isinstance(mount, dict) and mount.get("target") == "/opt/tiktoken-cache"
    )
    assert cache_mount == {
        "type": "bind",
        "source": "${AGENT_TIKTOKEN_CACHE_DIR:-./data/tiktoken-cache}",
        "target": "/opt/tiktoken-cache",
    }


def test_reporting_compose_persists_host_workspace():
    """工作区文件必须随容器重建持久化，否则编辑 revision 打开 500、重复导出死锁。"""
    repository_root = Path(__file__).parents[2]
    compose = yaml.load(
        (repository_root / "docker-compose.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    service = compose["services"]["reporting-os"]

    assert service["environment"]["REPORTING_HOST_WORKSPACE_ROOT"] == (
        "/var/lib/reporting-workspaces"
    )
    assert (
        "${AGENT_REPORT_WORKSPACE_DIR:-./data/reporting-workspaces}:/var/lib/reporting-workspaces"
        in service["volumes"]
    )


def test_report_editor_static_lives_outside_source_bind_mount() -> None:
    """源码只读 bind mount 会遮蔽源码树内的前端产物；命名卷只首播种，升级后仍是旧前端。"""

    repository_root = Path(__file__).parents[2]
    dockerfile = (repository_root / "Dockerfile").read_text(encoding="utf-8")
    compose = yaml.load(
        (repository_root / "docker-compose.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    service = compose["services"]["reporting-os"]

    assert "COPY --from=report-editor-frontend /build/static /opt/report-editor-static" in (
        dockerfile
    )
    assert "AGENT_REPORT_EDITOR_STATIC_DIR=/opt/report-editor-static" in dockerfile
    assert not any(
        str(mount.get("target", "") if isinstance(mount, dict) else mount).startswith(
            "/app/smart_reporting/report_editor/static"
        )
        for mount in service["volumes"]
    )
    assert "volumes" not in compose


def test_agentos_readme_only_references_existing_compose_services() -> None:
    repository_root = Path(__file__).parents[2]
    readme = (repository_root / "README.md").read_text(encoding="utf-8")

    assert "docker compose --env-file .env.example" not in readme
    assert "bash scripts/configure_agentos_env.sh .env" in readme


@pytest.mark.parametrize("existing_public_url", [None, "https://reports.example.com"])
def test_agentos_env_update_adds_required_public_url_without_overwriting_existing_values(
    tmp_path: Path, existing_public_url: str | None
) -> None:
    repository_root = Path(__file__).parents[2]
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "configure_agentos_env.sh"
    script.write_bytes((repository_root / "scripts/configure_agentos_env.sh").read_bytes())
    template = repository_root / ".env.example"
    (tmp_path / ".env.example").write_bytes(template.read_bytes())
    env_file = tmp_path / ".env"
    lines = [
        "OPENAI_API_KEY=existing-key",
        "AGENT_POSTGRES_PASSWORD=existing-password",
        "AGENT_WORKSPACE_HMAC_SECRET=01234567890123456789012345678901",
        "CUSTOM_SETTING=keep",
    ]
    if existing_public_url is not None:
        lines.append(f"AGENT_REPORT_PUBLIC_BASE_URL={existing_public_url}")
    env_file.write_text("\n".join((*lines, "")), encoding="utf-8")

    subprocess.run(
        ["bash", str(script), str(env_file)],
        input="n\nn\n",
        check=True,
        capture_output=True,
        text=True,
    )

    values = dict(
        line.split("=", 1)
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    template_values = dict(
        line.split("=", 1)
        for line in template.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    assert values["AGENT_REPORT_PUBLIC_BASE_URL"] == (
        existing_public_url or template_values["AGENT_REPORT_PUBLIC_BASE_URL"]
    )
    assert values["OPENAI_API_KEY"] == "existing-key"
    assert values["AGENT_POSTGRES_PASSWORD"] == "existing-password"
    assert values["AGENT_WORKSPACE_HMAC_SECRET"] == "01234567890123456789012345678901"
    assert values["CUSTOM_SETTING"] == "keep"
    assert "AGENT_REPORT_CONTEXT_TOKEN_BUDGET" not in values
