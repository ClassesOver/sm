import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from agentos_dev.coding import agentos as coding_agentos
from agentos_dev.settings import AgentSettings


def test_coding_entrypoints_do_not_import_reporting():
    script = """
import json
import sys
import agentos_dev.coding
import agentos_dev.coding.cli
import agentos_dev.coding.agentos
print(json.dumps(sorted(name for name in sys.modules if name.startswith('agentos_dev.coding.reporting'))))
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == []


def test_coding_agentos_registers_only_facade(monkeypatch):
    settings = AgentSettings.from_environment(
        {"JWT_VERIFICATION_KEY": "test-key"}, load_env_file=False
    )
    context = SimpleNamespace(database=object())
    worker = SimpleNamespace(id="worker")
    facade = SimpleNamespace(id="facade")
    captured = {}

    class FakeAgentOS:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def get_app(self):
            return FastAPI()

    monkeypatch.setattr(coding_agentos, "create_cli_context", lambda _settings: context)
    monkeypatch.setattr(coding_agentos, "create_cli_agent", lambda _context: worker)
    monkeypatch.setattr(
        coding_agentos,
        "create_cli_app_agent",
        lambda _context, _worker: facade,
    )
    monkeypatch.setattr(coding_agentos, "AgentOS", FakeAgentOS)
    monkeypatch.setattr(coding_agentos, "AGUI", lambda **kwargs: kwargs)

    coding_agentos.create_agentos(settings)

    assert captured["agents"] == [facade]
    assert worker not in captured["agents"]
    assert captured["interfaces"] == [{"agent": facade}]
    assert captured["authorization"] is True
    assert captured["authorization_config"].user_isolation is True


def test_coding_agentos缺少jwt密钥时拒绝启动(monkeypatch):
    settings = AgentSettings.from_environment({}, load_env_file=False)
    monkeypatch.setattr(coding_agentos, "create_cli_context", lambda _settings: SimpleNamespace())
    monkeypatch.setattr(coding_agentos, "create_cli_agent", lambda _context: object())
    monkeypatch.setattr(coding_agentos, "create_cli_app_agent", lambda _context, _worker: object())

    with pytest.raises(ValueError, match="JWT_VERIFICATION_KEY"):
        coding_agentos.create_agentos(settings)
