import hashlib
import json
from types import MappingProxyType

import pytest
from agno.models.openai import OpenAIChat
from pydantic import BaseModel

from smart_reporting.reporting.agent import create_reporting_generator_agent
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.benchmark_bundle import (
    BenchmarkModelConfig,
    _validate_required_charts,
    prepare_frozen_planner_coding_bundle,
    validate_frozen_planner_coding_bundle,
)
from smart_reporting.reporting.workflow.benchmark_execution import (
    build_benchmark_planner_agent,
    prepare_benchmark_coding_payload,
)
from smart_reporting.reporting.workflow.benchmark_variants import (
    BenchmarkPlannerSpec,
    BenchmarkProjection,
    BenchmarkVariant,
    LegacyAnalysisEvidenceDecision,
    LegacyVisualizationPlanDraft,
    build_benchmark_planner_spec,
)
from smart_reporting.reporting.workflow.runtime.analysis import (
    _validate_analysis_benchmark_planner,
    _validate_visualization_benchmark_planner,
    adapt_legacy_visualization_plan,
    visualization_coding_plan,
)
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisEvidenceDecision,
)
from smart_reporting.reporting.workflow.runtime.base import (
    _ANALYSIS_CODE_COMMON_INSTRUCTIONS,
    _ANALYSIS_EVIDENCE_CANDIDATE_INSTRUCTIONS,
    _ANALYSIS_EVIDENCE_LEGACY_INSTRUCTIONS,
    ThinkingPolicyConfig,
    _ReportWorkflowRuntimeBase,
)
from smart_reporting.reporting.workflow.runtime.phase_models import VisualizationPlanDraft
from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
    _validate_visualization_plan_bindings,
)


def test_analysis_coding_instructions_reuse_signed_plan_without_reexploration() -> None:
    text = "\n".join(_ANALYSIS_CODE_COMMON_INSTRUCTIONS)
    assert "同一 datasets[] 项声明的 columns" in text
    assert "为了验证假设读取未签发数据" in text


def test_legacy_projection_keeps_existing_facts_but_excludes_r7_fields() -> None:
    projection = BenchmarkProjection.for_variant(BenchmarkVariant.LEGACY)

    assert projection.variant is BenchmarkVariant.LEGACY
    assert projection.include_analysis_requirements is False
    assert projection.include_visual_bindings is False


def test_candidate_projection_enables_both_r7_field_groups() -> None:
    projection = BenchmarkProjection.for_variant(BenchmarkVariant.CANDIDATE)

    assert projection.variant is BenchmarkVariant.CANDIDATE
    assert projection.include_analysis_requirements is True
    assert projection.include_visual_bindings is True


@pytest.mark.parametrize("value", ["", "baseline", "legacy-candidate"])
def test_variant_parser_rejects_unknown_values(value: str) -> None:
    with pytest.raises(ValueError, match="legacy 或 candidate"):
        BenchmarkVariant.parse(value)


def test_projection_rejects_non_variant_values() -> None:
    with pytest.raises(TypeError, match="BenchmarkVariant"):
        BenchmarkProjection.for_variant("candidate")  # type: ignore[arg-type]


class _PlannerOutput(BaseModel):
    value: str


def _legacy_visualization_plan() -> LegacyVisualizationPlanDraft:
    return LegacyVisualizationPlanDraft.model_validate(
        {
            "charts": [
                {
                    "chartId": "chart-1",
                    "sourcePath": "charts/chart-1.png",
                    "title": "收入趋势",
                    "altText": "收入趋势",
                    "citationIds": ["citation-1"],
                    "metricCodes": ["income"],
                    "currentPeriod": "2025",
                    "sourceDatasetId": "dataset-1",
                    "aggregationGrain": "month",
                }
            ],
            "warnings": [],
        }
    )


def _write_frozen_bundle(
    tmp_path,
    *,
    embed_variant: bool = False,
    required_charts=None,
    declared_outputs=("charts/chart.png",),
) -> None:
    planner_request = {"sectionCode": "section-1", **({"variant": "legacy"} if embed_variant else {})}
    if required_charts is not None:
        planner_request["requiredCharts"] = required_charts
    files = {
        "planner-request.json": planner_request,
        "execution-context.json": {
            "taskKind": "visualization",
            "taskId": "task-1",
            "scriptPath": "charts/charts.py",
            "codingPayload": {
                "task": {
                    "task_id": "task-1",
                    "task_kind": "visualization",
                    "code_mode_session_id": "visualization:task-1",
                    "workspace_key": "workspace-1",
                    "workspace_root": "workspace",
                    "script_path": "charts/charts.py",
                    "authorized_read_paths": ["facts.json"],
                    "authorized_write_paths": ["charts/charts.py", *declared_outputs],
                    "declared_output_paths": list(declared_outputs),
                    "max_source_bytes": 100_000,
                },
                "facts": {"visualizationFacts": []},
            },
        },
        "acceptance.json": {"charts": {"chart-1": {"required": True}}},
        "workspace/facts.json": {"analysisId": "analysis-1"},
    }
    identities = {}
    for path, payload in files.items():
        content = (json.dumps(payload, ensure_ascii=False) + "\n").encode()
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        identities[path] = {
            "path": path,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    manifest = {
        "version": 2,
        "taskKind": "visualization",
        "plannerRequest": identities["planner-request.json"],
        "executionContext": identities["execution-context.json"],
        "acceptance": identities["acceptance.json"],
        "inputs": [identities["workspace/facts.json"]],
        "modelConfig": {
            "model": "coding-model",
            "reasoningEffort": "medium",
            "reasoningSummary": "auto",
            "enableThinkingLocation": "top_level",
            "enableThinking": True,
            "maxOutputTokens": 65536,
            "parallelToolCalls": True,
            "toolChoice": "auto",
        },
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_planner_spec_captures_variant_before_provider_construction() -> None:
    spec = BenchmarkPlannerSpec(
        task_kind="analysis",
        variant=BenchmarkVariant.LEGACY,
        output_schema=_PlannerOutput,
        instructions=("只返回旧版规划字段",),
        project_coding_facts=lambda payload: payload,
    )

    assert spec.variant is BenchmarkVariant.LEGACY
    assert spec.output_schema is _PlannerOutput
    assert spec.project_coding_facts({"analysisId": "a-1"}) == {"analysisId": "a-1"}


def test_planner_spec_rejects_production_runtime_shape_errors() -> None:
    with pytest.raises(ValueError, match="task_kind"):
        BenchmarkPlannerSpec(
            task_kind="report",  # type: ignore[arg-type]
            variant=BenchmarkVariant.CANDIDATE,
            output_schema=_PlannerOutput,
            instructions=("ok",),
            project_coding_facts=lambda payload: payload,
        )


def test_builder_selects_schema_and_projection_before_planner_creation() -> None:
    def legacy_projection(payload):
        return {**payload, "variant": "legacy"}

    def candidate_projection(payload):
        return {**payload, "variant": "candidate"}

    legacy = build_benchmark_planner_spec(
        task_kind="visualization",
        variant=BenchmarkVariant.LEGACY,
        legacy_output_schema=_PlannerOutput,
        candidate_output_schema=BaseModel,
        legacy_instructions=("legacy",),
        candidate_instructions=("candidate",),
        legacy_project_coding_facts=legacy_projection,
        candidate_project_coding_facts=candidate_projection,
    )
    candidate = build_benchmark_planner_spec(
        task_kind="visualization",
        variant=BenchmarkVariant.CANDIDATE,
        legacy_output_schema=_PlannerOutput,
        candidate_output_schema=_PlannerOutput,
        legacy_instructions=("legacy",),
        candidate_instructions=("candidate",),
        legacy_project_coding_facts=legacy_projection,
        candidate_project_coding_facts=candidate_projection,
    )

    assert legacy.variant is BenchmarkVariant.LEGACY
    assert legacy.instructions == ("legacy",)
    assert legacy.project_coding_facts({})["variant"] == "legacy"
    assert candidate.variant is BenchmarkVariant.CANDIDATE
    assert candidate.instructions == ("candidate",)
    assert candidate.project_coding_facts({})["variant"] == "candidate"


def test_legacy_planner_schemas_do_not_accept_r7_fields() -> None:
    decision = LegacyAnalysisEvidenceDecision.model_validate(
        {
            "requiresSupplementalEvidence": True,
            "reason": "缺少明细",
            "missingFacts": ["部门明细"],
        }
    )
    plan = _legacy_visualization_plan()

    assert decision.model_dump(by_alias=True).keys() == {
        "requiresSupplementalEvidence",
        "reason",
        "missingFacts",
    }
    chart_payload = plan.charts[0].model_dump(mode="json", by_alias=True)
    assert "visualForm" not in chart_payload
    assert "dataBindings" not in chart_payload
    with pytest.raises(ValueError):
        LegacyAnalysisEvidenceDecision.model_validate(
            {
                "requiresSupplementalEvidence": True,
                "reason": "缺少明细",
                "missingFacts": ["部门明细"],
                "codingRequirements": [],
            }
        )


def test_benchmark_planner_agent_forwards_spec_before_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_planning_agent(
        planner, agent_id, output_schema, *, thinking_policy, stage_instructions
    ):
        captured.update(
            {
                "planner": planner,
                "agent_id": agent_id,
                "output_schema": output_schema,
                "thinking_policy": thinking_policy,
                "stage_instructions": stage_instructions,
            }
        )
        return "benchmark-agent"

    monkeypatch.setattr(
        _ReportWorkflowRuntimeBase,
        "_planning_agent",
        staticmethod(fake_planning_agent),
    )
    spec = BenchmarkPlannerSpec(
        task_kind="analysis",
        variant=BenchmarkVariant.LEGACY,
        output_schema=LegacyAnalysisEvidenceDecision,
        instructions=("legacy evidence",),
        project_coding_facts=lambda payload: payload,
    )
    policy = ThinkingPolicyConfig(
        operation="analysis_evidence",
        thinking_enabled=True,
        configured_budget_cap=1024,
    )

    result = _ReportWorkflowRuntimeBase._benchmark_planning_agent(
        object(), spec, thinking_policy=policy
    )

    assert result == "benchmark-agent"
    assert captured["agent_id"] == "benchmark-analysis-legacy-planner"
    assert captured["output_schema"] is LegacyAnalysisEvidenceDecision
    assert captured["stage_instructions"] == ("legacy evidence",)


def test_analysis_legacy_variant_requires_pre_request_planner_and_schema() -> None:
    legacy = BenchmarkProjection.for_variant(BenchmarkVariant.LEGACY)

    with pytest.raises(ReportingError, match="旧 planner 与旧 schema"):
        _validate_analysis_benchmark_planner(legacy, None, _PlannerOutput)

    _validate_analysis_benchmark_planner(
        legacy,
        object(),
        LegacyAnalysisEvidenceDecision,
    )


def test_visualization_generator_only_adds_r7_instructions_to_candidate() -> None:
    model = OpenAIChat(id="benchmark-test")
    legacy = create_reporting_generator_agent(
        model=model,
        output_schema=LegacyVisualizationPlanDraft,
        name="legacy",
    )
    candidate = create_reporting_generator_agent(
        model=model,
        output_schema=VisualizationPlanDraft,
        name="candidate",
    )
    legacy_text = "\n".join(legacy.instructions)
    candidate_text = "\n".join(candidate.instructions)

    assert "sourceDatasetId" in legacy_text
    assert "renderer=plotly" in legacy_text
    assert "visualForm" not in legacy_text
    assert "dataBindings" not in legacy_text
    assert "visualForm" in candidate_text
    assert "dataBindings" in candidate_text


def test_analysis_planner_instructions_only_add_candidate_requirements() -> None:
    legacy_text = "\n".join(_ANALYSIS_EVIDENCE_LEGACY_INSTRUCTIONS)
    candidate_text = "\n".join(_ANALYSIS_EVIDENCE_CANDIDATE_INSTRUCTIONS)

    assert "currentAnalysis" in legacy_text
    assert "deterministicFacts" in legacy_text
    assert "codingRequirements" not in legacy_text
    assert "codingRequirements" in candidate_text

    agent = create_reporting_generator_agent(
        model=OpenAIChat(id="benchmark-test"),
        output_schema=LegacyAnalysisEvidenceDecision,
        name="analysis-legacy",
        stage_instructions=_ANALYSIS_EVIDENCE_LEGACY_INSTRUCTIONS,
    )
    assert tuple(agent.instructions[-3:]) == _ANALYSIS_EVIDENCE_LEGACY_INSTRUCTIONS


def test_visualization_legacy_variant_requires_pre_request_adapter() -> None:
    legacy = BenchmarkProjection.for_variant(BenchmarkVariant.LEGACY)

    with pytest.raises(ReportingError, match="旧 planner、旧 schema 和 adapter"):
        _validate_visualization_benchmark_planner(
            legacy,
            object(),
            LegacyVisualizationPlanDraft,
            None,
        )

    _validate_visualization_benchmark_planner(
        legacy,
        object(),
        LegacyVisualizationPlanDraft,
        lambda _plan, _request: None,  # type: ignore[arg-type,return-value]
    )


def test_legacy_visualization_adapter_validates_but_hides_frozen_r7_decisions() -> None:
    adapted = adapt_legacy_visualization_plan(
        _legacy_visualization_plan(),
        {
            "chart-1": {
                "visualForm": "按月折线图",
                "dataBindings": [
                    {
                        "analysisId": "analysis-1",
                        "factPath": "facts/analysis-1.json",
                        "dataPath": "metrics[0].periodValues",
                        "fields": ["period", "value"],
                        "role": "月度趋势",
                    }
                ],
            }
        },
    )

    projected = visualization_coding_plan(
        adapted,
        benchmark_projection=BenchmarkProjection.for_variant(BenchmarkVariant.LEGACY),
    )

    assert adapted.charts[0].data_bindings[0].fact_path == "facts/analysis-1.json"
    assert "visualForm" not in projected["charts"][0]
    assert "dataBindings" not in projected["charts"][0]


def test_legacy_visualization_adapter_rejects_unfrozen_chart_identity() -> None:
    with pytest.raises(ReportingError, match="验收身份不一致"):
        adapt_legacy_visualization_plan(_legacy_visualization_plan(), {})


def test_adapted_legacy_visualization_binding_mismatch_warns_without_raising() -> None:
    # 2026-09-23 契约变更（用户拍板）：图表绑定与签发事实描述的语义偏差从
    # report_phase_contract_invalid 硬错误改为 loguru 软告警（对齐 AGENTS.md
    # "语义业务校验只需要软告警"）；文件访问授权仍由执行层 AST 字面路径白名单硬校验。
    from loguru import logger

    adapted = adapt_legacy_visualization_plan(
        _legacy_visualization_plan(),
        {
            "chart-1": {
                "visualForm": "按月折线图",
                "dataBindings": [
                    {
                        "analysisId": "analysis-1",
                        "factPath": "facts/not-authorized.json",
                        "dataPath": "metrics[0].periodValues",
                        "fields": ["period", "value"],
                        "role": "月度趋势",
                    }
                ],
            }
        },
    )

    records = []
    sink = logger.add(lambda message: records.append(message.record), level="WARNING")
    try:
        _validate_visualization_plan_bindings(
            adapted,
            {
                "visualizationFacts": [
                    {
                        "analysisId": "analysis-1",
                        "factFile": {"path": "facts/analysis-1.json"},
                        "dataDescriptors": [
                            {
                                "dataPath": "metrics[0].periodValues",
                                "fields": ["period", "value"],
                            }
                        ],
                    }
                ]
            },
        )
    finally:
        logger.remove(sink)

    events = [r for r in records if "report_visualization_binding_mismatch" in r["message"]]
    assert len(events) == 1
    assert events[0]["level"].name == "WARNING"
    details = events[0]["message"]
    assert "facts/not-authorized.json" in details
    assert "chart-1" in details


def test_frozen_planner_coding_bundle_keeps_variant_outside_input(tmp_path) -> None:
    _write_frozen_bundle(tmp_path)

    manifest, payloads = validate_frozen_planner_coding_bundle(tmp_path)

    assert manifest.task_kind == "visualization"
    assert manifest.model_config_snapshot.parallel_tool_calls is True
    assert payloads["executionContext"]["scriptPath"] == "charts/charts.py"


def test_frozen_planner_coding_bundle_rejects_embedded_variant(tmp_path) -> None:
    _write_frozen_bundle(tmp_path, embed_variant=True)

    with pytest.raises(ValueError, match="不得内嵌"):
        validate_frozen_planner_coding_bundle(tmp_path)


def test_frozen_planner_coding_bundle_rejects_changed_input(tmp_path) -> None:
    _write_frozen_bundle(tmp_path)
    (tmp_path / "workspace/facts.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="身份不一致"):
        validate_frozen_planner_coding_bundle(tmp_path)


def test_frozen_bundle_accepts_required_charts_consistent_with_declared(tmp_path) -> None:
    _write_frozen_bundle(
        tmp_path,
        required_charts=[
            {"chartId": "chart", "sourcePath": "charts/chart.png", "interactivePath": None}
        ],
    )

    manifest, payloads = validate_frozen_planner_coding_bundle(tmp_path)

    assert payloads["plannerRequest"]["requiredCharts"][0]["chartId"] == "chart"
    assert manifest.task_kind == "visualization"


def test_frozen_bundle_accepts_required_charts_with_interactive_path(tmp_path) -> None:
    _write_frozen_bundle(
        tmp_path,
        declared_outputs=["charts/chart.png", "charts/chart.plotly.json"],
        required_charts=[
            {
                "chartId": "chart",
                "sourcePath": "charts/chart.png",
                "interactivePath": "charts/chart.plotly.json",
            }
        ],
    )

    _manifest, payloads = validate_frozen_planner_coding_bundle(tmp_path)

    assert payloads["plannerRequest"]["requiredCharts"][0]["interactivePath"] == (
        "charts/chart.plotly.json"
    )


def test_frozen_bundle_rejects_interactive_path_missing_from_declared(tmp_path) -> None:
    _write_frozen_bundle(
        tmp_path,
        required_charts=[
            {
                "chartId": "chart",
                "sourcePath": "charts/chart.png",
                "interactivePath": "charts/chart.plotly.json",
            }
        ],
    )

    with pytest.raises(ValueError, match="declared_output_paths 不一致"):
        validate_frozen_planner_coding_bundle(tmp_path)


def test_required_charts_rejected_for_non_visualization_task() -> None:
    with pytest.raises(ValueError, match="仅适用于 visualization"):
        _validate_required_charts(
            {"requiredCharts": [{"chartId": "chart", "sourcePath": "charts/chart.png"}]},
            {"task_kind": "analysis", "declared_output_paths": ["charts/chart.png"]},
        )


@pytest.mark.parametrize(
    ("required_charts", "match"),
    [
        ("not-a-list", "非空列表"),
        ([{"chartId": "chart"}], "sourcePath"),
        ([{"sourcePath": "charts/chart.png"}], "chartId"),
        (
            [
                {"chartId": "dup", "sourcePath": "charts/chart.png"},
                {"chartId": "dup", "sourcePath": "charts/chart.png"},
            ],
            "不能重复",
        ),
        (
            [{"chartId": "chart", "sourcePath": "charts/renamed.png"}],
            "declared_output_paths 不一致",
        ),
        (
            [{"chartId": "chart", "sourcePath": "charts/chart.png", "interactivePath": 1}],
            "interactivePath",
        ),
        (
            [{"chartId": "chart", "sourcePath": "charts/chart.png", "interactivePath": ""}],
            "空字符串",
        ),
        (
            [
                {"chartId": "chart-a", "sourcePath": "charts/chart.png"},
                {
                    "chartId": "chart-b",
                    "sourcePath": "charts/chart.png",
                    "interactivePath": "charts/other.png",
                },
            ],
            "不能重复",
        ),
    ],
)
def test_frozen_bundle_rejects_invalid_required_charts(tmp_path, required_charts, match) -> None:
    _write_frozen_bundle(tmp_path, required_charts=required_charts)

    with pytest.raises(ValueError, match=match):
        validate_frozen_planner_coding_bundle(tmp_path)


def test_frozen_bundle_rejects_authorized_input_identity_mismatch(tmp_path) -> None:
    _write_frozen_bundle(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["inputs"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="授权输入集合"):
        validate_frozen_planner_coding_bundle(tmp_path)


def test_prepare_frozen_planner_coding_bundle_round_trip(tmp_path) -> None:
    source = tmp_path / "source"
    dataset = source / "datasets/current.csv"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("income\n100\n", encoding="utf-8")
    bundle = tmp_path / "bundle"
    coding_payload = {
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
                    "datasetId": "dataset-1",
                    "path": "datasets/current.csv",
                    "size": len(b"income\n100\n"),
                    "sha256": hashlib.sha256(b"income\n100\n").hexdigest(),
                }
            ],
        },
    }
    model_config = BenchmarkModelConfig.model_validate({
        "model": "coding-model",
        "reasoningEffort": "medium",
        "reasoningSummary": "auto",
        "enableThinkingLocation": "top_level",
        "enableThinking": True,
        "maxOutputTokens": None,
        "parallelToolCalls": True,
        "toolChoice": "auto",
    })

    prepared = prepare_frozen_planner_coding_bundle(
        bundle,
        task_kind="analysis",
        planner_request={"currentAnalysis": {"analysisId": "analysis-001"}},
        coding_payload=coding_payload,
        acceptance={},
        model_config=model_config,
    )
    manifest, payloads = validate_frozen_planner_coding_bundle(bundle)

    assert prepared == manifest
    assert payloads["executionContext"]["codingPayload"]["task"][
        "workspace_root"
    ] == "workspace"
    assert manifest.inputs[0].path == "workspace/datasets/current.csv"
    assert (bundle / manifest.inputs[0].path).read_text(encoding="utf-8") == (
        "income\n100\n"
    )


@pytest.mark.parametrize(
    "datasets, authorized_paths",
    [
        ([], ["datasets/current.csv"]),
        (
            [
                {
                    "path": "datasets/current.csv",
                    "size": 11,
                    "sha256": "a" * 64,
                },
                {
                    "path": "datasets/current.csv",
                    "size": 11,
                    "sha256": "a" * 64,
                },
            ],
            ["datasets/current.csv"],
        ),
        (
            [
                {
                    "path": "datasets/current.csv",
                    "size": 11,
                    "sha256": "a" * 64,
                }
            ],
            ["datasets/other.csv"],
        ),
    ],
)
def test_prepare_analysis_bundle_rejects_unbound_dataset_paths(
    tmp_path, datasets, authorized_paths
) -> None:
    source = tmp_path / "source"
    for relative_path in authorized_paths:
        target = source / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("income\n100\n", encoding="utf-8")
    coding_payload = {
        "task": {
            "task_id": "analysis-001",
            "task_kind": "analysis",
            "code_mode_session_id": "analysis:analysis-001",
            "workspace_key": "workspace-001",
            "workspace_root": str(source),
            "script_path": "analysis/supplement.py",
            "authorized_read_paths": authorized_paths,
            "authorized_write_paths": [
                "analysis/supplement.py",
                "analysis/evidence.json",
            ],
            "declared_output_paths": ["analysis/evidence.json"],
            "max_source_bytes": 100_000,
        },
        "facts": {"datasets": datasets},
    }

    with pytest.raises(ValueError, match="datasets.*路径"):
        prepare_frozen_planner_coding_bundle(
            tmp_path / "bundle",
            task_kind="analysis",
            planner_request={"currentAnalysis": {"analysisId": "analysis-001"}},
            coding_payload=coding_payload,
            acceptance={},
            model_config=BenchmarkModelConfig.model_validate(
                {
                    "model": "coding-model",
                    "reasoningEffort": "medium",
                    "reasoningSummary": "auto",
                    "enableThinkingLocation": "omitted",
                    "enableThinking": None,
                    "maxOutputTokens": None,
                    "parallelToolCalls": True,
                    "toolChoice": "auto",
                }
            ),
        )


@pytest.mark.parametrize("dataset_update", [{"size": 12}, {"sha256": "b" * 64}])
def test_prepare_analysis_bundle_rejects_dataset_identity_mismatch(
    tmp_path, dataset_update
) -> None:
    source = tmp_path / "source"
    dataset = source / "datasets/current.csv"
    dataset.parent.mkdir(parents=True)
    content = b"income\n100\n"
    dataset.write_bytes(content)
    declared_dataset = {
        "path": "datasets/current.csv",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        **dataset_update,
    }
    coding_payload = {
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
        "facts": {"datasets": [declared_dataset]},
    }

    with pytest.raises(ValueError, match="dataset.*身份"):
        prepare_frozen_planner_coding_bundle(
            tmp_path / "bundle",
            task_kind="analysis",
            planner_request={"currentAnalysis": {"analysisId": "analysis-001"}},
            coding_payload=coding_payload,
            acceptance={},
            model_config=BenchmarkModelConfig.model_validate(
                {
                    "model": "coding-model",
                    "reasoningEffort": "medium",
                    "reasoningSummary": "auto",
                    "enableThinkingLocation": "omitted",
                    "enableThinking": None,
                    "maxOutputTokens": None,
                    "parallelToolCalls": True,
                    "toolChoice": "auto",
                }
            ),
        )


@pytest.mark.parametrize(
    "dataset_update",
    [{"size": 12}, {"sha256": "b" * 64}],
)
def test_validate_analysis_bundle_rejects_dataset_identity_mismatch(
    tmp_path, dataset_update
) -> None:
    source = tmp_path / "source"
    dataset = source / "datasets/current.csv"
    dataset.parent.mkdir(parents=True)
    content = b"income\n100\n"
    dataset.write_bytes(content)
    bundle = tmp_path / "bundle"
    coding_payload = {
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
            "datasets": [
                {
                    "path": "datasets/current.csv",
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            ]
        },
    }
    model_config = BenchmarkModelConfig.model_validate(
        {
            "model": "coding-model",
            "reasoningEffort": "medium",
            "reasoningSummary": "auto",
            "enableThinkingLocation": "omitted",
            "enableThinking": None,
            "maxOutputTokens": None,
            "parallelToolCalls": True,
            "toolChoice": "auto",
        }
    )
    prepare_frozen_planner_coding_bundle(
        bundle,
        task_kind="analysis",
        planner_request={"currentAnalysis": {"analysisId": "analysis-001"}},
        coding_payload=coding_payload,
        acceptance={},
        model_config=model_config,
    )
    context_path = bundle / "execution-context.json"
    context = json.loads(context_path.read_text(encoding="utf-8"))
    context["codingPayload"]["facts"]["datasets"][0].update(dataset_update)
    context_content = (json.dumps(context, ensure_ascii=False) + "\n").encode()
    context_path.write_bytes(context_content)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["executionContext"].update(
        {
            "size": len(context_content),
            "sha256": hashlib.sha256(context_content).hexdigest(),
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="dataset.*身份"):
        validate_frozen_planner_coding_bundle(bundle)


def test_prepare_frozen_bundle_rejects_planner_output_in_base_facts(tmp_path) -> None:
    model_config = BenchmarkModelConfig.model_validate({
        "model": "coding-model",
        "reasoningEffort": "medium",
        "reasoningSummary": "auto",
        "enableThinkingLocation": "omitted",
        "enableThinking": None,
        "maxOutputTokens": None,
        "parallelToolCalls": True,
        "toolChoice": "auto",
    })
    coding_payload = {
        "task": {
            "task_id": "analysis-001",
            "task_kind": "analysis",
            "code_mode_session_id": "analysis:analysis-001",
            "workspace_key": "workspace-001",
            "workspace_root": str(tmp_path),
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
            "codingRequirements": [],
        },
    }

    with pytest.raises(ValueError, match="planner 产物"):
        prepare_frozen_planner_coding_bundle(
            tmp_path / "bundle",
            task_kind="analysis",
            planner_request={"currentAnalysis": {"analysisId": "analysis-001"}},
            coding_payload=coding_payload,
            acceptance={},
            model_config=model_config,
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"toolChoice": "required"},
        {"reasoningEffort": "turbo"},
        {"reasoningSummary": "verbose"},
        {"reasoningEffort": "medium", "enableThinking": False},
        {"reasoningEffort": "none", "enableThinking": True},
    ],
)
def test_benchmark_model_config_rejects_unprojectable_wire_values(updates) -> None:
    payload = {
        "model": "coding-model",
        "reasoningEffort": "medium",
        "reasoningSummary": "auto",
        "enableThinkingLocation": "top_level",
        "enableThinking": True,
        "maxOutputTokens": None,
        "parallelToolCalls": True,
        "toolChoice": "auto",
    }
    payload.update(updates)

    with pytest.raises(ValueError):
        BenchmarkModelConfig.model_validate(payload)


def test_analysis_benchmark_projection_changes_only_candidate_requirements() -> None:
    execution = {
        "codingPayload": {
            "task": {"task_kind": "analysis"},
            "facts": {"currentAnalysis": {"analysisId": "analysis-1"}},
        }
    }
    legacy = prepare_benchmark_coding_payload(
        task_kind="analysis",
        variant=BenchmarkVariant.LEGACY,
        execution_context=execution,
        acceptance={},
        planner_output=LegacyAnalysisEvidenceDecision.model_validate(
            {
                "requiresSupplementalEvidence": True,
                "reason": "缺少明细",
                "missingFacts": ["部门明细"],
            }
        ),
    )
    candidate = prepare_benchmark_coding_payload(
        task_kind="analysis",
        variant=BenchmarkVariant.CANDIDATE,
        execution_context=execution,
        acceptance={},
        planner_output=AnalysisEvidenceDecision.model_validate(
            {
                "requiresSupplementalEvidence": True,
                "reason": "缺少明细",
                "missingFacts": ["部门明细"],
                "codingRequirements": [
                    {
                        "datasetId": "dataset-1",
                        "fields": ["department", "income"],
                        "calculation": "按部门汇总收入",
                        "outputName": "department_income",
                    }
                ],
            }
        ),
    )

    assert "codingRequirements" not in legacy["facts"]
    assert legacy["facts"]["evidenceDecision"]["missingFacts"] == ["部门明细"]
    assert candidate["facts"]["codingRequirements"][0]["datasetId"] == "dataset-1"
    assert "codingRequirements" not in execution["codingPayload"]["facts"]


def test_analysis_benchmark_rejects_planner_that_does_not_require_coding() -> None:
    execution = {
        "codingPayload": {
            "task": {"task_kind": "analysis"},
            "facts": {"currentAnalysis": {"analysisId": "analysis-1"}},
        }
    }
    decision = LegacyAnalysisEvidenceDecision.model_validate(
        {
            "requiresSupplementalEvidence": False,
            "reason": "确定性事实已覆盖",
            "missingFacts": [],
        }
    )

    with pytest.raises(ReportingError, match="无需 Coding"):
        prepare_benchmark_coding_payload(
            task_kind="analysis",
            variant=BenchmarkVariant.LEGACY,
            execution_context=execution,
            acceptance={},
            planner_output=decision,
        )


def test_visualization_benchmark_reports_output_path_differences() -> None:
    plan_payload = _legacy_visualization_plan().model_dump(mode="json", by_alias=True)
    plan_payload["charts"][0].update({
        "visualForm": "按月折线图",
        "dataBindings": [{
            "analysisId": "analysis-1",
            "factPath": "facts/analysis-1.json",
            "dataPath": "metrics[0].periodValues",
            "fields": ["period", "value"],
            "role": "月度趋势",
        }],
    })
    execution = {"codingPayload": {
        "task": {
            "task_kind": "visualization",
            "declared_output_paths": ["charts/z.png", "charts/a.png"],
        },
        "facts": {"visualizationFacts": []},
    }}

    with pytest.raises(ReportingError, match="图表输出路径") as caught:
        prepare_benchmark_coding_payload(
            task_kind="visualization",
            variant=BenchmarkVariant.CANDIDATE,
            execution_context=execution,
            acceptance={},
            planner_output=VisualizationPlanDraft.model_validate(plan_payload),
        )

    assert caught.value.details == {
        "missingPaths": ["charts/a.png", "charts/z.png"],
        "unexpectedPaths": ["charts/chart-1.png"],
    }
    assert execution["codingPayload"]["task"]["declared_output_paths"] == [
        "charts/z.png", "charts/a.png",
    ]


def _candidate_visualization_plan_payload() -> dict:
    plan_payload = _legacy_visualization_plan().model_dump(mode="json", by_alias=True)
    plan_payload["charts"][0].update({
        "visualForm": "按月折线图",
        "dataBindings": [{
            "analysisId": "analysis-1",
            "factPath": "facts/analysis-1.json",
            "dataPath": "metrics[0].periodValues",
            "fields": ["period", "value"],
            "role": "月度趋势",
        }],
    })
    return plan_payload


def _visualization_execution(declared=("charts/chart-1.png",)) -> dict:
    return {"codingPayload": {
        "task": {
            "task_kind": "visualization",
            "declared_output_paths": list(declared),
        },
        "facts": {"visualizationFacts": []},
    }}


def test_visualization_benchmark_accepts_plan_matching_required_charts() -> None:
    plan = VisualizationPlanDraft.model_validate(_candidate_visualization_plan_payload())
    planner_request = {
        "requiredCharts": [
            {"chartId": "chart-1", "sourcePath": "charts/chart-1.png", "interactivePath": None}
        ],
    }

    payload = prepare_benchmark_coding_payload(
        task_kind="visualization",
        variant=BenchmarkVariant.CANDIDATE,
        execution_context=_visualization_execution(),
        acceptance={},
        planner_output=plan,
        planner_request=planner_request,
    )

    assert payload["facts"]["visualizationPlan"]["charts"][0]["chartId"] == "chart-1"


def test_visualization_benchmark_rejects_required_charts_identity_violations() -> None:
    planner_request = {
        "requiredCharts": [
            {"chartId": "chart-1", "sourcePath": "charts/chart-1.png", "interactivePath": None},
            {"chartId": "chart-2", "sourcePath": "charts/chart-2.png", "interactivePath": None},
        ],
    }

    with pytest.raises(ReportingError, match="requiredCharts") as caught:
        prepare_benchmark_coding_payload(
            task_kind="visualization",
            variant=BenchmarkVariant.CANDIDATE,
            execution_context=_visualization_execution(
                ("charts/chart-1.png", "charts/chart-2.png")
            ),
            acceptance={},
            planner_output=VisualizationPlanDraft.model_validate(
                _candidate_visualization_plan_payload()
            ),
            planner_request=planner_request,
        )

    assert caught.value.details["missingChartIds"] == ["chart-2"]
    assert caught.value.details["unexpectedChartIds"] == []


def test_visualization_benchmark_rejects_required_charts_path_mismatch() -> None:
    plan_payload = _candidate_visualization_plan_payload()
    plan_payload["charts"][0]["sourcePath"] = "charts/renamed.png"
    planner_request = {
        "requiredCharts": [
            {"chartId": "chart-1", "sourcePath": "charts/chart-1.png", "interactivePath": None}
        ],
    }

    with pytest.raises(ReportingError, match="requiredCharts") as caught:
        prepare_benchmark_coding_payload(
            task_kind="visualization",
            variant=BenchmarkVariant.CANDIDATE,
            execution_context=_visualization_execution(("charts/renamed.png",)),
            acceptance={},
            planner_output=VisualizationPlanDraft.model_validate(plan_payload),
            planner_request=planner_request,
        )

    assert caught.value.details["pathMismatches"] == ["chart-1"]


def test_visualization_benchmark_rejects_required_charts_interactive_path_mismatch() -> None:
    plan_payload = _candidate_visualization_plan_payload()
    plan_payload["charts"][0]["renderer"] = "plotly"
    plan_payload["charts"][0]["interactivePath"] = "charts/chart-1.plotly.json"
    planner_request = {
        "requiredCharts": [
            {"chartId": "chart-1", "sourcePath": "charts/chart-1.png", "interactivePath": None}
        ],
    }

    with pytest.raises(ReportingError, match="requiredCharts") as caught:
        prepare_benchmark_coding_payload(
            task_kind="visualization",
            variant=BenchmarkVariant.CANDIDATE,
            execution_context=_visualization_execution(),
            acceptance={},
            planner_output=VisualizationPlanDraft.model_validate(plan_payload),
            planner_request=planner_request,
        )

    assert caught.value.details["pathMismatches"] == ["chart-1"]


def _legacy_acceptance() -> dict:
    return {
        "decisionsByChartId": {
            "chart-1": {
                "visualForm": "按月折线图",
                "dataBindings": [
                    {
                        "analysisId": "analysis-1",
                        "factPath": "facts/analysis-1.json",
                        "dataPath": "metrics[0].periodValues",
                        "fields": ["period", "value"],
                        "role": "月度趋势",
                    }
                ],
            }
        }
    }


def test_visualization_benchmark_legacy_variant_enforces_required_charts_identity() -> None:
    planner_request = {
        "requiredCharts": [
            {"chartId": "chart-1", "sourcePath": "charts/chart-1.png", "interactivePath": None}
        ],
    }

    payload = prepare_benchmark_coding_payload(
        task_kind="visualization",
        variant=BenchmarkVariant.LEGACY,
        execution_context=_visualization_execution(),
        acceptance=_legacy_acceptance(),
        planner_output=_legacy_visualization_plan(),
        planner_request=planner_request,
    )

    assert payload["facts"]["visualizationPlan"]["charts"][0]["chartId"] == "chart-1"


def test_visualization_benchmark_legacy_variant_rejects_renamed_chart() -> None:
    legacy_payload = _legacy_visualization_plan().model_dump(mode="json", by_alias=True)
    legacy_payload["charts"][0]["sourcePath"] = "charts/renamed.png"
    planner_request = {
        "requiredCharts": [
            {"chartId": "chart-1", "sourcePath": "charts/chart-1.png", "interactivePath": None}
        ],
    }

    with pytest.raises(ReportingError, match="requiredCharts") as caught:
        prepare_benchmark_coding_payload(
            task_kind="visualization",
            variant=BenchmarkVariant.LEGACY,
            execution_context=_visualization_execution(),
            acceptance=_legacy_acceptance(),
            planner_output=LegacyVisualizationPlanDraft.model_validate(legacy_payload),
            planner_request=planner_request,
        )

    assert caught.value.details["pathMismatches"] == ["chart-1"]


@pytest.mark.parametrize(
    "planner_request",
    [
        {"requiredCharts": ["not-a-chart-entry"]},
        {"requiredCharts": [{"sourcePath": "charts/chart-1.png"}]},
        {"requiredCharts": [{"chartId": "", "sourcePath": "charts/chart-1.png"}]},
    ],
)
def test_visualization_benchmark_rejects_malformed_required_charts_entry(
    planner_request,
) -> None:
    with pytest.raises(ReportingError, match="畸形条目"):
        prepare_benchmark_coding_payload(
            task_kind="visualization",
            variant=BenchmarkVariant.CANDIDATE,
            execution_context=_visualization_execution(),
            acceptance={},
            planner_output=VisualizationPlanDraft.model_validate(
                _candidate_visualization_plan_payload()
            ),
            planner_request=planner_request,
        )


def test_visualization_benchmark_identity_gate_accepts_mapping_planner_request() -> None:
    planner_request = MappingProxyType({
        "requiredCharts": [
            {"chartId": "chart-1", "sourcePath": "charts/chart-1.png", "interactivePath": None}
        ],
    })

    payload = prepare_benchmark_coding_payload(
        task_kind="visualization",
        variant=BenchmarkVariant.CANDIDATE,
        execution_context=_visualization_execution(),
        acceptance={},
        planner_output=VisualizationPlanDraft.model_validate(
            _candidate_visualization_plan_payload()
        ),
        planner_request=planner_request,
    )

    assert payload["facts"]["visualizationPlan"]["charts"][0]["chartId"] == "chart-1"


def test_visualization_benchmark_without_required_charts_keeps_legacy_gate_only() -> None:
    plan = VisualizationPlanDraft.model_validate(_candidate_visualization_plan_payload())

    payload = prepare_benchmark_coding_payload(
        task_kind="visualization",
        variant=BenchmarkVariant.CANDIDATE,
        execution_context=_visualization_execution(),
        acceptance={},
        planner_output=plan,
        planner_request={"sectionCode": "section-1"},
    )

    assert payload["facts"]["visualizationPlan"]["charts"][0]["chartId"] == "chart-1"


def test_visualization_benchmark_projection_hides_frozen_decisions_from_legacy() -> None:
    legacy_plan = _legacy_visualization_plan()
    decisions = {
        "chart-1": {
            "visualForm": "按月折线图",
            "dataBindings": [
                {
                    "analysisId": "analysis-1",
                    "factPath": "facts/analysis-1.json",
                    "dataPath": "metrics[0].periodValues",
                    "fields": ["period", "value"],
                    "role": "月度趋势",
                }
            ],
        }
    }
    current_plan = adapt_legacy_visualization_plan(legacy_plan, decisions)
    visualization_facts = [
        {
            "analysisId": "analysis-1",
            "factFile": {"path": "facts/analysis-1.json"},
            "dataDescriptors": [
                {
                    "dataPath": "metrics[0].periodValues",
                    "fields": ["period", "value"],
                },
                {
                    "dataPath": "metrics[1].periodValues",
                    "fields": ["period", "value"],
                },
            ],
        }
    ]
    execution = {
        "codingPayload": {
            "task": {
                "task_kind": "visualization",
                "declared_output_paths": ["charts/chart-1.png"],
            },
            "facts": {"visualizationFacts": visualization_facts},
        }
    }

    legacy = prepare_benchmark_coding_payload(
        task_kind="visualization",
        variant=BenchmarkVariant.LEGACY,
        execution_context=execution,
        acceptance={"decisionsByChartId": decisions},
        planner_output=legacy_plan,
    )
    candidate = prepare_benchmark_coding_payload(
        task_kind="visualization",
        variant=BenchmarkVariant.CANDIDATE,
        execution_context=execution,
        acceptance={"decisionsByChartId": decisions},
        planner_output=current_plan,
    )

    assert "visualForm" not in legacy["facts"]["visualizationPlan"]["charts"][0]
    assert "dataBindings" not in legacy["facts"]["visualizationPlan"]["charts"][0]
    assert candidate["facts"]["visualizationPlan"]["charts"][0]["visualForm"]
    assert len(legacy["facts"]["visualizationFacts"][0]["dataDescriptors"]) == 2
    assert candidate["facts"]["visualizationFacts"][0]["dataDescriptors"] == [
        {
            "dataPath": "metrics[0].periodValues",
            "fields": ["period", "value"],
        }
    ]
    assert "visualizationPlan" not in execution["codingPayload"]["facts"]


@pytest.mark.parametrize(
    ("task_kind", "variant", "expected_schema"),
    [
        ("analysis", BenchmarkVariant.LEGACY, LegacyAnalysisEvidenceDecision),
        ("analysis", BenchmarkVariant.CANDIDATE, AnalysisEvidenceDecision),
        ("visualization", BenchmarkVariant.LEGACY, LegacyVisualizationPlanDraft),
        ("visualization", BenchmarkVariant.CANDIDATE, VisualizationPlanDraft),
    ],
)
def test_benchmark_planner_agent_selects_schema_before_request(
    task_kind, variant, expected_schema
) -> None:
    spec, agent = build_benchmark_planner_agent(
        model=OpenAIChat(id="benchmark-test"),
        task_kind=task_kind,
        variant=variant,
    )

    assert spec.output_schema is expected_schema
    assert agent.output_schema is expected_schema
    assert agent.id == f"benchmark-{task_kind}-{variant.value}-planner"
    with pytest.raises(ValueError, match="instructions"):
        BenchmarkPlannerSpec(
            task_kind="visualization",
            variant=BenchmarkVariant.CANDIDATE,
            output_schema=_PlannerOutput,
            instructions=("",),
            project_coding_facts=lambda payload: payload,
        )


@pytest.mark.parametrize("variant", [BenchmarkVariant.LEGACY, BenchmarkVariant.CANDIDATE])
def test_visualization_benchmark_planner_instructions_require_chart_identity(variant) -> None:
    spec, _agent = build_benchmark_planner_agent(
        model=OpenAIChat(id="benchmark-test"),
        task_kind="visualization",
        variant=variant,
        planner_request={
            "requiredCharts": [
                {"chartId": "chart-1", "sourcePath": "charts/chart-1.png", "interactivePath": None}
            ]
        },
    )

    instructions = "\n".join(spec.instructions)
    assert "requiredCharts" in instructions
    assert "逐字使用" in instructions
    assert "不得新增、删除、改名图表或改动任何路径" in instructions


@pytest.mark.parametrize(
    "planner_request",
    [None, {}, {"requiredCharts": None}, {"requiredCharts": "not-a-list"}],
)
def test_visualization_benchmark_planner_instructions_absent_without_required_charts(
    planner_request,
) -> None:
    spec, _agent = build_benchmark_planner_agent(
        model=OpenAIChat(id="benchmark-test"),
        task_kind="visualization",
        variant=BenchmarkVariant.CANDIDATE,
        planner_request=planner_request,
    )

    assert spec.instructions == ()


def test_analysis_benchmark_planner_instructions_untouched_by_chart_identity() -> None:
    spec, _agent = build_benchmark_planner_agent(
        model=OpenAIChat(id="benchmark-test"),
        task_kind="analysis",
        variant=BenchmarkVariant.CANDIDATE,
    )

    assert "requiredCharts" not in "\n".join(spec.instructions)
