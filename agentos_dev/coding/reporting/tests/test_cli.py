import pytest

from agentos_dev.coding.reporting import cli as cli_module
from agentos_dev.coding.reporting.cli import read_report_request, run_cli
from agentos_dev.coding.reporting.models import ReportingError


def test_report_cli_uses_run_line_to_submit_multiline_input():
    values = iter(["生成经营分析", "类型: StarRocks", "/run"])

    result = read_report_request(read=lambda _prompt: next(values))

    assert result == "生成经营分析\n类型: StarRocks"


@pytest.mark.anyio
async def test_report_cli_rejects_incomplete_intake_before_creating_traced_context(monkeypatch):
    values = iter(["生成经营分析", "/run"])
    monkeypatch.setattr(
        cli_module,
        "create_cli_context",
        lambda *_args, **_kwargs: pytest.fail("不得在 intake 之前初始化 tracing"),
    )

    with pytest.raises(ReportingError) as error:
        await run_cli(read=lambda _prompt: next(values), write=lambda _value: None)

    assert error.value.code == "source_connection_incomplete"


def test_report_cli_rejects_arguments():
    with pytest.raises(SystemExit, match="agentos_dev.coding.reporting.cli"):
        cli_module.main(["report"])
