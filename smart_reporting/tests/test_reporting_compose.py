import os
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
    assert 'CMD ["python", "-m", "smart_reporting.app"]' in (
        repository_root / "Dockerfile"
    ).read_text(encoding="utf-8")
    assert service["environment"]["AGENT_OS_WORKERS"] == "1"


def test_reporting_compose_disables_fg_data_profiling_analytics():
    repository_root = Path(__file__).parents[2]
    compose = yaml.load(
        (repository_root / "docker-compose.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    assert compose["services"]["reporting-os"]["environment"][
        "YDATA_PROFILING_NO_ANALYTICS"
    ] == "true"


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


def test_daytona_runner_waits_for_api_health_without_reverse_dependency() -> None:
    repository_root = Path(__file__).parents[2]
    compose = yaml.load(
        (repository_root / "docker/docker-compose.yaml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    api = compose["services"]["api"]
    runner = compose["services"]["runner"]

    assert "/api/health" in " ".join(api["healthcheck"]["test"])
    assert "runner" not in api["depends_on"]
    assert runner["depends_on"]["api"]["condition"] == "service_healthy"


def test_daytona_env_init_prepares_dex_bind_mount_for_image_user(tmp_path: Path) -> None:
    repository_root = Path(__file__).parents[2]
    scripts_dir = tmp_path / "scripts"
    docker_dir = tmp_path / "docker"
    fake_bin = tmp_path / "bin"
    scripts_dir.mkdir()
    docker_dir.mkdir()
    fake_bin.mkdir()
    script = scripts_dir / "configure_daytona_env.sh"
    script.write_bytes((repository_root / "scripts/configure_daytona_env.sh").read_bytes())
    (docker_dir / ".env.example").write_bytes(
        (repository_root / "docker/.env.example").read_bytes()
    )
    chown_log = tmp_path / "chown.log"
    commands = {
        "id": '#!/bin/sh\nprintf "0\\n"\n',
        "chown": '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CHOWN_LOG"\n',
        "openssl": '#!/bin/sh\nprintf "abcdefghijklmnop\\n"\n',
        "htpasswd": "#!/bin/sh\nprintf 'admin:$2b$10$aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n'\n",
    }
    for name, content in commands.items():
        command = fake_bin / name
        command.write_text(content, encoding="utf-8")
        command.chmod(0o755)

    subprocess.run(
        ["bash", str(script), str(docker_dir / ".env")],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "HOST_UID": "1000",
            "HOST_GID": "1000",
            "CHOWN_LOG": str(chown_log),
        },
    )

    data_root = docker_dir / "data"
    assert {path.name for path in data_root.iterdir()} == {
        "db",
        "redis",
        "registry",
        "minio",
        "runner",
        "dex",
    }
    assert f"-R 1001:1001 {data_root / 'dex'}" in chown_log.read_text(encoding="utf-8")
