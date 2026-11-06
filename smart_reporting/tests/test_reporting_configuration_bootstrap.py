from __future__ import annotations

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_database_bootstrap_never_loads_files_and_requires_credential_key(monkeypatch):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.reporting import bootstrap
    from smart_reporting.runtime.settings import AgentSettings

    def forbidden(*args, **kwargs):
        raise AssertionError("database 模式不能读取文件配置")

    monkeypatch.setattr(bootstrap, "load_configured_report_source_registry", forbidden)
    monkeypatch.setattr(bootstrap, "load_configured_reporting_profiles", forbidden)
    settings = AgentSettings.from_environment(
        {"AGENT_REPORT_CONFIGURATION_MODE": "database"}, load_env_file=False
    )
    engine = create_async_engine("postgresql+psycopg://localhost/unopened")
    context = SimpleNamespace(database=SimpleNamespace(db_engine=engine))
    monkeypatch.setenv("AGENT_MANAGEMENT_CREDENTIAL_KEYS", f"test:{Fernet.generate_key().decode()}")
    try:
        registry, profiles, provider = bootstrap._configuration_sources(context, settings)
        assert registry is None and profiles is None
        assert provider.repository.engine is engine
        monkeypatch.delenv("AGENT_MANAGEMENT_CREDENTIAL_KEYS")
        with pytest.raises(ManagementError, match="management_secrets_unavailable"):
            bootstrap._configuration_sources(context, settings)
    finally:
        await engine.dispose()


@pytest.mark.parametrize("database", [SimpleNamespace(), SimpleNamespace(db_engine=object())])
def test_database_bootstrap_rejects_missing_async_engine(monkeypatch, database):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.reporting.bootstrap import _configuration_sources
    from smart_reporting.runtime.settings import AgentSettings

    monkeypatch.setenv("AGENT_MANAGEMENT_CREDENTIAL_KEYS", f"test:{Fernet.generate_key().decode()}")
    settings = AgentSettings.from_environment(
        {"AGENT_REPORT_CONFIGURATION_MODE": "database"}, load_env_file=False
    )
    with pytest.raises(ManagementError, match="management_database_unavailable"):
        _configuration_sources(SimpleNamespace(database=database), settings)
