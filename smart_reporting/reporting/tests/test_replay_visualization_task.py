import asyncio
import hashlib
import json
from copy import copy, deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.models.openai.responses import OpenAIResponses
from agno.models.response import ModelResponse

from scripts import replay_visualization_task
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.benchmark_bundle import (
    BenchmarkModelConfig,
    prepare_frozen_planner_coding_bundle,
)
from smart_reporting.reporting.workflow.benchmark_variants import (
    BenchmarkVariant,
    LegacyAnalysisEvidenceDecision,
)


@pytest.mark.anyio
async def test_replay_wall_timeout_is_explicit_and_does_not_retry() -> None:
    calls = 0

    async def hanging_run():
        nonlocal calls
        calls += 1
        await asyncio.sleep(1)

    with pytest.raises(replay_visualization_task.ReplayWallTimeout) as exc_info:
        await replay_visualization_task.run_with_wall_timeout(
            hanging_run(), seconds=0.001
        )

    assert calls == 1
    assert exc_info.value.seconds == 0.001


@pytest.mark.anyio
async def test_replay_heartbeat_reports_current_phase_and_request(monkeypatch) -> None:
    observed = []
    stop = asyncio.Event()

    def record(message, *args):
        observed.append((message, args))
        stop.set()

    monkeypatch.setattr(replay_visualization_task.logger, "info", record)
    await replay_visualization_task.emit_replay_heartbeats(
        stop,
        lambda: {
            "phase": "coding",
            "elapsedSeconds": 30.5,
            "remainingSeconds": "869.5",
            "requestIndex": 3,
            "requestStatus": "started",
        },
        interval_seconds=0.001,
    )

    assert observed[0][1] == ("coding", 30.5, "869.5", 3, "started")


@pytest.mark.anyio
async def test_replay_observed_chat_preserves_started_metric_on_cancellation(
    monkeypatch,
) -> None:
    async def hanging_invoke(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(OpenAIChat, "ainvoke", hanging_invoke)
    model = replay_visualization_task.ReplayObservedOpenAIChat(id="test-model")

    with pytest.raises(replay_visualization_task.ReplayWallTimeout):
        await replay_visualization_task.run_with_wall_timeout(
            model.ainvoke([], Message(role="assistant")), seconds=0.01
        )

    assert model.replay_request_metrics() == [
        {
            "requestIndex": 1,
            "providerRequestId": "unknown",
            "durationMs": "unknown",
            "inputTokens": "unknown",
            "outputTokens": "unknown",
            "reasoningTokens": "unknown",
            "cacheReadTokens": "unknown",
            "status": "started",
        }
    ]


@pytest.mark.anyio
async def test_replay_observed_chat_settles_completed_and_failed_requests(
    monkeypatch,
) -> None:
    responses = iter(
        [
            ModelResponse(
                provider_data={"id": "response-1"},
                response_usage=SimpleNamespace(
                    input_tokens=10,
                    output_tokens=5,
                    reasoning_tokens=3,
                    cache_read_tokens=2,
                ),
            ),
            RuntimeError("provider failed"),
        ]
    )

    async def invoke(*_args, **_kwargs):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(OpenAIChat, "ainvoke", invoke)
    model = replay_visualization_task.ReplayObservedOpenAIChat(id="test-model")
    model.replay_request_metrics()
    request_copy = copy(model)

    await request_copy.ainvoke([], Message(role="assistant"))
    with pytest.raises(RuntimeError, match="provider failed"):
        await model.ainvoke([], Message(role="assistant"))

    assert model.replay_request_metrics() == [
        {
            "requestIndex": 1,
            "providerRequestId": "response-1",
            "durationMs": pytest.approx(0, abs=100),
            "inputTokens": 10,
            "outputTokens": 5,
            "reasoningTokens": 3,
            "cacheReadTokens": 2,
            "status": "completed",
        },
        {
            "requestIndex": 2,
            "providerRequestId": "unknown",
            "durationMs": pytest.approx(0, abs=100),
            "inputTokens": "unknown",
            "outputTokens": "unknown",
            "reasoningTokens": "unknown",
            "cacheReadTokens": "unknown",
            "status": "failed",
        },
    ]


def test_replay_wall_timeout_failure_is_censored() -> None:
    result = replay_visualization_task.build_replay_failure(
        replay_visualization_task.ReplayWallTimeout(3.0),
        seconds=3.0,
        workspace=Path("/tmp/replay-timeout"),
        model_metrics=[],
        coding_metrics=[],
    )

    assert result["status"] == "timed_out"
    assert result["censored"] is True
    assert result["failure"]["code"] == "report_replay_wall_timeout"
    assert result["failure"]["details"] == {
        "wallTimeoutSeconds": 3.0,
        "censored": True,
    }


@pytest.mark.anyio
@pytest.mark.parametrize("metrics", [None, SimpleNamespace(
    input_tokens=120, output_tokens=30, reasoning_tokens=20,
)])
async def test_replay_wall_timeout_preserves_started_request_metric(
    tmp_path, monkeypatch, metrics
) -> None:
    heartbeat_messages = []
    original_heartbeat = replay_visualization_task.emit_replay_heartbeats

    async def fast_heartbeat(stop, state_reader):
        await original_heartbeat(stop, state_reader, interval_seconds=0.001)

    def capture_log(message, *args):
        if message.startswith("report_replay_heartbeat"):
            heartbeat_messages.append(args)

    monkeypatch.setattr(replay_visualization_task, "emit_replay_heartbeats", fast_heartbeat)
    monkeypatch.setattr(replay_visualization_task.logger, "info", capture_log)
    source = tmp_path / "source"
    source.mkdir()
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps(
            {
                "task": {
                    "task_id": "analysis-001",
                    "task_kind": "analysis",
                    "code_mode_session_id": "analysis:analysis-001",
                    "workspace_key": "workspace-001",
                    "workspace_root": str(source),
                    "script_path": "analysis/supplement.py",
                    "authorized_read_paths": [],
                    "authorized_write_paths": [
                        "analysis/supplement.py",
                        "analysis/evidence.json",
                    ],
                    "declared_output_paths": ["analysis/evidence.json"],
                    "max_source_bytes": 100_000,
                },
                "facts": {
                    "currentAnalysis": {"analysisId": "analysis-001"},
                    "evidencePath": "analysis/evidence.json",
                },
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "result.json"

    async def hanging_provider(*_args, **_kwargs):
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    class FakeCloseable:
        async def aclose(self):
            pass

    class HangingRunner:
        def __init__(self, agent_factory, *_args, **kwargs):
            self.agent_factory = agent_factory
            self.record_metrics = kwargs["model_metrics_recorder"]

        async def run(self, *_args, **_kwargs):
            agent = self.agent_factory([])
            agent.model.configure_code_run(
                [SimpleNamespace(name="run_script")], max_model_requests=4
            )
            try:
                await agent.model.ainvoke([])
            finally:
                self.record_metrics(SimpleNamespace(metrics=metrics), 1)
            raise AssertionError("unreachable")

    monkeypatch.setattr(OpenAIResponses, "ainvoke", hanging_provider)
    monkeypatch.setattr(
        replay_visualization_task.AgentSettings,
        "from_environment",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        replay_visualization_task,
        "build_replay_model",
        lambda *_args, **_kwargs: replay_visualization_task.ReplayObservedOpenAIChat(
            id="gpt-5-test", api_key="test-key", base_url="http://localhost"
        ),
    )
    monkeypatch.setattr(
        replay_visualization_task,
        "create_reporting_code_mode_runtime",
        lambda *_args, **_kwargs: FakeCloseable(),
    )
    monkeypatch.setattr(
        replay_visualization_task, "ReportingLspProcessManager", FakeCloseable
    )
    monkeypatch.setattr(
        replay_visualization_task, "ReportVisionReviewer", lambda *_args: object()
    )
    monkeypatch.setattr(
        replay_visualization_task, "ReportingCodeGenerationRunner", HangingRunner
    )

    result = await replay_visualization_task.main(
        None,
        payload_path,
        "analysis",
        "medium",
        output_path,
        None,
        None,
        wall_timeout_seconds=1.0,
    )

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 1
    assert saved["status"] == "timed_out"
    assert saved["modelMetrics"] == [{
        "requests": 1,
        "inputTokens": 120 if metrics is not None else None,
        "outputTokens": 30 if metrics is not None else None,
        "reasoningTokens": 20 if metrics is not None else None,
    }]
    assert saved["requestMetrics"][0]["status"] == "started"
    assert any(args[3:] == (1, "started") for args in heartbeat_messages)


def _analysis_benchmark_payload(source, dataset, *, include_decision: bool) -> dict:
    facts = {
        "currentAnalysis": {"analysisId": "analysis-001"},
        "evidencePath": "analysis/evidence.json",
        "datasets": [
            {
                "path": "datasets/current.csv",
                "size": dataset.stat().st_size,
                "sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
            }
        ],
    }
    if include_decision:
        facts["evidenceDecision"] = {
            "requiresSupplementalEvidence": True,
            "reason": "需要部门明细",
            "missingFacts": ["部门收入"],
        }
    return {
        "task": {
            "task_id": "analysis-001",
            "task_kind": "analysis",
            "code_mode_session_id": "analysis:analysis-001",
            "workspace_key": "workspace-001",
            "workspace_root": str(source),
            "script_path": "analysis/supplement.py",
            "authorized_read_paths": ["datasets/current.csv"],
            "authorized_write_paths": [
                "analysis/supplement.py",
                "analysis/evidence.json",
            ],
            "declared_output_paths": ["analysis/evidence.json"],
            "max_source_bytes": 100_000,
        },
        "facts": facts,
    }


@pytest.mark.anyio
async def test_replay_runner_setup_failure_cleans_up_heartbeat_and_resources(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    dataset = source / "datasets/current.csv"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("income\n100\n", encoding="utf-8")
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(
        _analysis_benchmark_payload(source, dataset, include_decision=True)
    ), encoding="utf-8")
    closed = []

    class Resource:
        def __init__(self, name):
            self.name = name

        async def aclose(self):
            closed.append(self.name)

    def failing_runner(*_args, **_kwargs):
        raise RuntimeError("runner setup failed")

    monkeypatch.setattr(replay_visualization_task.AgentSettings, "from_environment", lambda: SimpleNamespace())
    monkeypatch.setattr(replay_visualization_task, "build_replay_model", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(replay_visualization_task, "create_reporting_code_agent_factory", lambda **_kwargs: object())
    monkeypatch.setattr(replay_visualization_task, "create_reporting_code_mode_runtime", lambda *_args, **_kwargs: Resource("runtime"))
    monkeypatch.setattr(replay_visualization_task, "ReportingLspProcessManager", lambda: Resource("lsp"))
    monkeypatch.setattr(replay_visualization_task, "ReportVisionReviewer", lambda *_args: object())
    monkeypatch.setattr(replay_visualization_task, "ReportingCodeGenerationRunner", failing_runner)
    pending_before = asyncio.all_tasks()
    output_path = tmp_path / "result.json"

    result = await replay_visualization_task.main(
        None, payload_path, "analysis", "low", output_path, None, None
    )
    pending = asyncio.all_tasks() - pending_before
    try:
        assert result == 1
        assert json.loads(output_path.read_text())["failure"]["message"] == "runner setup failed"
        assert not pending
        assert closed == ["runtime", "lsp"]
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.anyio
async def test_replay_disable_flags_mark_coding_model(tmp_path, monkeypatch):
    source = tmp_path / "source"
    dataset = source / "datasets/current.csv"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("income\n100\n", encoding="utf-8")
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(
        _analysis_benchmark_payload(source, dataset, include_decision=True)
    ), encoding="utf-8")
    sentinel = SimpleNamespace()
    closed = []

    class Resource:
        def __init__(self, name):
            self.name = name

        async def aclose(self):
            closed.append(self.name)

    def fake_factory(**kwargs):
        kwargs["model_created"](sentinel)
        return object()

    def failing_runner(*_args, **_kwargs):
        raise RuntimeError("runner setup failed")

    monkeypatch.setattr(replay_visualization_task.AgentSettings, "from_environment", lambda: SimpleNamespace())
    monkeypatch.setattr(replay_visualization_task, "build_replay_model", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(replay_visualization_task, "create_reporting_code_agent_factory", fake_factory)
    monkeypatch.setattr(replay_visualization_task, "create_reporting_code_mode_runtime", lambda *_args, **_kwargs: Resource("runtime"))
    monkeypatch.setattr(replay_visualization_task, "ReportingLspProcessManager", lambda: Resource("lsp"))
    monkeypatch.setattr(replay_visualization_task, "ReportVisionReviewer", lambda *_args: object())
    monkeypatch.setattr(replay_visualization_task, "ReportingCodeGenerationRunner", failing_runner)

    result = await replay_visualization_task.main(
        None, payload_path, "analysis", "low", tmp_path / "result.json", None, None,
        disable_history_summary=True, disable_metadata_budget=True,
    )

    assert result == 1
    assert sentinel._code_disable_history_summary is True
    assert sentinel._code_disable_metadata_budget is True


@pytest.mark.anyio
@pytest.mark.parametrize("case", ["implicit", "same_seed", "input_tamper", "seed_tamper", "different_seed"])
async def test_main_validates_frozen_payload_and_loads_signed_seed(tmp_path, monkeypatch, case):
    source = tmp_path / "source"
    dataset = source / "datasets/current.csv"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("income\n100\n", encoding="utf-8")
    seed = tmp_path / "seed.py"
    source_bytes = b"print('original failed script')\n"
    seed.write_bytes(source_bytes)
    bundle = tmp_path / "bundle"
    replay_visualization_task.prepare_replay_bundle(
        _analysis_benchmark_payload(source, dataset, include_decision=True), bundle, seed,
    )
    explicit = seed if case in {"same_seed", "different_seed"} else None
    invalid = case in {"input_tamper", "seed_tamper", "different_seed"}
    if case == "input_tamper":
        (bundle / "workspace/datasets/current.csv").write_text("income\n999\n")
    elif case == "seed_tamper":
        (bundle / "seed/seed.py").write_text("print('changed')\n")
    elif case == "different_seed":
        seed.write_text("print('different')\n")

    def model_factory(*_args, **_kwargs):
        if invalid:
            raise AssertionError("invalid bundle reached model creation")
        return object()

    class Closeable:
        async def aclose(self):
            pass

    class Runner:
        async def run(self, task, *_args, **_kwargs):
            actual = (Path(task.workspace_root) / task.script_path).read_bytes()
            assert actual == source_bytes
            assert hashlib.sha256(actual).hexdigest() == hashlib.sha256(source_bytes).hexdigest()
            return SimpleNamespace(
                script_file=SimpleNamespace(model_dump=lambda **_kwargs: {"path": task.script_path}),
                execution_receipt=SimpleNamespace(output_files=()), visual_inspection_receipts=(),
            )

    monkeypatch.setattr(replay_visualization_task.AgentSettings, "from_environment", lambda: SimpleNamespace())
    monkeypatch.setattr(replay_visualization_task, "build_replay_model", model_factory)
    monkeypatch.setattr(replay_visualization_task, "create_reporting_code_agent_factory", lambda **_kwargs: object())
    monkeypatch.setattr(replay_visualization_task, "create_reporting_code_mode_runtime", lambda *_args, **_kwargs: Closeable())
    monkeypatch.setattr(replay_visualization_task, "ReportingLspProcessManager", Closeable)
    monkeypatch.setattr(replay_visualization_task, "ReportVisionReviewer", lambda *_args: object())
    monkeypatch.setattr(replay_visualization_task, "ReportingCodeGenerationRunner", lambda *_args, **_kwargs: Runner())
    args = (None, bundle / "payload.json", "analysis", "high", tmp_path / "result.json", None, explicit)
    if invalid:
        with pytest.raises(ValueError, match="身份不一致"):
            await replay_visualization_task.main(*args)
    else:
        assert await replay_visualization_task.main(*args) == 0


def _prepare_linked_analysis_bundles(tmp_path, *, candidate=False):
    source = tmp_path / "source"
    dataset = source / "datasets/current.csv"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("income\n100\n", encoding="utf-8")
    base_payload = _analysis_benchmark_payload(source, dataset, include_decision=False)
    benchmark_bundle = tmp_path / "benchmark"
    model_config = BenchmarkModelConfig.model_validate({
        "model": "coding-model",
        "reasoningEffort": "medium",
        "reasoningSummary": "detailed",
        "enableThinkingLocation": "top_level",
        "enableThinking": True,
        "maxOutputTokens": 65536,
        "parallelToolCalls": True,
        "toolChoice": "auto",
    })
    prepare_frozen_planner_coding_bundle(
        benchmark_bundle,
        task_kind="analysis",
        planner_request={"currentAnalysis": {"analysisId": "analysis-001"}},
        coding_payload=base_payload,
        acceptance={},
        model_config=model_config,
    )
    coding_only_bundle = tmp_path / "coding-only"
    payload = _analysis_benchmark_payload(source, dataset, include_decision=True)
    if candidate:
        payload["facts"].pop("evidenceDecision")
        payload["facts"]["codingRequirements"] = [{
            "datasetId": "current", "fields": ["income"],
            "calculation": "计算合计", "outputName": "total",
        }]
        replay_visualization_task.freeze_planner_coding_payload(
            payload, coding_only_bundle, benchmark_bundle, BenchmarkVariant.CANDIDATE
        )
    else:
        replay_visualization_task.prepare_replay_bundle(payload, coding_only_bundle, None)
    return benchmark_bundle, coding_only_bundle / "payload.json", model_config


def test_coding_only_link_uses_signed_legacy_analysis_payload_and_v2_model_config(
    tmp_path,
):
    benchmark_bundle, coding_only_payload, expected_model_config = (
        _prepare_linked_analysis_bundles(tmp_path)
    )

    linked = replay_visualization_task.link_coding_only_benchmark(
        benchmark_bundle,
        coding_only_payload,
        variant=BenchmarkVariant.LEGACY,
    )

    assert linked.payload["facts"]["evidenceDecision"] == {
        "requiresSupplementalEvidence": True,
        "reason": "需要部门明细",
        "missingFacts": ["部门收入"],
    }
    assert linked.model_config == expected_model_config
    assert linked.task_kind == "analysis"
    assert linked.benchmark_mode == "coding-only"


def test_coding_only_link_rejects_payload_different_from_v2_context(tmp_path):
    benchmark_bundle, coding_only_payload, _ = _prepare_linked_analysis_bundles(tmp_path)
    payload = json.loads(coding_only_payload.read_text(encoding="utf-8"))
    payload["facts"]["evidencePath"] = "analysis/other.json"
    source = tmp_path / "source"
    drifted_bundle = tmp_path / "drifted-coding-only"
    payload["task"]["workspace_root"] = str(source)
    replay_visualization_task.prepare_replay_bundle(payload, drifted_bundle, None)

    with pytest.raises(ValueError, match="Coding payload.*不一致"):
        replay_visualization_task.link_coding_only_benchmark(
            benchmark_bundle,
            drifted_bundle / "payload.json",
            variant=BenchmarkVariant.LEGACY,
        )


def test_coding_only_link_rejects_extra_unsigned_input_identity(tmp_path):
    benchmark_bundle, coding_only_payload, _ = _prepare_linked_analysis_bundles(tmp_path)
    manifest_path = coding_only_payload.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["inputs"].append("ignored-extra-identity")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="授权输入.*身份不一致"):
        replay_visualization_task.link_coding_only_benchmark(
            benchmark_bundle,
            coding_only_payload,
            variant=BenchmarkVariant.LEGACY,
        )


@pytest.mark.anyio
@pytest.mark.parametrize("candidate", [False, True])
async def test_coding_only_benchmark_skips_planner_and_labels_result(
    tmp_path, monkeypatch, candidate
):
    benchmark_bundle, coding_only_payload, expected_model_config = (
        _prepare_linked_analysis_bundles(tmp_path, candidate=candidate)
    )
    output_path = tmp_path / "result.json"
    seen = {}

    async def planner_must_not_run(*_args, **_kwargs):
        raise AssertionError("Coding-only benchmark 不得调用 planner")

    class FakeCloseable:
        async def aclose(self):
            pass

    class FakeRunner:
        def __init__(self, **kwargs):
            self.record_failure_artifact = kwargs["failure_artifact_recorder"]

        async def run(self, task, _workspace, facts, **_kwargs):
            seen["task"] = task
            seen["facts"] = facts
            self.record_failure_artifact({"source": "failed-source", "scriptPath": task.script_path})
            return SimpleNamespace(
                script_file=SimpleNamespace(
                    model_dump=lambda **_kwargs: {"path": task.script_path}
                ),
                execution_receipt=SimpleNamespace(output_files=()),
                visual_inspection_receipts=(),
            )

    monkeypatch.setattr(
        replay_visualization_task, "run_frozen_benchmark_planner", planner_must_not_run
    )
    monkeypatch.setattr(
        replay_visualization_task.AgentSettings,
        "from_environment",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        replay_visualization_task,
        "build_replay_model",
        lambda _settings, **kwargs: seen.setdefault("modelConfig", kwargs) or object(),
    )
    monkeypatch.setattr(
        replay_visualization_task,
        "create_reporting_code_agent_factory",
        lambda **kwargs: seen.setdefault("instructions", kwargs["instructions"])
        or object(),
    )
    monkeypatch.setattr(
        replay_visualization_task,
        "create_reporting_code_mode_runtime",
        lambda *_args, **_kwargs: FakeCloseable(),
    )
    monkeypatch.setattr(
        replay_visualization_task, "ReportingLspProcessManager", FakeCloseable
    )
    monkeypatch.setattr(
        replay_visualization_task, "ReportVisionReviewer", lambda *_args: object()
    )
    monkeypatch.setattr(
        replay_visualization_task,
        "ReportingCodeGenerationRunner",
        lambda *_args, **kwargs: FakeRunner(**kwargs),
    )

    result = await replay_visualization_task.main(
        None,
        None,
        "visualization",
        "high",
        output_path,
        None,
        None,
        benchmark_bundle_dir=benchmark_bundle,
        benchmark_variant=BenchmarkVariant.CANDIDATE if candidate else BenchmarkVariant.LEGACY,
        coding_only_payload_path=coding_only_payload,
    )

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 0
    assert saved["benchmarkMode"] == "coding-only"
    assert saved["variant"] == ("candidate" if candidate else "legacy")
    assert saved["requestMetrics"] == []
    artifact = saved["firstRunFailureArtifact"]
    content = Path(artifact["path"]).read_bytes()
    assert artifact["sha256"] == hashlib.sha256(content).hexdigest()
    assert artifact["size"] == len(content)
    assert json.loads(content)["source"] == "failed-source"
    assert "failed-source" not in output_path.read_text(encoding="utf-8")
    assert "plannerMetrics" not in saved
    assert seen["modelConfig"]["benchmark_model_config"] == expected_model_config
    if candidate:
        assert seen["instructions"] == replay_visualization_task._ANALYSIS_CODE_INSTRUCTIONS
        assert seen["facts"]["codingRequirements"][0]["outputName"] == "total"
    else:
        assert seen["instructions"] == replay_visualization_task._ANALYSIS_CODE_LEGACY_INSTRUCTIONS
        assert seen["facts"]["evidenceDecision"]["requiresSupplementalEvidence"] is True


@pytest.mark.parametrize("change", ["origin", "payload", "input"])
def test_candidate_coding_only_rejects_frozen_identity_drift(tmp_path, change):
    benchmark, payload_path, _ = _prepare_linked_analysis_bundles(tmp_path, candidate=True)
    if change == "origin":
        manifest_path = payload_path.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["plannerOrigin"]["benchmarkManifestSha256"] = "changed"
        manifest_path.write_text(json.dumps(manifest))
    elif change == "payload":
        payload_path.write_text(payload_path.read_text() + " ")
    else:
        (payload_path.parent / "workspace/datasets/current.csv").write_text("income\n999\n")
    with pytest.raises(ValueError, match="身份"):
        replay_visualization_task.link_coding_only_benchmark(
            benchmark, payload_path, variant=BenchmarkVariant.CANDIDATE
        )


@pytest.mark.anyio
async def test_benchmark_planner_timeout_preserves_started_provider_request(
    tmp_path, monkeypatch
):
    benchmark_bundle, _, _ = _prepare_linked_analysis_bundles(tmp_path)
    output_path = tmp_path / "planner-timeout.json"

    async def hanging_provider(*_args, **_kwargs):
        await asyncio.Event().wait()

    async def run_hanging_planner(
        _bundle_dir, *, variant, model, metrics_sink=None
    ):
        del variant, metrics_sink
        await model.ainvoke([], Message(role="assistant"))
        raise AssertionError("unreachable")

    monkeypatch.setattr(OpenAIChat, "ainvoke", hanging_provider)
    monkeypatch.setattr(
        replay_visualization_task.AgentSettings,
        "from_environment",
        lambda: SimpleNamespace(
            model_standard_id="test-model",
            openai_api_key="test-key",
            openai_base_url=(
                "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
            ),
            report_output_token_reserve=8192,
            model_timeout_seconds=60,
        ),
    )
    monkeypatch.setattr(
        replay_visualization_task,
        "run_frozen_benchmark_planner",
        run_hanging_planner,
    )

    result = await replay_visualization_task.main(
        None,
        None,
        "analysis",
        "medium",
        output_path,
        None,
        None,
        benchmark_bundle_dir=benchmark_bundle,
        benchmark_variant=BenchmarkVariant.LEGACY,
        wall_timeout_seconds=0.01,
    )

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 1
    assert saved["status"] == "timed_out"
    assert saved["failure"]["details"]["phase"] == "planner"
    assert saved["plannerRequestMetrics"] == [
        {
            "requestIndex": 1,
            "providerRequestId": "unknown",
            "durationMs": "unknown",
            "inputTokens": "unknown",
            "outputTokens": "unknown",
            "reasoningTokens": "unknown",
            "cacheReadTokens": "unknown",
            "status": "started",
        }
    ]


def test_replay_failure_preserves_diagnostic_metrics_and_workspace(tmp_path):
    assert callable(getattr(replay_visualization_task, "build_replay_failure", None))
    build_replay_failure = replay_visualization_task.build_replay_failure
    error = ReportingError(
        "report_code_declared_output_missing",
        "声明产物不存在，不代表脚本不存在。检查 details.path 对应的写出逻辑，使用 edit_script 局部修复现有脚本，再 run_script；不得调用 write_script 整段重写。",
        details={"path": "analysis/chart-006.png", "nextTools": ["edit_script"]},
    )

    result = build_replay_failure(
        error,
        seconds=242.486,
        workspace=tmp_path / "workspace",
        model_metrics=[{"requests": 10, "reasoningTokens": 7061}],
        coding_metrics=[{"firstPatchApplied": True}],
    )

    assert result == {
        "status": "failed",
        "seconds": 242.486,
        "workspace": str(tmp_path / "workspace"),
        "modelMetrics": [{"requests": 10, "reasoningTokens": 7061}],
        "codingMetrics": [{"firstPatchApplied": True}],
        "requestMetrics": [],
        "failure": {
            "type": "ReportingError",
            "code": "report_code_declared_output_missing",
            "message": "声明产物不存在，不代表脚本不存在。检查 details.path 对应的写出逻辑，使用 edit_script 局部修复现有脚本，再 run_script；不得调用 write_script 整段重写。",
            "details": {"path": "analysis/chart-006.png", "nextTools": ["edit_script"]},
        },
    }


def test_replay_result_file_is_valid_json_even_when_console_has_other_output(tmp_path):
    assert callable(getattr(replay_visualization_task, "write_replay_result", None))
    write_replay_result = replay_visualization_task.write_replay_result
    output = tmp_path / "low.json"
    payload = {"status": "failed", "seconds": 1.25}

    write_replay_result(output, payload)

    assert json.loads(output.read_text(encoding="utf-8")) == payload


def test_prepare_replay_files_seeds_existing_script_and_clears_outputs(tmp_path):
    root = tmp_path / "workspace"
    script = root / "charts/charts.py"
    output = root / "charts/chart.png"
    script.parent.mkdir(parents=True)
    script.write_text("old source\n", encoding="utf-8")
    output.write_bytes(b"old image")
    seed = tmp_path / "seed.py"
    seed.write_text("print('seeded')\n", encoding="utf-8")
    task = SimpleNamespace(
        script_path="charts/charts.py",
        declared_output_paths=("charts/chart.png",),
    )

    replay_visualization_task.prepare_replay_files(root, task, seed)

    assert script.read_text(encoding="utf-8") == "print('seeded')\n"
    assert not output.exists()


def test_prepare_replay_files_without_seed_clears_script_and_outputs(tmp_path):
    root = tmp_path / "workspace"
    script = root / "charts/charts.py"
    output = root / "charts/chart.png"
    script.parent.mkdir(parents=True)
    script.write_text("old source\n", encoding="utf-8")
    output.write_bytes(b"old image")
    task = SimpleNamespace(
        script_path="charts/charts.py",
        declared_output_paths=("charts/chart.png",),
    )

    replay_visualization_task.prepare_replay_files(root, task, None)

    assert not script.exists()
    assert not output.exists()


def test_analysis_replay_keeps_signed_read_paths_without_visualization_facts():
    payload = {
        "task": {
            "task_kind": "analysis",
            "authorized_read_paths": ["datasets/current.csv"],
        },
        "facts": {
            "currentAnalysis": {"analysisId": "analysis_001"},
            "evidencePath": "analysis/evidence.json",
        },
    }

    normalized = replay_visualization_task.normalize_replay_payload(payload)

    assert normalized["task"]["authorized_read_paths"] == ["datasets/current.csv"]
    assert "visualizationFacts" not in normalized["facts"]


def test_analysis_replay_can_add_signed_compact_existing_facts(tmp_path):
    facts_path = tmp_path / "analysis.json"
    facts_path.write_text(
        json.dumps({
            "analysisId": "analysis_001",
            "metrics": [{
                "datasetId": "dataset-1",
                "total": 120,
                "periodValues": [{"period": "2025-01", "value": 120}],
                "topGroups": [{"group": "large", "value": 120}],
            }],
        }),
        encoding="utf-8",
    )
    payload = {
        "task": {"task_kind": "analysis", "authorized_read_paths": []},
        "facts": {"currentAnalysis": {"analysisId": "analysis_001"}},
    }

    normalized = replay_visualization_task.normalize_replay_payload(
        payload, deterministic_facts_path=facts_path
    )

    existing = normalized["facts"]["existingFacts"]
    assert existing["analysisId"] == "analysis_001"
    assert existing["metrics"] == [{"datasetId": "dataset-1", "total": 120}]


def test_analysis_replay_rejects_existing_facts_for_another_analysis(tmp_path):
    facts_path = tmp_path / "analysis.json"
    facts_path.write_text(json.dumps({"analysisId": "analysis_002"}), encoding="utf-8")
    payload = {
        "task": {"task_kind": "analysis", "authorized_read_paths": []},
        "facts": {"currentAnalysis": {"analysisId": "analysis_001"}},
    }

    try:
        replay_visualization_task.normalize_replay_payload(
            payload, deterministic_facts_path=facts_path
        )
    except ValueError as error:
        assert "analysisId" in str(error)
    else:
        raise AssertionError("expected analysis identity mismatch")


def test_replay_instructions_match_production_task_instructions():
    assert replay_visualization_task.replay_instructions("visualization") == (
        replay_visualization_task._VISUALIZATION_CODE_INSTRUCTIONS
    )
    assert replay_visualization_task.replay_instructions("analysis") == (
        replay_visualization_task._ANALYSIS_CODE_LEGACY_INSTRUCTIONS
    )
    assert replay_visualization_task.replay_instructions(
        "analysis", variant=BenchmarkVariant.CANDIDATE
    ) == replay_visualization_task._ANALYSIS_CODE_INSTRUCTIONS
    assert replay_visualization_task.replay_instructions(
        "analysis", variant=BenchmarkVariant.LEGACY
    ) == replay_visualization_task._ANALYSIS_CODE_LEGACY_INSTRUCTIONS
    assert replay_visualization_task.replay_instructions(
        "visualization", variant=BenchmarkVariant.LEGACY
    ) == replay_visualization_task._VISUALIZATION_CODE_LEGACY_INSTRUCTIONS
    assert "codingRequirements" not in "\n".join(
        replay_visualization_task._ANALYSIS_CODE_LEGACY_INSTRUCTIONS
    )
    assert "dataBindings" not in "\n".join(
        replay_visualization_task._VISUALIZATION_CODE_LEGACY_INSTRUCTIONS
    )


def test_analysis_legacy_instructions_pin_yoy_alignment_and_missing_dimension_nulls():
    instructions = "\n".join(
        replay_visualization_task._ANALYSIS_CODE_LEGACY_INSTRUCTIONS
    )
    assert "当前任务的时间粒度和比较窗口" in instructions
    assert "仅月度同比按 month（1-12）对齐" in instructions
    assert "其他粒度不得降为月份" in instructions
    assert "JSON null" in instructions
    assert "不得按 0 补齐" in instructions
    assert "不得假定收入主题、固定字段名或固定维度" in instructions


def test_visualization_coding_instructions_bound_repair_to_critical_issue():
    instructions = "\n".join(
        replay_visualization_task._VISUALIZATION_CODE_INSTRUCTIONS
    )
    assert "critical" in instructions
    assert "禁止插入临时诊断" in instructions
    assert "只修改与该问题直接相关的局部代码" in instructions


def test_benchmark_model_config_reaches_code_responses_request() -> None:
    settings = SimpleNamespace(
        model_standard_id="environment-model",
        openai_api_key="test-key",
        openai_base_url=(
            "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        ),
        report_output_token_reserve=8192,
        model_timeout_seconds=60,
    )
    config = BenchmarkModelConfig.model_validate({
        "model": "coding-model",
        "reasoningEffort": "medium",
        "reasoningSummary": "detailed",
        "enableThinkingLocation": "top_level",
        "enableThinking": True,
        "maxOutputTokens": None,
        "parallelToolCalls": True,
        "toolChoice": "auto",
    })

    model = replay_visualization_task.build_replay_model(
        settings,
        reasoning_effort="high",
        benchmark_model_config=config,
    )
    assert isinstance(model, replay_visualization_task.ReplayObservedOpenAIChat)
    agent = replay_visualization_task.create_reporting_code_agent_factory(
        model=model,
        name="benchmark-wire-test",
        task_kind="analysis",
        instructions=(),
    )([])
    params = agent.model._phase_request_model([]).get_request_params()

    assert model.id == "coding-model"
    assert model.role_map["system"] == "system"
    assert params["reasoning"] == {"effort": "medium", "summary": "detailed"}
    assert params.get("max_output_tokens") is None
    assert params["extra_body"] == {"enable_thinking": True}
    assert params["parallel_tool_calls"] is True


def test_benchmark_model_can_lower_planner_effort_without_changing_coding() -> None:
    settings = SimpleNamespace(
        model_standard_id="environment-model",
        openai_api_key="test-key",
        openai_base_url=(
            "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        ),
        report_output_token_reserve=8192,
        model_timeout_seconds=60,
    )
    config = BenchmarkModelConfig.model_validate({
        "model": "coding-model",
        "reasoningEffort": "high",
        "plannerReasoningEffort": "medium",
        "reasoningSummary": "auto",
        "enableThinkingLocation": "top_level",
        "enableThinking": True,
        "maxOutputTokens": 65536,
        "parallelToolCalls": True,
        "toolChoice": "auto",
    })

    planner = replay_visualization_task.build_replay_model(
        settings,
        reasoning_effort="high",
        benchmark_model_config=config,
        benchmark_stage="planner",
    )
    coding = replay_visualization_task.build_replay_model(
        settings,
        reasoning_effort="high",
        benchmark_model_config=config,
        benchmark_stage="coding",
    )

    assert planner.reasoning_effort == "medium"
    assert coding.reasoning_effort == "high"


def test_benchmark_model_config_rejects_planner_effort_crossing_none_boundary() -> None:
    with pytest.raises(
        ValueError,
        match="plannerReasoningEffort.*reasoningEffort.*none",
    ):
        BenchmarkModelConfig.model_validate({
            "model": "coding-model",
            "reasoningEffort": "high",
            "plannerReasoningEffort": "none",
            "reasoningSummary": "auto",
            "enableThinkingLocation": "top_level",
            "enableThinking": True,
            "maxOutputTokens": 65536,
            "parallelToolCalls": True,
            "toolChoice": "auto",
        })


@pytest.mark.parametrize(
    ("base_url", "location", "enable_thinking"),
    [
        (
            "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            "omitted",
            None,
        ),
        ("http://localhost:8000/v1", "top_level", True),
    ],
)
def test_benchmark_model_rejects_thinking_location_provider_mismatch(
    base_url, location, enable_thinking
) -> None:
    settings = SimpleNamespace(
        model_standard_id="environment-model",
        openai_api_key="test-key",
        openai_base_url=base_url,
        report_output_token_reserve=8192,
        model_timeout_seconds=60,
    )
    config = BenchmarkModelConfig.model_validate({
        "model": "coding-model",
        "reasoningEffort": "medium",
        "reasoningSummary": "auto",
        "enableThinkingLocation": location,
        "enableThinking": enable_thinking,
        "maxOutputTokens": None,
        "parallelToolCalls": True,
        "toolChoice": "auto",
    })

    with pytest.raises(ValueError, match="enableThinkingLocation"):
        replay_visualization_task.build_replay_model(
            settings,
            reasoning_effort="high",
            benchmark_model_config=config,
        )


def test_analysis_replay_reports_production_evidence_schema_failure():
    diagnostic = replay_visualization_task.analysis_evidence_diagnostic(
        b'{"findings":[],"reconciliations":[],"warnings":[]}',
        {"analysisId": "analysis_001", "datasetIds": ["dataset-1"]},
    )

    assert diagnostic is not None
    assert diagnostic["code"] == "report_analysis_evidence_schema_invalid"
    assert "issueSummary" in diagnostic["details"]


def test_analysis_replay_accepts_valid_production_evidence():
    diagnostic = replay_visualization_task.analysis_evidence_diagnostic(
        b'{"findings":[{"name":"x"}],'
        b'"reconciliations":[{"name":"check","passed":false}],'
        b'"warnings":["difference retained"]}',
        {"analysisId": "analysis_001", "datasetIds": ["dataset-1"]},
    )

    assert diagnostic is None


def test_find_task_payload_selects_requested_coding_stage():
    rows = [
        {
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(
                        {"task": {"task_kind": "analysis"}, "facts": {}}
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"task": {"task_kind": "visualization"}, "facts": {}}
                    ),
                },
            ]
        }
    ]

    assert replay_visualization_task.find_task_payload(rows, "analysis")["task"] == {
        "task_kind": "analysis"
    }
    assert replay_visualization_task.find_task_payload(rows, "visualization")[
        "task"
    ] == {"task_kind": "visualization"}


@pytest.mark.parametrize("drift", [False, True])
def test_load_task_restores_responses_message_with_same_span_metadata(monkeypatch, drift):
    from unittest.mock import MagicMock

    task = {"task_kind": "visualization", "script_path": "charts/a.py"}
    payload = {"task": task, "facts": {"example": 1}}
    host = {**task, "workspace_root": "/tmp/original"}
    if drift:
        host["script_path"] = "charts/other.py"
    attributes = {
        "input.value": json.dumps({"messages": [
            {"role": "assistant", "content": "not a task"},
            {"role": "user", "content": json.dumps(payload)},
        ]}),
        "metadata": json.dumps({"reportingCodingTaskContext": host}),
    }
    connection = MagicMock()
    connection.__enter__.return_value.execute.return_value = [(attributes,)]
    monkeypatch.setattr(replay_visualization_task.psycopg, "connect", lambda *_: connection)
    monkeypatch.setattr(replay_visualization_task, "psycopg_db_url", lambda: "test")
    if drift:
        with pytest.raises(ValueError, match="模型 task 与宿主"):
            replay_visualization_task.load_task("run", "visualization")
    else:
        assert replay_visualization_task.load_task("run", "visualization") == {
            **payload, "task": host,
        }


def _trace_span(
    agent_id,
    input_payload,
    *,
    output_payload=None,
    host_task_context=None,
    span_id="span-1",
):
    attributes = {
        "agno.agent.id": agent_id,
        "input.value": json.dumps(input_payload),
        "output.value": (
            json.dumps(output_payload) if output_payload is not None else ""
        ),
    }
    if host_task_context is not None:
        attributes["metadata"] = json.dumps(
            {"reportingCodingTaskContext": host_task_context}
        )
    return {
        "span_id": span_id,
        "parent_span_id": "parent-1",
        "attributes": attributes,
    }


def _candidate_visualization_plan(
    chart_path: str, *, interactive_path: str | None = None
) -> dict:
    return {
        "charts": [
            {
                "chartId": "chart-1",
                "sourcePath": chart_path,
                "renderer": "plotly" if interactive_path else "matplotlib",
                "interactivePath": interactive_path,
                "title": "月度收入趋势",
                "altText": "月度收入趋势图",
                "citationIds": ["citation-1"],
                "metricCodes": ["income"],
                "currentPeriod": "2025",
                "comparisonPeriod": None,
                "comparisonType": "none",
                "sourceDatasetId": "dataset-1",
                "aggregationGrain": "month",
                "comparability": "strict",
                "visualForm": "按月折线图",
                "dataBindings": [
                    {
                        "analysisId": "analysis-001",
                        "factPath": "facts/analysis-001.json",
                        "dataPath": "metrics[0].periodValues",
                        "fields": ["period", "value"],
                        "role": "月度趋势",
                    }
                ],
            }
        ],
        "warnings": [],
    }


def test_extract_analysis_trace_pairs_identity_and_removes_planner_output() -> None:
    planner_request = {
        "currentAnalysis": {"analysisId": "analysis-001"},
        "deterministicFacts": {"analysisId": "analysis-001"},
        "datasets": [{"datasetId": "dataset-1"}],
        "analysisBlock": {"blockId": "analysis-001:evidence:decision"},
    }
    coding_payload = {
        "task": {"task_kind": "analysis"},
        "facts": {
            "currentAnalysis": {"analysisId": "analysis-001"},
            "datasets": planner_request["datasets"],
            "evidenceDecision": {"requiresSupplementalEvidence": True},
        },
    }
    rows = [
        _trace_span(
            "report-analysis-evidence-planner",
            planner_request,
            span_id="planner-1",
        ),
        _trace_span(
            "report-analysis-script-writer", coding_payload, span_id="coding-1"
        ),
    ]

    extracted = replay_visualization_task.extract_benchmark_trace_inputs(
        rows,
        task_kind="analysis",
        task_identity="analysis-001",
    )

    assert extracted["plannerRequest"] == planner_request
    assert "evidenceDecision" not in extracted["codingPayload"]["facts"]
    assert extracted["sourceSpans"] == {
        "planner": "planner-1",
        "coding": "coding-1",
    }


@pytest.mark.parametrize("interactive", [False, True])
def test_extract_visualization_trace_pairs_declared_output_paths(interactive) -> None:
    chart_path = "charts/chart-1.png"
    interactive_path = "charts/chart-1.plotly.json"
    planner_request = {
        "sectionCode": "section-001",
        "visualizationWorkspace": {"chartOutputRoot": "charts"},
        "visualizationFacts": [
            {
                "analysisId": "analysis-001",
                "factFile": {"path": "facts/analysis-001.json"},
                "dataDescriptors": [
                    {"dataPath": "metrics[0].periodValues", "fields": ["period", "value"]},
                    {"dataPath": "metrics[1].periodValues", "fields": ["period", "value"]},
                ],
            }
        ],
    }
    planner_output = _candidate_visualization_plan(
        chart_path, interactive_path=interactive_path if interactive else None
    )
    candidate_facts = [
        {
            **planner_request["visualizationFacts"][0],
            "dataDescriptors": [
                planner_request["visualizationFacts"][0]["dataDescriptors"][0]
            ],
        }
    ]
    coding_payload = {
        "task": {
            "task_kind": "visualization",
            "declared_output_paths": (
                [chart_path, interactive_path] if interactive else [chart_path]
            ),
        },
        "facts": {
            "visualizationFacts": candidate_facts,
            "visualizationPlan": planner_output,
        },
    }
    rows = [
        _trace_span(
            "reporting-visualization-generator",
            planner_request,
            output_payload=planner_output,
            span_id="planner-1",
        ),
        _trace_span(
            "reporting-visualization-code-agent",
            coding_payload,
            span_id="coding-1",
        ),
    ]

    extracted = replay_visualization_task.extract_benchmark_trace_inputs(
        rows,
        task_kind="visualization",
        task_identity="section-001",
    )

    assert extracted["plannerRequest"] == planner_request
    assert "visualizationPlan" not in extracted["codingPayload"]["facts"]
    assert extracted["codingPayload"]["facts"]["visualizationFacts"] == planner_request[
        "visualizationFacts"
    ]

    drifted_rows = deepcopy(rows)
    drifted_payload = json.loads(drifted_rows[1]["attributes"]["input.value"])
    drifted_payload["facts"]["visualizationFacts"] = planner_request[
        "visualizationFacts"
    ]
    drifted_rows[1]["attributes"]["input.value"] = json.dumps(drifted_payload)
    with pytest.raises(ValueError, match="visualizationFacts 投影不一致"):
        replay_visualization_task.extract_benchmark_trace_inputs(
            drifted_rows,
            task_kind="visualization",
            task_identity="section-001",
        )


def test_extract_visualization_trace_restores_host_task_context() -> None:
    chart_path = "charts/chart-1.png"
    planner_request = {
        "sectionCode": "section-001",
        "visualizationFacts": [
            {
                "analysisId": "analysis-001",
                "factFile": {"path": "facts/analysis-001.json"},
                "dataDescriptors": [
                    {"dataPath": "metrics[0].periodValues", "fields": ["period", "value"]}
                ],
            }
        ],
    }
    planner_output = _candidate_visualization_plan(chart_path)
    model_task = {
        "task_kind": "visualization",
        "script_path": "charts/charts.py",
        "authorized_read_paths": ["facts/analysis-001.json"],
        "authorized_write_paths": ["charts/charts.py", chart_path],
        "declared_output_paths": [chart_path],
        "max_source_bytes": 100_000,
    }
    host_task = {
        "task_id": "section-001",
        "task_kind": "visualization",
        "code_mode_session_id": "visualization:section-001",
        "workspace_key": "workspace-001",
        "workspace_root": "/tmp/workspace-001",
        **{key: value for key, value in model_task.items() if key != "task_kind"},
    }
    rows = [
        _trace_span(
            "reporting-visualization-generator",
            planner_request,
            output_payload=planner_output,
            span_id="planner-1",
        ),
        _trace_span(
            "reporting-visualization-code-agent",
            {
                "task": model_task,
                "facts": {
                    "visualizationFacts": planner_request["visualizationFacts"],
                    "visualizationPlan": planner_output,
                },
            },
            host_task_context=host_task,
            span_id="coding-1",
        ),
    ]

    extracted = replay_visualization_task.extract_benchmark_trace_inputs(
        rows,
        task_kind="visualization",
        task_identity="section-001",
    )

    assert extracted["codingPayload"]["task"] == host_task


def test_extract_analysis_trace_restores_host_identity_and_rejects_context_drift() -> None:
    planner_request = {
        "currentAnalysis": {"analysisId": "analysis-001"},
        "datasets": [{"path": "datasets/current.csv"}],
    }
    model_task = {
        "task_kind": "analysis",
        "script_path": "analysis/a.py",
        "authorized_read_paths": ["datasets/current.csv"],
        "authorized_write_paths": ["analysis/a.py", "analysis/out.json"],
        "declared_output_paths": ["analysis/out.json"],
        "max_source_bytes": 100_000,
    }
    host_task = {
        **model_task,
        "task_id": "analysis-001",
        "code_mode_session_id": "analysis:analysis-001",
        "workspace_key": "workspace-001",
        "workspace_root": "/tmp/workspace-001",
    }
    rows = [
        _trace_span(
            "report-analysis-evidence-planner",
            planner_request,
            span_id="planner-1",
        ),
        _trace_span(
            "report-analysis-script-writer",
            {
                "task": model_task,
                "facts": {
                    "currentAnalysis": planner_request["currentAnalysis"],
                    "datasets": planner_request["datasets"],
                },
            },
            host_task_context=host_task,
            span_id="coding-1",
        ),
    ]

    extracted = replay_visualization_task.extract_benchmark_trace_inputs(
        rows, task_kind="analysis", task_identity="analysis-001"
    )
    assert extracted["codingPayload"]["task"] == host_task

    rows[1]["attributes"]["metadata"] = json.dumps({
        "reportingCodingTaskContext": {**host_task, "script_path": "analysis/other.py"}
    })
    with pytest.raises(ValueError, match="模型 task 与宿主 task context 不一致"):
        replay_visualization_task.extract_benchmark_trace_inputs(
            rows, task_kind="analysis", task_identity="analysis-001"
        )


def test_extract_analysis_trace_projects_signed_datasets_from_matching_coding_span() -> None:
    planner_output = {
        "requiresSupplementalEvidence": True,
        "reason": "缺少明细",
        "missingFacts": ["部门明细"],
    }
    datasets = [
        {
            "datasetId": "dataset-1",
            "path": "datasets/current.csv",
            "size": 11,
            "sha256": "a" * 64,
            "columns": ["income"],
        }
    ]
    rows = [
        _trace_span(
            "report-analysis-evidence-planner",
            {
                "currentAnalysis": {"analysisId": "analysis-001"},
                "deterministicFacts": {},
            },
            output_payload=planner_output,
            span_id="planner-1",
        ),
        _trace_span(
            "report-analysis-script-writer",
            {
                "task": {
                    "task_kind": "analysis",
                    "authorized_read_paths": ["datasets/current.csv"],
                },
                "facts": {
                    "currentAnalysis": {"analysisId": "analysis-001"},
                    "datasets": datasets,
                    "evidenceDecision": planner_output,
                },
            },
            span_id="coding-1",
        ),
    ]

    extracted = replay_visualization_task.extract_benchmark_trace_inputs(
        rows,
        task_kind="analysis",
        task_identity="analysis-001",
    )

    assert extracted["plannerRequest"]["datasets"] == datasets
    assert extracted["projection"] == {
        "kind": "analysisDatasetsFromCodingFacts",
        "plannerSpan": "planner-1",
        "codingSpan": "coding-1",
    }


@pytest.mark.parametrize(
    "coding_datasets",
    [
        [{"datasetId": "dataset-1", "path": "datasets/current.csv"}],
        None,
    ],
)
def test_extract_analysis_trace_rejects_existing_planner_datasets_from_other_task(
    coding_datasets,
) -> None:
    planner_datasets = [{"datasetId": "dataset-1", "path": "datasets/other.csv"}]
    rows = [
        _trace_span(
            "report-analysis-evidence-planner",
            {
                "currentAnalysis": {"analysisId": "analysis-001"},
                "datasets": planner_datasets,
            },
            span_id="planner-1",
        ),
        _trace_span(
            "report-analysis-script-writer",
            {
                "task": {
                    "task_kind": "analysis",
                    "authorized_read_paths": ["datasets/current.csv"],
                },
                "facts": {
                    "currentAnalysis": {"analysisId": "analysis-001"},
                    "datasets": coding_datasets,
                },
            },
            span_id="coding-1",
        ),
    ]

    with pytest.raises(ValueError, match="datasets.*不一致"):
        replay_visualization_task.extract_benchmark_trace_inputs(
            rows, task_kind="analysis", task_identity="analysis-001"
        )


@pytest.mark.parametrize("mismatch", ["analysis", "decision", "paths"])
def test_extract_analysis_trace_rejects_unproven_dataset_projection(mismatch) -> None:
    planner_analysis = {"analysisId": "analysis-001"}
    coding_analysis = dict(planner_analysis)
    planner_output = {
        "requiresSupplementalEvidence": True,
        "reason": "缺少明细",
        "missingFacts": ["部门明细"],
    }
    coding_decision = dict(planner_output)
    authorized_paths = ["datasets/current.csv"]
    if mismatch == "analysis":
        coding_analysis["step"] = "不同分析"
    elif mismatch == "decision":
        coding_decision["reason"] = "不同决策"
    else:
        authorized_paths = ["datasets/other.csv"]
    rows = [
        _trace_span(
            "report-analysis-evidence-planner",
            {"currentAnalysis": planner_analysis, "deterministicFacts": {}},
            output_payload=planner_output,
            span_id="planner-1",
        ),
        _trace_span(
            "report-analysis-script-writer",
            {
                "task": {
                    "task_kind": "analysis",
                    "authorized_read_paths": authorized_paths,
                },
                "facts": {
                    "currentAnalysis": coding_analysis,
                    "datasets": [
                        {
                            "datasetId": "dataset-1",
                            "path": "datasets/current.csv",
                            "size": 11,
                            "sha256": "a" * 64,
                        }
                    ],
                    "evidenceDecision": coding_decision,
                },
            },
            span_id="coding-1",
        ),
    ]

    with pytest.raises(ValueError, match="身份|决策|路径"):
        replay_visualization_task.extract_benchmark_trace_inputs(
            rows,
            task_kind="analysis",
            task_identity="analysis-001",
        )


@pytest.mark.anyio
async def test_frozen_benchmark_planner_projects_output_before_coding(
    monkeypatch, tmp_path
):
    manifest = SimpleNamespace(
        task_kind="analysis",
        model_dump=lambda **_kwargs: {"version": 2, "taskKind": "analysis"},
    )
    payloads = {
        "plannerRequest": {"currentAnalysis": {"analysisId": "analysis-1"}},
        "executionContext": {
            "codingPayload": {
                "task": {"task_id": "task-1", "task_kind": "analysis"},
                "facts": {"currentAnalysis": {"analysisId": "analysis-1"}},
            }
        },
        "acceptance": {},
    }
    monkeypatch.setattr(
        replay_visualization_task,
        "validate_frozen_planner_coding_bundle",
        lambda _path: (manifest, payloads),
    )
    monkeypatch.setattr(
        replay_visualization_task,
        "build_benchmark_planner_agent",
        lambda **_kwargs: (object(), object()),
    )

    class FakeExecutor:
        def __init__(self, _agent):
            pass

        async def run(self, _instruction, **kwargs):
            kwargs["model_metrics_recorder"](
                SimpleNamespace(
                    metrics=SimpleNamespace(
                        input_tokens=10,
                        output_tokens=5,
                        reasoning_tokens=3,
                    )
                ),
                1,
            )
            return LegacyAnalysisEvidenceDecision.model_validate(
                {
                    "requiresSupplementalEvidence": True,
                    "reason": "缺少明细",
                    "missingFacts": ["部门明细"],
                }
            )

    monkeypatch.setattr(
        replay_visualization_task,
        "ReportingStructuredOutputExecutor",
        FakeExecutor,
    )

    payload, metrics, saved_manifest = (
        await replay_visualization_task.run_frozen_benchmark_planner(
            tmp_path,
            variant=BenchmarkVariant.LEGACY,
            model=OpenAIChat(id="benchmark-test"),
        )
    )

    assert "codingRequirements" not in payload["facts"]
    assert len(metrics) == 1
    assert metrics[0].pop("durationMs") >= 0
    assert metrics == [
        {
            "requests": 1,
            "inputTokens": 10,
            "outputTokens": 5,
            "reasoningTokens": 3,
            "status": "completed",
            "plannerDecision": {
                "requiresSupplementalEvidence": True,
                "codingRequirementCount": 0,
            },
        }
    ]
    assert saved_manifest == {"version": 2, "taskKind": "analysis"}


@pytest.mark.anyio
async def test_frozen_benchmark_planner_records_duration_when_planner_fails(
    monkeypatch, tmp_path
):
    manifest = SimpleNamespace(
        task_kind="analysis",
        model_dump=lambda **_kwargs: {"version": 2, "taskKind": "analysis"},
    )
    payloads = {
        "plannerRequest": {"currentAnalysis": {"analysisId": "analysis-1"}},
        "executionContext": {
            "codingPayload": {
                "task": {"task_id": "task-1", "task_kind": "analysis"},
                "facts": {"currentAnalysis": {"analysisId": "analysis-1"}},
            }
        },
        "acceptance": {},
    }
    monkeypatch.setattr(
        replay_visualization_task,
        "validate_frozen_planner_coding_bundle",
        lambda _path: (manifest, payloads),
    )
    monkeypatch.setattr(
        replay_visualization_task,
        "build_benchmark_planner_agent",
        lambda **_kwargs: (object(), object()),
    )

    class FailingExecutor:
        def __init__(self, _agent):
            pass

        async def run(self, _instruction, **_kwargs):
            raise RuntimeError("planner failed")

    monkeypatch.setattr(
        replay_visualization_task,
        "ReportingStructuredOutputExecutor",
        FailingExecutor,
    )
    previous = {"requests": 1, "durationMs": 123, "status": "completed"}
    metrics: list[dict] = [previous.copy()]

    with pytest.raises(RuntimeError, match="planner failed"):
        await replay_visualization_task.run_frozen_benchmark_planner(
            tmp_path,
            variant=BenchmarkVariant.LEGACY,
            model=OpenAIChat(id="benchmark-test"),
            metrics_sink=metrics,
        )

    assert len(metrics) == 2
    assert metrics[0] == previous
    assert metrics[1]["requests"] == 0
    assert metrics[1]["status"] == "failed"
    assert metrics[1]["durationMs"] >= 0


@pytest.mark.anyio
async def test_prepare_only_writes_portable_bundle_without_loading_model_settings(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    dataset = source / "datasets/current.csv"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("income\n100\n", encoding="utf-8")
    payload_path = tmp_path / "analysis-payload.json"
    payload_path.write_text(
        json.dumps(
            {
                "task": {
                    "task_id": "analysis-001",
                    "task_kind": "analysis",
                    "code_mode_session_id": "analysis:analysis-001",
                    "workspace_key": "workspace-001",
                    "workspace_root": str(source),
                    "script_path": "analysis/supplement.py",
                    "authorized_read_paths": ["datasets/current.csv"],
                    "authorized_write_paths": [
                        "analysis/supplement.py",
                        "analysis/evidence.json",
                    ],
                    "declared_output_paths": ["analysis/evidence.json"],
                    "max_source_bytes": 100_000,
                },
                "facts": {
                    "currentAnalysis": {"analysisId": "analysis_001"},
                    "evidencePath": "analysis/evidence.json",
                },
            }
        ),
        encoding="utf-8",
    )
    bundle = tmp_path / "bundle"
    result_path = tmp_path / "prepare-result.json"
    monkeypatch.setattr(
        replay_visualization_task.AgentSettings,
        "from_environment",
        lambda: (_ for _ in ()).throw(AssertionError("prepare-only 不应加载模型配置")),
    )

    result = await replay_visualization_task.main(
        None,
        payload_path,
        "analysis",
        "medium",
        result_path,
        None,
        None,
        bundle,
    )

    assert result == 0
    prepared_payload = json.loads((bundle / "payload.json").read_text(encoding="utf-8"))
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert prepared_payload["task"]["workspace_root"] == "workspace"
    assert (bundle / "workspace/datasets/current.csv").read_text(encoding="utf-8") == (
        "income\n100\n"
    )
    assert manifest["taskKind"] == "analysis"
    assert manifest["inputs"][0]["path"] == "datasets/current.csv"
    assert len(manifest["inputs"][0]["sha256"]) == 64
    assert json.loads(result_path.read_text(encoding="utf-8"))["status"] == "prepared"

    rebundled = tmp_path / "rebundled"
    assert await replay_visualization_task.main(
        None,
        bundle / "payload.json",
        "analysis",
        "medium",
        None,
        None,
        None,
        rebundled,
    ) == 0
    assert replay_visualization_task.validate_replay_bundle(
        rebundled / "payload.json"
    )["payloadSha256"]


@pytest.mark.anyio
async def test_prepare_benchmark_from_explicit_files_does_not_load_model_settings(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    dataset = source / "datasets/current.csv"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("income\n100\n", encoding="utf-8")
    planner_request = tmp_path / "planner-request.json"
    coding_payload = tmp_path / "coding-payload.json"
    acceptance = tmp_path / "acceptance.json"
    model_config = tmp_path / "model-config.json"
    planner_request.write_text(
        json.dumps({"currentAnalysis": {"analysisId": "analysis-001"}}),
        encoding="utf-8",
    )
    coding_payload.write_text(
        json.dumps({
            "task": {
                "task_id": "analysis-001",
                "task_kind": "analysis",
                "code_mode_session_id": "analysis:analysis-001",
                "workspace_key": "workspace-001",
                "workspace_root": str(source),
                "script_path": "analysis/supplement.py",
                "authorized_read_paths": ["datasets/current.csv"],
                "authorized_write_paths": [
                    "analysis/supplement.py",
                    "analysis/evidence.json",
                ],
                "declared_output_paths": ["analysis/evidence.json"],
                "max_source_bytes": 100_000,
            },
                "facts": {
                    "currentAnalysis": {"analysisId": "analysis-001"},
                    "evidencePath": "analysis/evidence.json",
                    "datasets": [
                        {
                            "path": "datasets/current.csv",
                            "size": dataset.stat().st_size,
                            "sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
                        }
                    ],
                },
        }),
        encoding="utf-8",
    )
    acceptance.write_text("{}", encoding="utf-8")
    model_config.write_text(
        json.dumps({
            "model": "coding-model",
            "reasoningEffort": "medium",
            "reasoningSummary": "auto",
            "enableThinkingLocation": "top_level",
            "enableThinking": True,
            "maxOutputTokens": None,
            "parallelToolCalls": True,
            "toolChoice": "auto",
        }),
        encoding="utf-8",
    )
    bundle = tmp_path / "benchmark"
    result_path = tmp_path / "prepare-benchmark-result.json"
    monkeypatch.setattr(
        replay_visualization_task.AgentSettings,
        "from_environment",
        lambda: (_ for _ in ()).throw(AssertionError("prepare 不应加载模型配置")),
    )

    result = await replay_visualization_task.main(
        None,
        None,
        "analysis",
        "medium",
        result_path,
        None,
        None,
        benchmark_prepare_dir=bundle,
        planner_request_path=planner_request,
        coding_payload_path=coding_payload,
        acceptance_path=acceptance,
        model_config_path=model_config,
    )

    assert result == 0
    assert json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))[
        "version"
    ] == 2
    assert json.loads(result_path.read_text(encoding="utf-8"))["status"] == "prepared"


@pytest.mark.anyio
async def test_extract_benchmark_from_trace_is_offline(monkeypatch, tmp_path):
    dataset = tmp_path / "datasets/current.csv"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("income\n100\n", encoding="utf-8")
    datasets = [
        {
            "path": "datasets/current.csv",
            "size": dataset.stat().st_size,
            "sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        }
    ]
    acceptance = tmp_path / "acceptance.json"
    model_config = tmp_path / "model-config.json"
    acceptance.write_text("{}", encoding="utf-8")
    model_config.write_text(
        json.dumps({
            "model": "coding-model",
            "reasoningEffort": "medium",
            "reasoningSummary": "auto",
            "enableThinkingLocation": "omitted",
            "enableThinking": None,
            "maxOutputTokens": None,
            "parallelToolCalls": True,
            "toolChoice": "auto",
        }),
        encoding="utf-8",
    )
    rows = [
        _trace_span(
            "report-analysis-evidence-planner",
            {
                "currentAnalysis": {"analysisId": "analysis-001"},
                "deterministicFacts": {},
                "datasets": datasets,
            },
            span_id="planner-1",
        ),
        _trace_span(
            "report-analysis-script-writer",
            {
                "task": {
                    "task_id": "analysis-001",
                    "task_kind": "analysis",
                    "code_mode_session_id": "analysis:analysis-001",
                    "workspace_key": "workspace-001",
                    "workspace_root": str(tmp_path),
                    "script_path": "analysis/supplement.py",
                    "authorized_read_paths": ["datasets/current.csv"],
                    "authorized_write_paths": [
                        "analysis/supplement.py",
                        "analysis/evidence.json",
                    ],
                    "declared_output_paths": ["analysis/evidence.json"],
                    "max_source_bytes": 100_000,
                },
                "facts": {
                    "currentAnalysis": {"analysisId": "analysis-001"},
                    "datasets": datasets,
                },
            },
            span_id="coding-1",
        ),
    ]
    monkeypatch.setattr(replay_visualization_task, "load_trace_spans", lambda _id: rows)
    output = tmp_path / "extract.json"
    result = await replay_visualization_task.main(
        None,
        None,
        "analysis",
        "medium",
        output,
        None,
        None,
        trace_id="trace-1",
        trace_identity="analysis-001",
        benchmark_extract_dir=tmp_path / "bundle",
        acceptance_path=acceptance,
        model_config_path=model_config,
    )

    assert result == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "extracted"
    assert payload["sourceSpans"] == {"planner": "planner-1", "coding": "coding-1"}


def test_validate_replay_bundle_rejects_authorized_input_drift(tmp_path):
    source = tmp_path / "source"
    dataset = source / "datasets/current.csv"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("income\n100\n", encoding="utf-8")
    payload = {
        "task": {
            "task_id": "analysis-001",
            "task_kind": "analysis",
            "code_mode_session_id": "analysis:analysis-001",
            "workspace_key": "workspace-001",
            "workspace_root": str(source),
            "script_path": "analysis/supplement.py",
            "authorized_read_paths": ["datasets/current.csv"],
            "authorized_write_paths": [
                "analysis/supplement.py",
                "analysis/evidence.json",
            ],
            "declared_output_paths": ["analysis/evidence.json"],
            "max_source_bytes": 100_000,
        },
        "facts": {
            "currentAnalysis": {"analysisId": "analysis_001"},
            "evidencePath": "analysis/evidence.json",
        },
    }
    bundle = tmp_path / "bundle"
    replay_visualization_task.prepare_replay_bundle(payload, bundle, None)

    assert replay_visualization_task.validate_replay_bundle(bundle / "payload.json")[
        "taskKind"
    ] == "analysis"
    (bundle / "workspace/datasets/current.csv").write_text(
        "income\n999\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="身份不一致"):
        replay_visualization_task.validate_replay_bundle(bundle / "payload.json")
