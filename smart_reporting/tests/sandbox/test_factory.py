from __future__ import annotations

from smart_reporting.runtime.settings import AgentSettings
from smart_reporting.sandbox import DaytonaProvider
from smart_reporting.sandbox.factory import create_sandbox_provider

from .test_daytona_provider import FakeDaytonaClient, MemoryRegistry


def test_factory_builds_daytona_provider_without_accessing_network() -> None:
    settings = AgentSettings.from_environment(
        {
            "SANDBOX_PROVIDER": "daytona",
            "AGENT_WORKSPACE_HMAC_SECRET": "0123456789abcdef0123456789abcdef",
            "DAYTONA_DEFAULT_SNAPSHOT": "reporting-snapshot",
        },
        load_env_file=False,
    )

    provider = create_sandbox_provider(
        settings,
        registry=MemoryRegistry(),
        daytona_client=FakeDaytonaClient(),
    )

    assert isinstance(provider, DaytonaProvider)
