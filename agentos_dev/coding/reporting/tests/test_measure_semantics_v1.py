from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from agno.run import RunContext
from agno.workflow.types import StepInput

from agentos_dev.coding.reporting.contract import (
    MeasureSemantic,
    ModelColumn,
    ModelTable,
    SourceSchemaSnapshot,
    schema_hash,
)
from agentos_dev.coding.reporting.data_source import DataShape
from agentos_dev.coding.reporting.models import ReportingError
from agentos_dev.coding.reporting.profile import (
    EffectiveReportingProfile,
    ReportingProfileDocument,
    ReportingProfileRegistry,
    resolve_reporting_profile,
)
from agentos_dev.coding.reporting.workflow.runtime import (
    REPORT_DATA_SHAPES_STATE_KEY,
    REPORT_DATA_UNDERSTANDING_STATE_KEY,
    REPORT_EFFECTIVE_PROFILE_STATE_KEY,
    REPORT_SCHEMA_SNAPSHOTS_STATE_KEY,
    REPORT_WORKFLOW_INPUT_STATE_KEY,
    MeasureSemanticDecision,
    MeasureSemanticProposal,
    ReportWorkflowRuntime,
    _apply_confirmed_measure_semantics,
    _apply_profile_scope_filters_to_snapshots,
    _measure_semantic_candidate_refs,
    _validate_proposed_exclusive_scopes,
)


def _snapshot(*, with_semantic: bool = False) -> SourceSchemaSnapshot:
    table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="income",
        columns=(
            ModelColumn(name="month", dataType="DATE", nullable=False),
            ModelColumn(name="department", dataType="VARCHAR(100)", nullable=True),
            ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
        ),
    )
    semantics = (
        (
            MeasureSemantic(
                fieldRef="operations.reporting.income.amount",
                aggregation="sum",
                additiveAcross=("month", "department"),
            ),
        )
        if with_semantic
        else ()
    )
    return SourceSchemaSnapshot(
        source="ddl",
        revision="ddl-v1",
        schemaHash=schema_hash((table,)),
        tables=(table,),
        measureSemantics=semantics,
    )


def _state(*, with_semantic: bool = False) -> dict[str, object]:
    snapshot = _snapshot(with_semantic=with_semantic)
    profile = resolve_reporting_profile(ReportingProfileRegistry({}, ()), None)
    return {
        REPORT_WORKFLOW_INPUT_STATE_KEY: {
            "version": "1",
            "reportGoal": "分析收入",
            "period": {"start": "2025-01-01", "end": "2025-12-31"},
            "sourceIds": ["operations"],
        },
        REPORT_SCHEMA_SNAPSHOTS_STATE_KEY: [snapshot.model_dump(mode="json", by_alias=True)],
        REPORT_DATA_UNDERSTANDING_STATE_KEY: {
            "tables": [
                {
                    "sourceId": "operations",
                    "table": "reporting.income",
                    "role": "收入分析",
                    "periodColumn": "month",
                    "periodGranularity": "date",
                }
            ]
        },
        REPORT_DATA_SHAPES_STATE_KEY: [
            {
                "sourceId": "operations",
                "metadataRevision": "ddl-v1",
                "schemaHash": snapshot.schema_hash,
                "statisticsVersion": "1",
                "queryCount": 1,
                "periodStart": "2025-01-01",
                "periodEnd": "2025-12-31",
                "tables": [
                    {
                        "sourceId": "operations",
                        "database": "reporting",
                        "table": "income",
                        "totalRowCount": 2,
                        "periodRowCount": 2,
                        "outsidePeriodRowCount": 0,
                        "periodNullCount": 0,
                        "firstEffectiveDate": "2025-01-01",
                        "lastEffectiveDate": "2025-02-01",
                        "columnCount": 3,
                        "periodGranularity": "date",
                        "periodCoverage": ["2025-01", "2025-02"],
                        "missingPeriods": [],
                        "columns": [
                            {
                                "name": name,
                                "dataType": data_type,
                                "nullable": nullable,
                                "nullCount": 0,
                                "nullRate": 0,
                                "distinctCount": 2,
                                "distinctMode": "exact",
                                "cardinalityRate": 1,
                                "unique": False,
                                "topValues": [],
                            }
                            for name, data_type, nullable in (
                                ("month", "DATE", False),
                                ("department", "VARCHAR(100)", True),
                                ("amount", "DECIMAL(18,2)", True),
                            )
                        ],
                    }
                ],
            }
        ],
        REPORT_EFFECTIVE_PROFILE_STATE_KEY: profile.model_dump(mode="json", by_alias=True),
    }


def _proposal() -> MeasureSemanticProposal:
    return MeasureSemanticProposal(
        decisions=(
            MeasureSemanticDecision(
                fieldRef="operations.reporting.income.amount",
                classification="measure",
                reason="金额字段表示可汇总的收入发生额。",
                measureSemantic=MeasureSemantic(
                    fieldRef="operations.reporting.income.amount",
                    aggregation="sum",
                    additiveAcross=("month", "department"),
                ),
            ),
        )
    )


def _profile_with_scope_filters(
    *scope_filters: dict[str, Any],
) -> EffectiveReportingProfile:
    document = ReportingProfileDocument.model_validate(
        {
            "version": "1",
            "profileId": "scoped",
            "revision": "1",
            "scopeFilters": list(scope_filters),
            "sections": [
                {"code": "executive_summary", "title": "执行摘要"},
                {"code": "scope_and_methodology", "title": "分析范围与方法"},
                {"code": "key_findings", "title": "关键发现"},
                {"code": "limitations", "title": "局限性"},
                {"code": "recommendations", "title": "建议"},
            ],
        }
    )
    return resolve_reporting_profile(ReportingProfileRegistry({"scoped": document}, ()), "scoped")


def _context(
    *,
    with_semantic: bool = False,
    profile: EffectiveReportingProfile | None = None,
) -> RunContext:
    state = _state(with_semantic=with_semantic)
    if profile is not None:
        state[REPORT_EFFECTIVE_PROFILE_STATE_KEY] = profile.model_dump(mode="json", by_alias=True)
    return RunContext(
        run_id="run-1",
        session_id="session-1",
        user_id="user-1",
        session_state=state,
    )


def test_待确认数值字段排除期间字段和已有语义():
    context = _context()
    runtime = object.__new__(ReportWorkflowRuntime)

    refs = _measure_semantic_candidate_refs(
        runtime._snapshots(context),
        runtime._data_understanding(context),
        runtime._profile(context),
    )
    assert refs == ("operations.reporting.income.amount",)
    context_with_semantic = _context(with_semantic=True)
    assert (
        _measure_semantic_candidate_refs(
            runtime._snapshots(context_with_semantic),
            runtime._data_understanding(context_with_semantic),
            runtime._profile(context_with_semantic),
        )
        == ()
    )


def test_模型固定口径值必须来自受限画像():
    state = _state()
    shape_payload = deepcopy(state[REPORT_DATA_SHAPES_STATE_KEY][0])
    department = next(
        item for item in shape_payload["tables"][0]["columns"] if item["name"] == "department"
    )
    department["topValues"] = [{"value": "内科", "count": 1, "ratio": 0.5}]
    data_shapes = (DataShape.model_validate(shape_payload),)

    def proposal(value: str) -> MeasureSemanticProposal:
        return MeasureSemanticProposal(
            decisions=(
                MeasureSemanticDecision(
                    fieldRef="operations.reporting.income.amount",
                    classification="measure",
                    reason="金额字段表示收入发生额。",
                    measureSemantic=MeasureSemantic(
                        fieldRef="operations.reporting.income.amount",
                        aggregation="sum",
                        additiveAcross=("month",),
                        exclusiveScope={"department": value},
                    ),
                ),
            )
        )

    _validate_proposed_exclusive_scopes(proposal("内科"), data_shapes)
    with pytest.raises(ReportingError) as captured:
        _validate_proposed_exclusive_scopes(proposal("科室类型"), data_shapes)

    assert captured.value.code == "report_measure_semantic_scope_unobserved"
    assert "内科" in captured.value.message


@pytest.mark.anyio
async def test_模型候选在用户批准前不写入workflow_state():
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime._measure_semantic_agent = object()
    captured: list[dict[str, object]] = []

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        return _proposal()

    runtime._run_planner = run_planner
    context = _context()
    original_state = deepcopy(context.session_state)

    output = await runtime.propose_measure_semantics(StepInput(input={}), context)

    assert output.content == _proposal()
    assert context.session_state == original_state
    assert captured[0]["candidateFieldRefs"] == ["operations.reporting.income.amount"]
    assert captured[0]["candidateFieldContexts"] == [
        {
            "fieldRef": "operations.reporting.income.amount",
            "sameTableColumnNames": ["month", "department"],
        }
    ]


@pytest.mark.anyio
async def test_已有语义时不调用模型并返回空候选():
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime._measure_semantic_agent = object()

    async def run_planner(*_args):
        raise AssertionError("已有完整语义时不应调用模型")

    runtime._run_planner = run_planner
    output = await runtime.propose_measure_semantics(
        StepInput(input={}), _context(with_semantic=True)
    )

    assert output.content == MeasureSemanticProposal()


@pytest.mark.anyio
async def test_用户批准后提交步骤才把候选写入结构快照():
    runtime = object.__new__(ReportWorkflowRuntime)
    context = _context()

    output = await runtime.commit_measure_semantics(
        StepInput(previous_step_content=_proposal()), context
    )

    snapshot = runtime._snapshots(context)[0]
    assert snapshot.measure_semantics == (_proposal().decisions[0].measure_semantic,)
    assert output.content["measureSemantics"] == [
        _proposal().decisions[0].measure_semantic.model_dump(mode="json", by_alias=True)
    ]


@pytest.mark.anyio
async def test_模型候选合并profile范围后审核对象与提交对象一致():
    profile = _profile_with_scope_filters(
        {
            "code": "department-scope",
            "fieldRefs": ["operations.reporting.income.department"],
            "value": "北部院区",
            "requiredForAllTables": True,
        }
    )
    context = _context(profile=profile)
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime._measure_semantic_agent = object()

    async def run_planner(_agent, _payload, _run_context):
        return _proposal()

    runtime._run_planner = run_planner

    reviewed = await runtime.propose_measure_semantics(StepInput(input={}), context)
    reviewed_proposal = MeasureSemanticProposal.model_validate(reviewed.content)
    reviewed_semantic = reviewed_proposal.decisions[0].measure_semantic
    assert reviewed_semantic is not None
    assert reviewed_semantic.exclusive_scope == {"department": "北部院区"}

    committed = await runtime.commit_measure_semantics(
        StepInput(previous_step_content=reviewed.content), context
    )

    assert committed.content["measureSemantics"] == [
        reviewed_semantic.model_dump(mode="json", by_alias=True)
    ]
    assert runtime._snapshots(context)[0].measure_semantics == (reviewed_semantic,)


def test_候选未完整分类或引用快照外字段时拒绝提交():
    context = _context()
    runtime = object.__new__(ReportWorkflowRuntime)
    snapshots = runtime._snapshots(context)
    plan = runtime._data_understanding(context)
    profile = runtime._profile(context)
    expected = _measure_semantic_candidate_refs(snapshots, plan, profile)

    with pytest.raises(ReportingError) as missing:
        _apply_confirmed_measure_semantics(snapshots, MeasureSemanticProposal(), expected)
    assert missing.value.code == "report_measure_semantic_proposal_invalid"

    forged = MeasureSemanticProposal(
        decisions=(
            MeasureSemanticDecision(
                fieldRef="operations.reporting.income.forged",
                classification="dimension",
                reason="伪造字段",
            ),
        )
    )
    with pytest.raises(ReportingError) as unknown:
        _apply_confirmed_measure_semantics(snapshots, forged, expected)
    assert unknown.value.code == "report_measure_semantic_proposal_invalid"


def test_profile强制范围确定性进入已有指标语义():
    snapshot = _snapshot(with_semantic=True)
    profile = _profile_with_scope_filters(
        {
            "code": "department-scope",
            "fieldRefs": ["operations.reporting.income.department"],
            "value": "北部院区",
            "requiredForAllTables": True,
        }
    )

    scoped = _apply_profile_scope_filters_to_snapshots((snapshot,), profile)

    assert scoped[0].measure_semantics[0].exclusive_scope == {"department": "北部院区"}


def test_profile强制范围缺少表映射时失败关闭():
    income = _snapshot().tables[0]
    cost = ModelTable(
        sourceId="operations",
        database="reporting",
        name="cost",
        columns=(
            ModelColumn(name="month", dataType="DATE", nullable=False),
            ModelColumn(name="department", dataType="VARCHAR(100)", nullable=True),
            ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
        ),
    )
    snapshot = SourceSchemaSnapshot(
        source="ddl",
        revision="ddl-v1",
        schemaHash=schema_hash((income, cost)),
        tables=(income, cost),
    )
    profile = _profile_with_scope_filters(
        {
            "code": "department-scope",
            "fieldRefs": ["operations.reporting.income.department"],
            "value": "北部院区",
            "requiredForAllTables": True,
        }
    )

    with pytest.raises(ReportingError) as captured:
        _apply_profile_scope_filters_to_snapshots((snapshot,), profile)

    assert captured.value.code == "report_profile_scope_filter_invalid"


@pytest.mark.parametrize(
    ("scope_filters", "expected_code"),
    [
        (
            (
                {
                    "code": "unknown-field",
                    "fieldRefs": ["operations.reporting.income.area"],
                    "value": "北部院区",
                },
            ),
            "report_profile_scope_filter_invalid",
        ),
        (
            (
                {
                    "code": "north",
                    "fieldRefs": ["operations.reporting.income.department"],
                    "value": "北部院区",
                },
                {
                    "code": "south",
                    "fieldRefs": ["operations.reporting.income.department"],
                    "value": "南部院区",
                },
            ),
            "report_profile_scope_filter_conflict",
        ),
    ],
)
def test_profile强制范围缺字段或声明冲突时失败关闭(
    scope_filters: tuple[dict[str, Any], ...], expected_code: str
):
    profile = _profile_with_scope_filters(*scope_filters)

    with pytest.raises(ReportingError) as captured:
        _apply_profile_scope_filters_to_snapshots((_snapshot(),), profile)

    assert captured.value.code == expected_code
