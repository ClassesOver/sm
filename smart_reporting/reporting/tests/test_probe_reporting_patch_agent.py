import asyncio
import inspect
import json
from types import SimpleNamespace

from scripts import probe_reporting_patch_agent
from scripts.probe_reporting_patch_agent import _patch_function, _task


def test_patch_probe_exposes_only_patch_to_the_model() -> None:
    received: list[dict[str, object]] = []
    target, _old, new, operation, _prompt = _task(1)
    tool = _patch_function(received, target, operation)

    assert tool.parameters == {
        "type": "object",
        "properties": {"patch": {"type": "string", "minLength": 1}},
        "required": ["patch"],
        "additionalProperties": False,
    }
    assert list(inspect.signature(tool.entrypoint).parameters) == ["patch"]

    patch = f"--- /dev/null\n+++ b/{target}\n@@ -0,0 +1 @@\n+{new}"
    result = tool.entrypoint(patch=patch)

    assert result["ok"] is True
    assert received == [{"patch": patch, "valid": True, "paths": [target]}]


def test_task_uses_parser_operation_name_for_modify() -> None:
    _target, _old, _new, operation, _prompt = _task(3)

    assert operation == "update"


def test_patch_tool_stops_attempt_after_one_validation() -> None:
    tool = _patch_function([], "analysis/income/script_003.py", "update")

    assert tool.stop_after_tool_call is True


def test_run_retries_invalid_attempt_as_fresh_agent(monkeypatch, capsys) -> None:
    attempts = 0

    class FakeAgent:
        async def arun(self, _prompt: str) -> None:
            nonlocal attempts
            attempts += 1

    def fake_build_agent(*_args, **_kwargs):
        received = _args[1]
        if attempts == 0:
            received.append({"valid": False, "patch": "bad"})
        else:
            received.append({"valid": True, "patch": "good"})
        return FakeAgent()

    monkeypatch.setattr(
        probe_reporting_patch_agent.AgentSettings,
        "from_environment",
        lambda: SimpleNamespace(model_id="test-model"),
    )
    monkeypatch.setattr(probe_reporting_patch_agent, "_build_agent", fake_build_agent)

    asyncio.run(
        probe_reporting_patch_agent._run(
            SimpleNamespace(env_file=".env", runs=1, thinking=False, progress_file=None)
        )
    )

    result = json.loads(capsys.readouterr().out)
    assert result["valid_count"] == 1
    assert result["runs"][0]["attempts"] == 2


def test_run_reports_agent_that_never_calls_patch_tool(monkeypatch, capsys) -> None:
    class FakeAgent:
        async def arun(self, _prompt: str) -> None:
            return None

    monkeypatch.setattr(
        probe_reporting_patch_agent.AgentSettings,
        "from_environment",
        lambda: SimpleNamespace(model_id="test-model"),
    )
    monkeypatch.setattr(
        probe_reporting_patch_agent, "_build_agent", lambda *_args, **_kwargs: FakeAgent()
    )

    asyncio.run(
        probe_reporting_patch_agent._run(
            SimpleNamespace(env_file=".env", runs=1, thinking=False, progress_file=None)
        )
    )

    result = json.loads(capsys.readouterr().out)
    assert result["valid_count"] == 0
    assert result["runs"][0]["attempts"] == 3
    assert result["runs"][0]["error"].startswith("no_tool_call:")
