import asyncio
from types import SimpleNamespace

from fastapi import FastAPI

from agentos_dev import playground_agentos
from agentos_dev.settings import AgentSettings


def test_playground_agentos_registers_facades_and_closes_resources(monkeypatch):
    settings = AgentSettings.from_environment({}, load_env_file=False)
    context = SimpleNamespace(database=object())
    coding_worker = SimpleNamespace(id="coding-worker")
    coding_facade = SimpleNamespace(id="coding-agent-cli-app")
    report_worker = SimpleNamespace(id="report-worker")
    report_facade = SimpleNamespace(id="report-agent")
    closed = []
    credentials = SimpleNamespace(close_all=lambda: closed.append("credentials"))
    captured = {}

    class FakeAgentOS:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    async def close_resources(_context, *resources):
        closed.extend(resources)

    monkeypatch.setattr(playground_agentos, "create_cli_context", lambda _settings: context)
    monkeypatch.setattr(playground_agentos, "create_cli_agent", lambda _context: coding_worker)
    monkeypatch.setattr(
        playground_agentos,
        "create_cli_app_agent",
        lambda _context, _worker: coding_facade,
    )
    monkeypatch.setattr(
        playground_agentos,
        "create_report_agentos_components",
        lambda *_args: (report_facade, report_worker, credentials),
    )
    monkeypatch.setattr(playground_agentos, "_close_cli_resources", close_resources)
    monkeypatch.setattr(playground_agentos, "AgentOS", FakeAgentOS)

    playground_agentos.create_agentos(settings)

    assert captured["agents"] == [coding_facade, report_facade]
    assert coding_worker not in captured["agents"]
    assert report_worker not in captured["agents"]
    assert "interfaces" not in captured
    assert captured["db"] is context.database

    async def run_lifespan():
        async with captured["lifespan"](FastAPI()):
            pass

    asyncio.run(run_lifespan())

    assert closed == [
        "credentials",
        coding_facade,
        report_facade,
        report_worker,
        coding_worker,
    ]
