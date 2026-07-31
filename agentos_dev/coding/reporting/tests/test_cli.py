from types import SimpleNamespace

import pytest

from agentos_dev.coding.reporting import cli as cli_module
from agentos_dev.coding.reporting.cli import read_report_request, run_cli
from agentos_dev.coding.reporting.models import ReportingError
from agentos_dev.settings import AgentSettings


def test_report_cli_uses_run_line_to_submit_multiline_input():
    values = iter(["生成经营分析", "类型: StarRocks", "/run"])

    result = read_report_request(read=lambda _prompt: next(values))

    assert result == "生成经营分析\n类型: StarRocks"


@pytest.mark.anyio
async def test_report_cli_rejects_invalid_envelope_before_creating_traced_context(monkeypatch):
    values = iter(["生成经营分析", "/run"])
    monkeypatch.setattr(
        cli_module,
        "create_execution_context",
        lambda *_args, **_kwargs: pytest.fail("不得在 intake 之前初始化 tracing"),
    )

    with pytest.raises(ReportingError) as error:
        await run_cli(read=lambda _prompt: next(values), write=lambda _value: None)

    assert error.value.code == "report_request_invalid"


@pytest.mark.anyio
async def test_report_cli_uses_independent_report_thinking_setting(monkeypatch):
    settings = AgentSettings.from_environment(
        {
            "AGENT_CODING_ENABLE_THINKING": "true",
            "AGENT_REPORT_CODING_ENABLE_THINKING": "false",
            "AGENT_REPORT_ENABLE_THINKING": "true",
        },
        load_env_file=False,
    )
    context = SimpleNamespace(
        settings=settings,
        database=object(),
        workspace_service=object(),
    )
    captured = {}

    class WorkerCaptured(Exception):
        pass

    def capture_worker(*_args, **kwargs):
        captured.update(kwargs)
        raise WorkerCaptured

    monkeypatch.setattr(cli_module, "parse_cli_envelope", lambda _value: object())
    monkeypatch.setattr(cli_module, "create_execution_context", lambda _settings: context)
    monkeypatch.setattr(cli_module, "TaskExecutionRepository", lambda _database: object())
    monkeypatch.setattr(cli_module, "create_report_worker", capture_worker)

    values = iter(["{}", "/run"])
    with pytest.raises(WorkerCaptured):
        await run_cli(
            settings=settings,
            read=lambda _prompt: next(values),
            write=lambda _value: None,
        )

    assert captured["report_coding_enable_thinking"] is False


def test_report_cli_rejects_arguments():
    with pytest.raises(SystemExit, match="agentos_dev.coding.reporting.cli"):
        cli_module.main(["report"])
