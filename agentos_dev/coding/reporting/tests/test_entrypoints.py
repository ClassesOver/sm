import importlib

from agentos_dev.coding.reporting import agentos as report_agentos
from agentos_dev.settings import AgentSettings


def test_report_entrypoints_import_independently():
    for name in (
        "agentos_dev.coding.reporting",
        "agentos_dev.coding.reporting.cli",
        "agentos_dev.coding.reporting.agentos",
        "agentos_dev.coding.reporting.__main__",
    ):
        if name.endswith(".__main__"):
            continue
        assert importlib.import_module(name) is not None


def test_report_agentos_registers_only_facade(monkeypatch):
    settings = AgentSettings.from_environment({}, load_env_file=False)
    database = object()
    context = type(
        "Context",
        (),
        {
            "database": database,
            "workspace_service": object(),
            "coding_repository": object(),
        },
    )()
    coding_worker = type("Agent", (), {"skills": object()})()
    report_worker = type("Agent", (), {"skills": object()})()
    facade = object()
    captured = {}

    class FakeRuntime:
        workflow = object()
        cleanup_cancelled = object()

        def __init__(self, **_kwargs):
            pass

    class FakeAgentOS:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(report_agentos, "create_cli_context", lambda _settings: context)
    monkeypatch.setattr(report_agentos, "create_cli_agent", lambda _context: coding_worker)
    monkeypatch.setattr(
        report_agentos, "create_report_worker", lambda *_args, **_kwargs: report_worker
    )
    monkeypatch.setattr(report_agentos, "CodingTaskSupervisor", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(report_agentos, "CodingExecutionKernel", lambda *_args: object())
    monkeypatch.setattr(
        report_agentos, "ReportDataSourceToolkit", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(report_agentos, "ReportWorkflowRuntime", FakeRuntime)
    monkeypatch.setattr(
        report_agentos, "ReportWorkflowController", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(report_agentos, "create_report_agent", lambda *_args: facade)
    monkeypatch.setattr(report_agentos, "TemporaryCredentialStore", lambda: object())
    monkeypatch.setattr(
        report_agentos,
        "TemporarySourceBindingService",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        report_agentos.SkillValidatorRegistry,
        "from_skills",
        lambda _skills: object(),
    )
    monkeypatch.setattr(report_agentos, "AgentOS", FakeAgentOS)
    monkeypatch.setattr(report_agentos, "AGUI", lambda **kwargs: kwargs)

    report_agentos.create_agentos(settings)

    assert captured["agents"] == [facade]
    assert report_worker not in captured["agents"]
    assert coding_worker not in captured["agents"]
    assert captured["interfaces"] == [{"agent": facade}]
