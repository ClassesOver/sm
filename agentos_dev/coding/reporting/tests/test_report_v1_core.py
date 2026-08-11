from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from ag_ui.core import RunAgentInput
from agno.run import RunContext
from agno.workflow.types import StepInput

from agentos_dev.coding.reporting.contract import (
    AgentQueryResponse,
    MeasureSemantic,
    ModelColumn,
    ModelTable,
    ModelTerm,
    ModelTermsResponse,
    RawDdlModel,
    ReportRequestEnvelope,
    SourceSchemaSnapshot,
    schema_hash,
)
from agentos_dev.coding.reporting.data_source import (
    CONFIG_FILE_NAME,
    DataShape,
    load_report_source_registry,
)
from agentos_dev.coding.reporting.data_sources import DatasetHandle
from agentos_dev.coding.reporting.delivery.publishing import (
    InMemoryDownloadGrantRepository,
    ReportDownloadGrantService,
    ReportDownloadScope,
    cli_result,
    publication_result,
)
from agentos_dev.coding.reporting.entrypoints import prepare_agui_envelope
from agentos_dev.coding.reporting.hospital_operation import (
    OutlineSectionProposal,
    ReportOutlineProposal,
    ReportOutlineSection,
    make_outline,
    ruijin_profile,
)
from agentos_dev.coding.reporting.hospital_operation.delivery import (
    PlanExecutionReceipt,
    SourceBinding,
    SourceWarning,
)
from agentos_dev.coding.reporting.hospital_operation.detailed_analysis import (
    profile_csv_dataset,
)
from agentos_dev.coding.reporting.metadata import ReportingMetadataClient, select_reporting_agent
from agentos_dev.coding.reporting.models import ReportingError
from agentos_dev.coding.reporting.profile import (
    ReportingProfileRegistry,
    resolve_reporting_profile,
)
from agentos_dev.coding.reporting.workflow.query_pipeline import (
    DatasetLineage,
    QueryRequirement,
    approve_query_batch,
    require_approved_sql,
    resolve_schema_snapshot,
)
from agentos_dev.coding.reporting.workflow.runtime import (
    REPORT_ANALYSIS_CONTEXT_FILE_STATE_KEY,
    REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY,
    REPORT_ANALYSIS_PLAN_STATE_KEY,
    REPORT_APPROVED_QUERIES_STATE_KEY,
    REPORT_DATA_REQUIREMENTS_STATE_KEY,
    REPORT_DATA_UNDERSTANDING_STATE_KEY,
    REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY,
    REPORT_EFFECTIVE_PROFILE_STATE_KEY,
    REPORT_OUTLINE_CONTEXT_STATE_KEY,
    REPORT_OUTLINE_STATE_KEY,
    REPORT_PROFILE_COVERAGE_STATE_KEY,
    REPORT_RECONCILIATIONS_STATE_KEY,
    REPORT_REQUEST_CONTEXT_STATE_KEY,
    REPORT_SCHEMA_SNAPSHOTS_STATE_KEY,
    REPORT_WORKFLOW_INPUT_STATE_KEY,
    REPORT_WORKFLOW_SCOPE_STATE_KEY,
    AnalysisBundle,
    AnalysisItem,
    DataUnderstandingPlan,
    DataUnderstandingTable,
    GeneratedQueryBatch,
    PlanningSchemaTable,
    ReportOutline,
    ReportWorkflowRuntime,
    TableReference,
    _analysis_allowed_mutation_paths,
    _analysis_bundle_semantic_issues,
    _analysis_validation_issues,
    _approve_generated_queries,
    _coding_observed_data_facts,
    _compact_validation_feedback,
    _normalize_duplicate_requirements,
    _outline_section_issues,
    _PlannerOutputValidationError,
    _planning_schema_payload,
    _row_preserving_requirement_ids,
    _validate_data_understanding,
    _validate_hospital_operation_profile_schema,
)


def envelope(**updates):
    value = {
        "version": "1",
        "reportGoal": "分析经营情况",
        "reportType": "comprehensive",
        "period": {"start": "2025-01-01", "end": "2025-12-31"},
        "sourceIds": ["operations"],
    }
    value.update(updates)
    return ReportRequestEnvelope.from_untrusted(value)


def test_coding任务携带数据画像确认的期间事实():
    shape = DataShape.model_validate(
        {
            "sourceId": "operations",
            "metadataRevision": "m1",
            "schemaHash": "a" * 64,
            "statisticsVersion": "1",
            "queryCount": 1,
            "periodStart": "2025-01-01",
            "periodEnd": "2025-12-31",
            "tables": [
                {
                    "sourceId": "operations",
                    "database": "reporting",
                    "table": "income",
                    "totalRowCount": 30,
                    "periodRowCount": 30,
                    "outsidePeriodRowCount": 0,
                    "periodNullCount": 0,
                    "firstEffectiveDate": "2025-01-01",
                    "lastEffectiveDate": "2025-11-01",
                    "columnCount": 1,
                    "periodGranularity": "date",
                    "periodCoverage": ["2025-01", "2025-10", "2025-11"],
                    "missingPeriods": ["2025-02"],
                    "columns": [
                        {
                            "name": "period_code",
                            "dataType": "VARCHAR",
                            "nullable": False,
                            "nullCount": 0,
                            "nullRate": 0,
                            "distinctCount": 3,
                            "distinctMode": "exact",
                            "cardinalityRate": 0.1,
                            "unique": False,
                        }
                    ],
                }
            ],
        }
    )

    requirement = QueryRequirement.model_validate(
        {
            "requirementId": "income-monthly",
            "sourceId": "operations",
            "tables": [
                {
                    "table": "reporting.income",
                    "periodColumn": "period_code",
                    "periodGranularity": "date",
                    "measureColumns": ["income_amount"],
                }
            ],
            "dimensionColumns": ["period_code"],
            "grainColumns": ["period_code"],
        }
    )
    lineage = DatasetLineage(
        datasetId="income-monthly-dataset",
        sourceId="operations",
        requirementId="income-monthly",
        sqlHash="b" * 64,
        rowCount=30,
        size=2048,
        sha256="c" * 64,
    )

    assert _coding_observed_data_facts((shape,), (requirement,), (lineage,)) == [
        {
            "datasetId": "income-monthly-dataset",
            "requirementId": "income-monthly",
            "sourceId": "operations",
            "table": "reporting.income",
            "periodGranularity": "date",
            "firstEffectiveDate": "2025-01-01",
            "lastEffectiveDate": "2025-11-01",
            "periodCoverage": ["2025-01", "2025-10", "2025-11"],
            "missingPeriods": ["2025-02"],
            "periodRowCount": 30,
        }
    ]


def tables(*, nullable: bool = False):
    return (
        ModelTable(
            sourceId="operations",
            database="reporting",
            name="income",
            columns=(ModelColumn(name="month", dataType="DATE", nullable=nullable),),
        ),
    )


def raw_ddl_models() -> tuple[RawDdlModel, ...]:
    return (
        RawDdlModel(
            id=1,
            modelName="income",
            modelDesc="收入模型",
            ddl="CREATE TABLE reporting.income (month DATE NOT NULL)",
        ),
    )


def source_config(tmp_path: Path):
    config = {
        "version": "1",
        "defaultSourceIds": ["operations"],
        "sources": [
            {
                "id": "operations",
                "type": "starrocks",
                "dsnEnv": "REPORT_DSN",
                "database": "reporting",
            }
        ],
    }
    (tmp_path / CONFIG_FILE_NAME).write_text(json.dumps(config), encoding="utf-8")
    registry = load_report_source_registry(
        tmp_path,
        tmp_path,
        environ={"REPORT_DSN": "starrocks://reader:secret@db:9030/reporting"},
    )
    return registry.sources["operations"]


def approval_snapshots() -> tuple[SourceSchemaSnapshot, ...]:
    columns = (
        ModelColumn(name="month", dataType="DATE", nullable=False),
        ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
        ModelColumn(name="campus", dataType="VARCHAR(100)", nullable=True),
    )
    values = (
        ModelTable(
            sourceId="operations",
            database="reporting",
            name=name,
            columns=columns,
        )
        for name in ("income", "cost")
    )
    model_tables = tuple(values)
    return (
        SourceSchemaSnapshot(
            source="metadata_api",
            revision="m1",
            schemaHash=schema_hash(model_tables),
            tables=model_tables,
            measureSemantics=tuple(
                MeasureSemantic(
                    fieldRef=f"operations.reporting.{name}.amount",
                    aggregation="sum",
                    additiveAcross=("month", "campus"),
                    exclusiveScope={},
                )
                for name in ("income", "cost")
            ),
        ),
    )


def data_understanding_context(
    snapshot: SourceSchemaSnapshot | None = None,
) -> RunContext:
    state = {
        REPORT_WORKFLOW_INPUT_STATE_KEY: envelope().workflow_payload(
            default_source_ids=("operations",)
        ),
        REPORT_SCHEMA_SNAPSHOTS_STATE_KEY: [
            (snapshot or approval_snapshots()[0]).model_dump(mode="json", by_alias=True)
        ],
    }
    return RunContext(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        session_state=state,
    )


@pytest.mark.anyio
async def test_分析数据上下文从需求表读取指标字段并绑定语义() -> None:
    content = b"month,amount\n2025-01-01,10\n"
    digest = hashlib.sha256(content).hexdigest()
    requirement = QueryRequirement.model_validate(
        {
            "requirementId": "income-monthly",
            "sourceId": "operations",
            "tables": [
                {
                    "table": "reporting.income",
                    "periodColumn": "month",
                    "periodGranularity": "date",
                    "measureColumns": ["amount"],
                }
            ],
            "dimensionColumns": ["month"],
            "grainColumns": ["month"],
        }
    )
    handle = DatasetHandle(
        dataset_id="dataset-1",
        source_id="operations",
        path="reports/dataset-1.csv",
        row_count=1,
        size=len(content),
        sha256=digest,
        requirement_id=requirement.requirement_id,
        sql_hash="a" * 64,
    )
    state = {
        REPORT_DATA_REQUIREMENTS_STATE_KEY: [requirement.model_dump(mode="json", by_alias=True)]
    }

    class Workspace:
        @asynccontextmanager
        async def _async_client(self):
            yield object()

        async def _asandbox_for(self, _client, _thread_id):
            return object()

        @staticmethod
        def normalize_path(path, *, allow_root):
            assert not allow_root
            return path, path

        async def _adownload_file(self, _sandbox, _path, _size):
            return content

    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = Workspace()
    runtime._state = lambda _context: state
    runtime._workflow_result = lambda _state: {"datasets": [handle.public_dict()]}
    runtime._scope = lambda _context: {"threadId": "thread-1"}
    runtime._snapshots = lambda _context: approval_snapshots()
    runtime._assert_state_safe = lambda _state: None

    await runtime.prepare_analysis_context(
        StepInput(input=envelope()), data_understanding_context()
    )

    contexts = state[REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY]
    assert contexts[0]["organizationGrain"] == ["month"]
    assert [item["fieldRef"] for item in contexts[0]["metricSemantics"]] == [
        "operations.reporting.income.amount"
    ]
    coverage = state[REPORT_PROFILE_COVERAGE_STATE_KEY]
    assert coverage["authorizedDatasetCount"] == 1
    assert coverage["coveredDatasetCount"] == 1
    assert coverage["datasets"][0]["datasetId"] == handle.dataset_id
    assert coverage["datasets"][0]["fields"] == ["month", "amount"]
    assert coverage["datasets"][0]["profileFile"]["sha256"] == contexts[0]["profileFile"]["sha256"]


@pytest.mark.anyio
async def test_详细分析计划根据profile索引编排且不启动coding任务() -> None:
    content = b"period,amount\n2025-01,10\n"
    profiled = profile_csv_dataset(
        content,
        dataset_id="dataset-question-runtime",
        path="reports/dataset-question-runtime.csv",
        expected_sha256=hashlib.sha256(content).hexdigest(),
        metric_semantics=(
            {"fieldRef": "operations.reporting.income.amount", "aggregation": "sum"},
        ),
    )
    captured: dict[str, Any] = {}
    handle = DatasetHandle(
        dataset_id="dataset-question-runtime",
        source_id="operations",
        path="reports/dataset-question-runtime.csv",
        row_count=1,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        requirement_id="income-monthly",
        sql_hash="b" * 64,
    )

    state: dict[str, Any] = {
        REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY: [profiled.model_dump(mode="json", by_alias=True)],
        REPORT_PROFILE_COVERAGE_STATE_KEY: {
            "version": "1",
            "authorizedDatasetCount": 1,
            "coveredDatasetCount": 1,
            "datasets": [
                {
                    "datasetId": handle.dataset_id,
                    "datasetPath": handle.path,
                    "datasetSize": handle.size,
                    "datasetSnapshotHash": handle.sha256,
                    "profileFile": profiled.context.profile_file.model_dump(
                        mode="json", by_alias=True
                    ),
                    "rowCount": profiled.context.row_count,
                    "fieldCount": len(profiled.context.fields),
                    "fields": list(profiled.context.fields),
                }
            ],
        },
        REPORT_ANALYSIS_PLAN_STATE_KEY: [
            {
                "code": "income",
                "description": "收入规模与趋势分析",
                "requirementIds": ["income-monthly"],
            }
        ],
        REPORT_DATA_REQUIREMENTS_STATE_KEY: [],
    }
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._state = lambda _context: state
    runtime._workflow_result = lambda _state: {"datasets": [handle.public_dict()]}
    runtime._scope = lambda _context: {
        "userId": "user-1",
        "threadId": "thread-1",
    }
    runtime._envelope = lambda _context: envelope()
    runtime._snapshots = lambda _context: approval_snapshots()

    async def write_artifact_validation_context(_thread_id, _path, payload):
        captured["context"] = payload
        return {
            "path": "reports/analysis-context.json",
            "size": 1,
            "sha256": "a" * 64,
        }

    runtime._write_artifact_validation_context = write_artifact_validation_context
    runtime._assert_state_safe = lambda _state: None

    output = await runtime.generate_detailed_analysis_plan(
        StepInput(input=envelope()),
        RunContext(run_id="workflow-run", session_id="session", user_id="user-1"),
    )

    analysis = output.content.analyses[0]
    assert analysis.analysis_id == "analysis_001"
    assert analysis.domain == "income"
    assert analysis.dataset_ids == ("dataset-question-runtime",)
    assert analysis.metrics == ("amount",)
    assert "CSV 复算" in analysis.evidence_summary
    assert "Profile 定位信号包含 2 个变量" in analysis.evidence_summary
    assert "先检查 coverage 与 alerts" in analysis.evidence_summary
    assert "Pointer 定点读取完整 Profile" in analysis.evidence_summary
    assert "关键指标期间趋势图" not in analysis.recommended_charts
    assert analysis.recommended_charts
    assert "？" not in analysis.management_question
    assert state[REPORT_ANALYSIS_CONTEXT_FILE_STATE_KEY]["sha256"] == "a" * 64
    assert "datasetContexts" in captured["context"]
    assert (
        captured["context"]["profileCoverageManifest"] == state[REPORT_PROFILE_COVERAGE_STATE_KEY]
    )
    assert "initialRequirements" in captured["context"]
    assert (
        state[REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY]["analyses"][0]["analysisId"]
        == "analysis_001"
    )


def valid_data_understanding_output() -> dict[str, object]:
    return {
        "tables": [
            {
                "sourceId": "operations",
                "table": "reporting.income",
                "role": "完成目标所需的事实表",
                "periodColumn": "month",
                "periodGranularity": "date",
            }
        ]
    }


def test_hitl恢复从workflow状态恢复可信作用域():
    state: dict[str, object] = {}
    initial = RunContext(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        session_state=state,
        dependencies={
            "AgentOS 报表工作流": {
                "externalRunId": "external-run",
                "threadId": "thread-1",
                "userId": "user-1",
            }
        },
    )

    expected = ReportWorkflowRuntime._scope(initial)
    resumed = RunContext(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        session_state=state,
    )

    assert state[REPORT_WORKFLOW_SCOPE_STATE_KEY] == expected
    assert ReportWorkflowRuntime._scope(resumed) == expected

    resumed.user_id = "user-2"
    with pytest.raises(ReportingError) as rejected:
        ReportWorkflowRuntime._scope(resumed)
    assert rejected.value.code == "report_workflow_context_missing"


def test_原生workflow从agno_runcontext建立作用域():
    context = RunContext(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        session_state={},
    )

    assert ReportWorkflowRuntime._scope(context) == {
        "externalRunId": "workflow-run",
        "threadId": "workflow-session",
        "userId": "user-1",
    }
    assert context.session_state[REPORT_WORKFLOW_SCOPE_STATE_KEY] == {
        "externalRunId": "workflow-run",
        "threadId": "workflow-session",
        "userId": "user-1",
    }


def test_数据理解输入输出复用相同规范表引用契约():
    schema_table = PlanningSchemaTable.model_validate(
        {
            "sourceId": "operations",
            "table": "REPORTING.INCOME",
            "description": "收入模型",
            "columns": [{"name": "month", "dataType": "DATE"}],
        }
    )
    selected_table = DataUnderstandingTable.model_validate(
        {
            **valid_data_understanding_output()["tables"][0],
            "table": "REPORTING.INCOME",
        }
    )

    assert isinstance(schema_table, TableReference)
    assert isinstance(selected_table, TableReference)
    assert schema_table.table == selected_table.table == "reporting.income"


def test_数据理解计划由模型选表且只校验ddl引用():
    plan = DataUnderstandingPlan.model_validate(
        {
            "tables": [
                {
                    "sourceId": "operations",
                    "table": "reporting.income",
                    "role": "模型按目标决定的收入事实表",
                    "periodColumn": "month",
                    "periodGranularity": "date",
                }
            ]
        }
    )

    _validate_data_understanding(plan, approval_snapshots())

    invalid = plan.model_copy(
        update={"tables": (plan.tables[0].model_copy(update={"period_column": "invented_column"}),)}
    )
    with pytest.raises(ReportingError) as captured:
        _validate_data_understanding(invalid, approval_snapshots())
    assert captured.value.code == "report_data_understanding_invalid"


@pytest.mark.anyio
async def test_数据理解模型只接收有效结构契约不接收原始ddl():
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._data_understanding_agent = object()

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        return DataUnderstandingPlan.model_validate(valid_data_understanding_output())

    runtime._run_planner = run_planner
    snapshot = approval_snapshots()[0].model_copy(update={"ddl_models": raw_ddl_models()})
    context = data_understanding_context(snapshot)

    await runtime.plan_data_scope(StepInput(input=envelope()), context)

    assert len(captured) == 1
    assert set(captured[0]) == {
        "reportGoal",
        "period",
        "periodWindows",
        "domains",
        "schemas",
    }
    assert captured[0]["domains"] == []
    assert [item["role"] for item in captured[0]["periodWindows"]["windows"]] == [
        "current",
        "yoy",
    ]
    schemas = captured[0]["schemas"]
    assert isinstance(schemas, list)
    assert set(schemas[0]) == {"tables", "measureSemantics"}
    assert schemas[0]["measureSemantics"][0]["aggregation"] == "sum"
    assert "ddlModels" not in json.dumps(schemas, ensure_ascii=False)
    assert set(schemas[0]["tables"][0]) == {"sourceId", "table", "description", "columns"}
    assert schemas[0]["tables"][0]["table"] == "reporting.income"
    column = schemas[0]["tables"][0]["columns"][1]
    assert column == {
        "name": "amount",
        "dataType": "DECIMAL(18,2)",
        "description": "",
    }


def test_分析计划schema只截断超长描述并保留物理事实():
    snapshot = approval_snapshots()[0]
    table = snapshot.tables[0]
    long_description = "预算类型枚举说明" * 100
    columns = tuple(
        column.model_copy(update={"description": long_description})
        if column.name == "amount"
        else column
        for column in table.columns
    )
    compact_snapshot = snapshot.model_copy(
        update={
            "tables": (
                table.model_copy(update={"description": long_description, "columns": columns}),
                *snapshot.tables[1:],
            )
        }
    )

    schemas = _planning_schema_payload((compact_snapshot,), description_limit=160)
    compact_table = schemas[0]["tables"][0]
    compact_column = next(item for item in compact_table["columns"] if item["name"] == "amount")

    assert compact_table["table"] == "reporting.income"
    assert compact_column["dataType"] == "DECIMAL(18,2)"
    assert len(compact_table["description"]) == 160
    assert len(compact_column["description"]) == 160
    assert compact_table["description"].endswith("...")


@pytest.mark.anyio
async def test_数据理解纠错反馈拒绝文件名和字段引用并复用规范候选():
    invalid_output = {
        "tables": [
            {
                "sourceId": "operations",
                "table": "income.sql",
                "role": "收入表",
                "periodColumn": "month",
                "periodGranularity": "date",
            },
            {
                "sourceId": "operations",
                "table": "income.month",
                "role": "收入期间字段",
                "periodColumn": "month",
                "periodGranularity": "date",
            },
        ]
    }
    outputs = [invalid_output, valid_data_understanding_output()]
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._data_understanding_agent = object()

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        return outputs[len(captured) - 1]

    runtime._run_planner = run_planner

    await runtime.plan_data_scope(StepInput(input=envelope()), data_understanding_context())

    assert len(captured) == 2
    correction = captured[1]["correction"]
    assert correction["attempt"] == 2
    assert "previousOutput" not in correction
    issues = {item["path"]: item for item in correction["validationFeedback"]["issues"]}
    assert "不能使用文件名" in issues["tables[0].table"]["reason"]
    assert "不能使用 table.column" in issues["tables[1].table"]["reason"]
    allowed = [
        {"sourceId": "operations", "table": "reporting.income"},
        {"sourceId": "operations", "table": "reporting.cost"},
    ]
    assert issues["tables[0].table"]["allowedValues"] == allowed
    assert issues["tables[1].table"]["allowedValues"] == allowed
    assert "直接替换错误值，不把修正说明或标记写入字段" in correction["instruction"]


@pytest.mark.anyio
async def test_数据理解一次反馈全部结构和引用问题():
    invalid_output = {
        "tables": [
            {
                "sourceId": "missing",
                "table": "reporting.income",
                "role": "未知来源",
                "periodColumn": "month",
                "periodGranularity": "date",
            },
            {
                "sourceId": "operations",
                "table": "reporting.missing",
                "role": "未知表",
                "periodColumn": "month",
                "periodGranularity": "date",
            },
            {
                "sourceId": "operations",
                "table": "reporting.income",
                "role": "期间错误",
                "periodColumn": "invented",
                "periodGranularity": "quarter",
                "unexpected": True,
            },
            {
                "sourceId": "operations",
                "table": "reporting.income",
                "role": "重复表",
                "periodColumn": "month",
                "periodGranularity": "date",
            },
        ]
    }
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._data_understanding_agent = object()

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        return invalid_output if len(captured) == 1 else valid_data_understanding_output()

    runtime._run_planner = run_planner

    await runtime.plan_data_scope(StepInput(input=envelope()), data_understanding_context())

    feedback = captured[1]["correction"]["validationFeedback"]
    paths = {item["path"] for item in feedback["issues"]}
    assert {
        "tables[0].sourceId",
        "tables[0].table",
        "tables[1].table",
        "tables[2].periodColumn",
        "tables[2].periodGranularity",
        "tables[2].unexpected",
        "tables[3].table",
    } <= paths
    period_issue = next(
        item for item in feedback["issues"] if item["path"] == "tables[2].periodColumn"
    )
    assert period_issue["allowedValues"] == ["month", "amount", "campus"]


@pytest.mark.anyio
async def test_数据理解一次反馈字段缺失类型错误和多余字段():
    invalid_output = {
        "tables": [
            {
                "sourceId": 1,
                "table": "reporting.income",
                "periodColumn": ["month"],
                "periodGranularity": "date",
                "unexpected": True,
            }
        ]
    }
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._data_understanding_agent = object()

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        return invalid_output if len(captured) == 1 else valid_data_understanding_output()

    runtime._run_planner = run_planner

    await runtime.plan_data_scope(StepInput(input=envelope()), data_understanding_context())

    issues = captured[1]["correction"]["validationFeedback"]["issues"]
    paths = {item["path"] for item in issues}
    assert {
        "tables[0].sourceId",
        "tables[0].role",
        "tables[0].periodColumn",
        "tables[0].unexpected",
    } <= paths


@pytest.mark.anyio
async def test_数据理解期间粒度与物理字段不匹配时反馈合法组合():
    invalid_output = {
        "tables": [
            {
                "sourceId": "operations",
                "table": "reporting.income",
                "role": "收入表",
                "periodColumn": "campus",
                "periodGranularity": "date",
            }
        ]
    }
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._data_understanding_agent = object()

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        return invalid_output if len(captured) == 1 else valid_data_understanding_output()

    runtime._run_planner = run_planner

    await runtime.plan_data_scope(StepInput(input=envelope()), data_understanding_context())

    issues = captured[1]["correction"]["validationFeedback"]["issues"]
    issue = next(item for item in issues if item["path"] == "tables[0].periodGranularity")
    assert "VARCHAR(100)" in issue["reason"]
    assert issue["allowedValues"] == [
        {
            "periodColumn": "month",
            "dataType": "DATE",
            "periodGranularity": "date",
        }
    ]


def test_数据理解支持字符串月份物理编码():
    table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="monthly_income",
        columns=(
            ModelColumn(
                name="period_code",
                dataType="VARCHAR(7)",
                nullable=False,
                description="数据月份，例如 2026/02 或 2026-02",
            ),
        ),
    )
    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision="m1",
        schemaHash=schema_hash((table,)),
        tables=(table,),
    )
    plan = DataUnderstandingPlan.model_validate(
        {
            "tables": [
                {
                    "sourceId": "operations",
                    "table": "reporting.monthly_income",
                    "role": "月度收入",
                    "periodColumn": "period_code",
                    "periodGranularity": "month",
                }
            ]
        }
    )

    _validate_data_understanding(plan, (snapshot,))


def test_数据理解支持字符串日期物理编码():
    table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="daily_income",
        columns=(
            ModelColumn(
                name="data_date",
                dataType="VARCHAR(10)",
                nullable=False,
                description="数据日期，例如 2026/02/01 或 2026-02-01",
            ),
        ),
    )
    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision="m1",
        schemaHash=schema_hash((table,)),
        tables=(table,),
    )
    plan = DataUnderstandingPlan.model_validate(
        {
            "tables": [
                {
                    "sourceId": "operations",
                    "table": "reporting.daily_income",
                    "role": "每日收入",
                    "periodColumn": "data_date",
                    "periodGranularity": "date",
                }
            ]
        }
    )

    _validate_data_understanding(plan, (snapshot,))


@pytest.mark.anyio
async def test_分析计划结构错误会携带强反馈纠错且不盲重试():
    invalid_output = {
        "analyses": [
            {
                "code": "income",
                "description": "收入分析",
                "requirementIds": ["income-monthly"],
            }
        ],
        "requirements": [
            {
                "requirementId": "income-monthly",
                "sourceId": "operations",
                "tables": [
                    {
                        "table": "reporting.income",
                        "periodColumn": "month",
                        "periodGranularity": "date",
                        "measureColumns": ["amount"],
                    }
                ],
                "dimensionColumns": ["campus"],
                "grainColumns": ["month"],
                "relations": [],
            }
        ],
    }
    valid_output = {
        **invalid_output,
        "requirements": [
            {
                **invalid_output["requirements"][0],
                "dimensionColumns": ["month", "campus"],
            }
        ],
    }
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._analysis_agent = object()

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        if len(captured) == 1:
            raise _PlannerOutputValidationError(
                invalid_output,
                [
                    {
                        "path": "requirements[0]",
                        "rejectedValue": invalid_output["requirements"][0],
                        "reason": "grainColumns 必须属于 dimensionColumns",
                        "requiredAction": "修正该字段并返回完整 AnalysisBundle",
                    }
                ],
            )
        return AnalysisBundle.model_validate(valid_output)

    runtime._run_planner = run_planner
    context = data_understanding_context()
    state = context.session_state
    state[REPORT_OUTLINE_STATE_KEY] = {
        "title": "运营分析",
        "sections": ["收入分析"],
        "assumptions": [],
    }
    state[REPORT_OUTLINE_CONTEXT_STATE_KEY] = {}
    state[REPORT_DATA_UNDERSTANDING_STATE_KEY] = valid_data_understanding_output()

    await runtime.generate_analysis_plan(StepInput(input=envelope()), context)

    assert len(captured) == 2
    correction = captured[1]["correction"]
    assert correction["attempt"] == 2
    assert correction["previousOutput"] == invalid_output
    assert correction["allowedMutationPaths"] == ["requirements[0]"]
    assert correction["validationFeedback"]["issues"][0]["path"] == "requirements[0]"
    assert "grainColumns" in correction["validationFeedback"]["issues"][0]["reason"]
    assert state[REPORT_ANALYSIS_PLAN_STATE_KEY][0]["code"] == "income"
    assert state[REPORT_DATA_REQUIREMENTS_STATE_KEY][0]["requirementId"] == "income-monthly"


def test_分析计划模型契约以provider兼容描述声明数组不得重复():
    definitions = AnalysisBundle.model_json_schema(by_alias=True)["$defs"]

    fields = (
        definitions["AnalysisItem"]["properties"]["requirementIds"],
        definitions["RequirementTable"]["properties"]["measureColumns"],
        definitions["QueryRequirement"]["properties"]["dimensionColumns"],
        definitions["QueryRequirement"]["properties"]["grainColumns"],
    )
    assert all(
        "每个" in field["description"] and "只出现一次" in field["description"] for field in fields
    )
    assert all("uniqueItems" not in field for field in fields)


def test_分析需求数量受三窗口物化批次上限约束():
    requirement = query_requirement()
    requirements = tuple(
        requirement.model_copy(update={"requirement_id": f"income-monthly-{index}"})
        for index in range(34)
    )

    with pytest.raises(ValueError):
        AnalysisBundle.model_validate(
            {
                "analyses": [
                    {
                        "code": "income",
                        "description": "收入分析",
                        "requirementIds": [requirements[0].requirement_id],
                    }
                ],
                "requirements": [
                    item.model_dump(mode="json", by_alias=True) for item in requirements
                ],
            }
        )


def test_分析计划字段纠错反馈提供实际数值字段候选():
    raw_output = {
        "requirements": [
            {
                "requirementId": "income-monthly",
                "sourceId": "operations",
                "tables": [
                    {
                        "table": "reporting.income",
                        "periodColumn": "month",
                        "measureColumns": ["amount", "amount"],
                    }
                ],
            }
        ]
    }

    enriched = _analysis_validation_issues(
        [
            {
                "path": "requirements[0].tables[0].measureColumns",
                "rejectedValue": ["amount", "amount"],
                "reason": "measureColumns 不能重复",
            }
        ],
        raw_output,
        approval_snapshots(),
    )

    assert enriched[0]["allowedValues"] == ["amount"]
    assert enriched[0]["requiredAction"] == (
        "从 allowedValues 选择必要的可聚合数值字段，每个字段只保留一次"
    )


def test_分析计划多表缺少关系时反馈优先拆分单表():
    enriched = _analysis_validation_issues(
        [
            {
                "path": "requirements[0]",
                "rejectedValue": {"tables": [{}, {}], "relations": []},
                "reason": "Value error, 多表 requirement 必须声明 relations",
                "requiredAction": "根据 reason 修正该字段，并返回完整输出 JSON",
            }
        ],
        {"requirements": []},
        approval_snapshots(),
    )

    assert "拆分为单表" in enriched[0]["requiredAction"]
    assert _analysis_allowed_mutation_paths(enriched) == (
        "requirements",
        "analyses[*].requirementIds",
    )


@pytest.mark.anyio
async def test_分析计划结构纠错保留可解析候选并限制修改路径():
    requirement = query_requirement()
    valid_payload = {
        "analyses": [
            {
                "code": "income",
                "description": "收入分析",
                "requirementIds": [requirement.requirement_id],
            }
        ],
        "requirements": [requirement.model_dump(mode="json", by_alias=True)],
    }
    invalid_payload = json.loads(json.dumps(valid_payload))
    invalid_payload["requirements"][0]["tables"][0]["measureColumns"] = [
        "amount",
        "amount",
    ]
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._analysis_agent = SimpleNamespace(id="analysis-planner")

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        if len(captured) == 1:
            raise _PlannerOutputValidationError(
                invalid_payload,
                [
                    {
                        "path": "requirements[0].tables[0].measureColumns",
                        "rejectedValue": ["amount", "amount"],
                        "reason": "measureColumns 不能重复",
                        "requiredAction": "根据 reason 修正该字段，并返回完整输出 JSON",
                    }
                ],
            )
        return AnalysisBundle.model_validate(valid_payload)

    runtime._run_planner = run_planner
    context = data_understanding_context()
    state = context.session_state
    state[REPORT_OUTLINE_STATE_KEY] = {
        "title": "运营分析",
        "sections": ["收入分析"],
        "assumptions": [],
    }
    state[REPORT_OUTLINE_CONTEXT_STATE_KEY] = {}
    state[REPORT_DATA_UNDERSTANDING_STATE_KEY] = valid_data_understanding_output()

    await runtime.generate_analysis_plan(StepInput(input=envelope()), context)

    correction = captured[1]["correction"]
    assert correction["previousOutput"] == invalid_payload
    assert correction["allowedMutationPaths"] == ["requirements[0].tables[0].measureColumns"]


@pytest.mark.anyio
async def test_分析计划语义纠错基于上一合法输出且只允许修改错误路径():
    requirement = query_requirement()
    invalid = AnalysisBundle.model_validate(
        {
            "analyses": [
                {
                    "code": "income",
                    "description": "收入分析",
                    "requirementIds": ["income-monthl"],
                }
            ],
            "requirements": [requirement.model_dump(mode="json", by_alias=True)],
        }
    )
    valid = invalid.model_copy(
        update={
            "analyses": (
                invalid.analyses[0].model_copy(
                    update={"requirement_ids": (requirement.requirement_id,)}
                ),
            )
        }
    )
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._analysis_agent = SimpleNamespace(id="analysis-planner")

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        return invalid if len(captured) == 1 else valid

    runtime._run_planner = run_planner
    context = data_understanding_context()
    state = context.session_state
    state[REPORT_OUTLINE_STATE_KEY] = {
        "title": "运营分析",
        "sections": ["收入分析"],
        "assumptions": [],
    }
    state[REPORT_OUTLINE_CONTEXT_STATE_KEY] = {
        "profile": {
            "profileId": "generic",
            "revision": "1",
            "dimensions": [],
            "metrics": [],
            "reconciliations": [],
            "pageLayout": {"headerLeft": "不应进入分析上下文"},
        },
        "capabilities": [],
        "tables": [
            {
                "sourceId": "operations",
                "table": "reporting.income",
                "periodRowCount": 12,
                "periodGranularity": "date",
                "periodCoverage": ["2025-01"],
                "missingPeriods": [],
                "columns": [{"name": "不应重复输入"}],
            }
        ],
        "schemas": [{"table": "不应重复输入"}],
    }
    state[REPORT_DATA_UNDERSTANDING_STATE_KEY] = valid_data_understanding_output()

    await runtime.generate_analysis_plan(StepInput(input=envelope()), context)

    assert set(captured[0]) == {
        "reportGoal",
        "domains",
        "periodWindows",
        "analysisSequence",
        "analysisContext",
        "dataUnderstanding",
        "schemas",
    }
    assert captured[0]["analysisSequence"] == [
        "整体规模与结构",
        "趋势与拐点",
        "异常贡献",
        "归因验证",
        "经营影响",
    ]
    assert "schemas" not in captured[0]["analysisContext"]
    assert "tables" not in captured[0]["analysisContext"]
    assert [table["table"] for schema in captured[0]["schemas"] for table in schema["tables"]] == [
        "reporting.income"
    ]
    correction = captured[1]["correction"]
    assert correction["previousOutput"] == invalid.model_dump(mode="json", by_alias=True)
    assert correction["allowedMutationPaths"] == ["analyses[0].requirementIds"]
    issue = correction["validationFeedback"]["issues"][0]
    assert issue["suggestedReplacement"] == requirement.requirement_id


@pytest.mark.anyio
async def test_分析计划删除无合法指标需求且拒绝借机改写其他分析():
    income_table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="income",
        columns=(
            ModelColumn(name="month", dataType="DATE", nullable=False),
            ModelColumn(name="campus", dataType="VARCHAR(100)", nullable=True),
            ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
        ),
    )
    project_table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="project_budget",
        columns=(
            ModelColumn(name="period_year", dataType="INTEGER", nullable=False),
            ModelColumn(name="project_name", dataType="VARCHAR(255)", nullable=False),
            ModelColumn(name="budget_amount", dataType="DECIMAL(18,2)", nullable=True),
        ),
    )
    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision="m1",
        schemaHash=schema_hash((income_table, project_table)),
        tables=(income_table, project_table),
        measureSemantics=(
            MeasureSemantic(
                fieldRef="operations.reporting.income.amount",
                aggregation="sum",
                additiveAcross=("month", "campus"),
                exclusiveScope={},
            ),
        ),
    )
    income_requirement = QueryRequirement.model_validate(
        {
            "requirementId": "income-monthly",
            "sourceId": "operations",
            "tables": [
                {
                    "table": "reporting.income",
                    "periodColumn": "month",
                    "periodGranularity": "date",
                    "measureColumns": ["amount"],
                }
            ],
            "dimensionColumns": ["month", "campus"],
            "grainColumns": ["month", "campus"],
        }
    )
    project_requirement = QueryRequirement.model_validate(
        {
            "requirementId": "project-annual",
            "sourceId": "operations",
            "tables": [
                {
                    "table": "reporting.project_budget",
                    "periodColumn": "period_year",
                    "periodGranularity": "year",
                    "measureColumns": ["budget_amount"],
                }
            ],
            "dimensionColumns": ["period_year", "project_name"],
            "grainColumns": ["period_year", "project_name"],
        }
    )
    invalid = AnalysisBundle.model_validate(
        {
            "analyses": [
                {
                    "code": "income",
                    "description": "收入分析",
                    "requirementIds": ["income-monthly"],
                },
                {
                    "code": "project",
                    "description": "项目预算分析",
                    "requirementIds": ["project-annual"],
                },
            ],
            "requirements": [
                income_requirement.model_dump(mode="json", by_alias=True),
                project_requirement.model_dump(mode="json", by_alias=True),
            ],
        }
    )
    corrected = invalid.model_copy(
        update={"analyses": (invalid.analyses[0],), "requirements": (income_requirement,)}
    )
    drifted = corrected.model_copy(
        update={
            "analyses": (
                corrected.analyses[0].model_copy(update={"description": "借纠错改写的收入分析"}),
            )
        }
    )
    outputs = [invalid, drifted, corrected]
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._analysis_agent = SimpleNamespace(id="analysis-planner")

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        return outputs[len(captured) - 1]

    runtime._run_planner = run_planner
    context = data_understanding_context(snapshot)
    state = context.session_state
    state[REPORT_OUTLINE_STATE_KEY] = {
        "title": "运营分析",
        "sections": ["收入分析", "项目预算分析"],
        "assumptions": [],
    }
    state[REPORT_OUTLINE_CONTEXT_STATE_KEY] = {}
    state[REPORT_DATA_UNDERSTANDING_STATE_KEY] = {
        "tables": [
            {
                "sourceId": "operations",
                "table": "reporting.income",
                "role": "收入",
                "periodColumn": "month",
                "periodGranularity": "date",
            },
            {
                "sourceId": "operations",
                "table": "reporting.project_budget",
                "role": "项目预算",
                "periodColumn": "period_year",
                "periodGranularity": "year",
            },
        ]
    }

    await runtime.generate_analysis_plan(StepInput(input=envelope()), context)

    assert len(captured) == 3
    first_correction = captured[1]["correction"]
    assert first_correction["allowedMutationPaths"] == []
    assert first_correction["requiredDeletionPaths"] == ["requirements[1]", "analyses[1]"]
    issue = first_correction["validationFeedback"]["issues"][0]
    assert issue["reason"] == "字段未获服务端结构快照批准为可聚合指标，禁止猜测聚合口径"
    assert "删除整个 requirement" in issue["requiredAction"]
    assert captured[2]["correction"]["validationFeedback"]["code"] == (
        "report_correction_scope_violation"
    )
    assert state[REPORT_ANALYSIS_PLAN_STATE_KEY] == [
        invalid.analyses[0].model_dump(mode="json", by_alias=True)
    ]
    assert state[REPORT_DATA_REQUIREMENTS_STATE_KEY] == [
        income_requirement.model_dump(mode="json", by_alias=True)
    ]


@pytest.mark.anyio
async def test_分析计划由服务端补齐多指标共用的安全物化粒度():
    table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="income",
        columns=(
            ModelColumn(name="month", dataType="DATE", nullable=False),
            ModelColumn(name="campus", dataType="VARCHAR(100)", nullable=True),
            ModelColumn(name="department_code", dataType="VARCHAR(30)", nullable=True),
            ModelColumn(name="department", dataType="VARCHAR(100)", nullable=True),
            ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
            ModelColumn(name="person_time", dataType="INTEGER", nullable=True),
        ),
    )
    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision="m1",
        schemaHash=schema_hash((table,)),
        tables=(table,),
        measureSemantics=(
            MeasureSemantic(
                fieldRef="operations.reporting.income.amount",
                aggregation="sum",
            ),
            MeasureSemantic(
                fieldRef="operations.reporting.income.person_time",
                aggregation="sum",
            ),
        ),
    )
    requirement = QueryRequirement.model_validate(
        {
            "requirementId": "income-monthly",
            "sourceId": "operations",
            "tables": [
                {
                    "table": "reporting.income",
                    "periodColumn": "month",
                    "periodGranularity": "date",
                    "measureColumns": ["amount", "person_time"],
                }
            ],
            "dimensionColumns": ["campus"],
            "grainColumns": ["campus"],
        }
    )
    bundle = AnalysisBundle.model_validate(
        {
            "analyses": [
                {
                    "code": "income",
                    "description": "收入与人次分析",
                    "requirementIds": [requirement.requirement_id],
                }
            ],
            "requirements": [requirement.model_dump(mode="json", by_alias=True)],
        }
    )
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._analysis_agent = SimpleNamespace(id="analysis-planner")

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        return bundle

    runtime._run_planner = run_planner
    context = data_understanding_context(snapshot)
    state = context.session_state
    state[REPORT_OUTLINE_STATE_KEY] = {
        "title": "运营分析",
        "sections": ["收入分析"],
        "assumptions": [],
    }
    state[REPORT_OUTLINE_CONTEXT_STATE_KEY] = {}
    state[REPORT_DATA_UNDERSTANDING_STATE_KEY] = {
        "tables": [
            {
                "sourceId": "operations",
                "table": "reporting.income",
                "role": "收入",
                "periodColumn": "month",
                "periodGranularity": "date",
            }
        ]
    }

    await runtime.generate_analysis_plan(StepInput(input=envelope()), context)

    assert len(captured) == 1
    normalized = state[REPORT_DATA_REQUIREMENTS_STATE_KEY][0]
    assert normalized["dimensionColumns"] == [
        "campus",
        "month",
        "department_code",
        "department",
    ]
    assert normalized["grainColumns"] == [
        "campus",
        "month",
        "department_code",
        "department",
    ]
    assert bundle.requirements[0] == requirement


def test_分析计划安全粒度反馈按表合并并开放完整修复目标():
    table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="income",
        columns=(
            ModelColumn(name="month", dataType="DATE", nullable=False),
            ModelColumn(name="campus", dataType="VARCHAR(100)", nullable=True),
            ModelColumn(name="department", dataType="VARCHAR(100)", nullable=True),
            ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
            ModelColumn(name="person_time", dataType="INTEGER", nullable=True),
        ),
    )
    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision="m1",
        schemaHash=schema_hash((table,)),
        tables=(table,),
        measureSemantics=(
            MeasureSemantic(
                fieldRef="operations.reporting.income.amount",
                aggregation="sum",
            ),
            MeasureSemantic(
                fieldRef="operations.reporting.income.person_time",
                aggregation="sum",
            ),
        ),
    )
    requirement = QueryRequirement.model_validate(
        {
            "requirementId": "income-monthly",
            "sourceId": "operations",
            "tables": [
                {
                    "table": "reporting.income",
                    "periodColumn": "month",
                    "periodGranularity": "date",
                    "measureColumns": ["amount", "person_time"],
                }
            ],
            "dimensionColumns": ["month", "campus"],
            "grainColumns": ["month", "campus"],
        }
    )
    bundle = AnalysisBundle.model_validate(
        {
            "analyses": [
                {
                    "code": "income",
                    "description": "收入与人次分析",
                    "requirementIds": [requirement.requirement_id],
                }
            ],
            "requirements": [requirement.model_dump(mode="json", by_alias=True)],
        }
    )
    understanding = DataUnderstandingPlan.model_validate(
        {
            "tables": [
                {
                    "sourceId": "operations",
                    "table": "reporting.income",
                    "role": "收入",
                    "periodColumn": "month",
                    "periodGranularity": "date",
                }
            ]
        }
    )

    issues = _analysis_bundle_semantic_issues(bundle, understanding, (snapshot,))

    assert len(issues) == 1
    assert issues[0]["path"] == "requirements[0].grainColumns"
    assert issues[0]["missingValues"] == ["department"]
    assert issues[0]["repairTargets"] == [
        "requirements[0].dimensionColumns",
        "requirements[0].grainColumns",
    ]
    assert issues[0]["targetValues"] == {
        "dimensionColumns": ["month", "campus", "department"],
        "grainColumns": ["month", "campus", "department"],
    }
    assert _analysis_allowed_mutation_paths(issues) == (
        "requirements[0].dimensionColumns",
        "requirements[0].grainColumns",
    )


@pytest.mark.anyio
async def test_分析计划连续相同且无法规范化时提前停止():
    columns = (
        ModelColumn(name="month", dataType="DATE", nullable=False),
        *(
            ModelColumn(name=f"dimension_{index}", dataType="VARCHAR(30)", nullable=True)
            for index in range(30)
        ),
        ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
    )
    table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="income",
        columns=columns,
    )
    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision="m1",
        schemaHash=schema_hash((table,)),
        tables=(table,),
        measureSemantics=(
            MeasureSemantic(
                fieldRef="operations.reporting.income.amount",
                aggregation="sum",
            ),
        ),
    )
    requirement = QueryRequirement.model_validate(
        {
            "requirementId": "income-monthly",
            "sourceId": "operations",
            "tables": [
                {
                    "table": "reporting.income",
                    "periodColumn": "month",
                    "periodGranularity": "date",
                    "measureColumns": ["amount"],
                }
            ],
            "dimensionColumns": ["month"],
            "grainColumns": ["month"],
        }
    )
    bundle = AnalysisBundle.model_validate(
        {
            "analyses": [
                {
                    "code": "income",
                    "description": "收入分析",
                    "requirementIds": [requirement.requirement_id],
                }
            ],
            "requirements": [requirement.model_dump(mode="json", by_alias=True)],
        }
    )
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._analysis_agent = SimpleNamespace(id="analysis-planner")

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        return bundle

    runtime._run_planner = run_planner
    context = data_understanding_context(snapshot)
    state = context.session_state
    state[REPORT_OUTLINE_STATE_KEY] = {
        "title": "运营分析",
        "sections": ["收入分析"],
        "assumptions": [],
    }
    state[REPORT_OUTLINE_CONTEXT_STATE_KEY] = {}
    state[REPORT_DATA_UNDERSTANDING_STATE_KEY] = {
        "tables": [
            {
                "sourceId": "operations",
                "table": "reporting.income",
                "role": "收入",
                "periodColumn": "month",
                "periodGranularity": "date",
            }
        ]
    }

    with pytest.raises(ReportingError) as captured_error:
        await runtime.generate_analysis_plan(StepInput(input=envelope()), context)

    assert captured_error.value.code == "report_analysis_plan_invalid"
    assert "连续两次没有进展" in captured_error.value.message
    assert len(captured) == 2


@pytest.mark.anyio
async def test_分析计划纠错拒绝修改允许路径以外的字段():
    requirement = query_requirement()
    invalid = AnalysisBundle.model_validate(
        {
            "analyses": [
                {
                    "code": "income",
                    "description": "收入分析",
                    "requirementIds": ["income-monthl"],
                }
            ],
            "requirements": [requirement.model_dump(mode="json", by_alias=True)],
        }
    )
    corrected_analysis = invalid.analyses[0].model_copy(
        update={"requirement_ids": (requirement.requirement_id,)}
    )
    drifted = invalid.model_copy(
        update={
            "analyses": (corrected_analysis.model_copy(update={"description": "擅自改写的描述"}),)
        }
    )
    valid = invalid.model_copy(update={"analyses": (corrected_analysis,)})
    outputs = [invalid, drifted, valid]
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._analysis_agent = SimpleNamespace(id="analysis-planner")

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        return outputs[len(captured) - 1]

    runtime._run_planner = run_planner
    context = data_understanding_context()
    state = context.session_state
    state[REPORT_OUTLINE_STATE_KEY] = {
        "title": "运营分析",
        "sections": ["收入分析"],
        "assumptions": [],
    }
    state[REPORT_OUTLINE_CONTEXT_STATE_KEY] = {}
    state[REPORT_DATA_UNDERSTANDING_STATE_KEY] = valid_data_understanding_output()

    await runtime.generate_analysis_plan(StepInput(input=envelope()), context)

    correction = captured[2]["correction"]
    assert correction["validationFeedback"]["code"] == "report_correction_scope_violation"
    assert correction["allowedMutationPaths"] == ["analyses[0].requirementIds"]
    assert correction["previousOutput"] == invalid.model_dump(mode="json", by_alias=True)


@pytest.mark.anyio
async def test_分析计划禁止强行拼接期间语义不同的表并反馈拆分单表requirement():
    monthly = ModelTable(
        sourceId="operations",
        database="reporting",
        name="income",
        columns=(
            ModelColumn(name="period_code", dataType="VARCHAR(7)", nullable=False),
            ModelColumn(name="area", dataType="VARCHAR(100)", nullable=True),
            ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
        ),
    )
    annual = ModelTable(
        sourceId="operations",
        database="reporting",
        name="project_budget",
        columns=(
            ModelColumn(name="period_year", dataType="VARCHAR(4)", nullable=False),
            ModelColumn(name="area", dataType="VARCHAR(100)", nullable=True),
            ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
        ),
    )
    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision="m1",
        schemaHash=schema_hash((monthly, annual)),
        tables=(monthly, annual),
        measureSemantics=(
            MeasureSemantic(
                fieldRef="operations.reporting.income.amount",
                aggregation="sum",
                additiveAcross=("period_code", "area"),
            ),
            MeasureSemantic(
                fieldRef="operations.reporting.project_budget.amount",
                aggregation="sum",
                additiveAcross=("period_year", "area"),
            ),
        ),
    )
    invalid_output = {
        "analyses": [
            {
                "code": "budget",
                "description": "预算与收入对照",
                "requirementIds": ["forced-join"],
            }
        ],
        "requirements": [
            {
                "requirementId": "forced-join",
                "sourceId": "operations",
                "tables": [
                    {
                        "table": "reporting.income",
                        "periodColumn": "period_code",
                        "periodGranularity": "month",
                        "measureColumns": ["amount"],
                    },
                    {
                        "table": "reporting.project_budget",
                        "periodColumn": "period_year",
                        "periodGranularity": "year",
                        "measureColumns": ["amount"],
                    },
                ],
                "dimensionColumns": ["period_code", "area"],
                "grainColumns": ["period_code", "area"],
                "relations": [
                    {
                        "leftTable": "reporting.income",
                        "rightTable": "reporting.project_budget",
                        "joinColumns": ["area"],
                    }
                ],
            }
        ],
    }
    valid_output = {
        "analyses": [
            {
                "code": "budget",
                "description": "预算与收入对照",
                "requirementIds": ["income-monthly", "budget-annual"],
            }
        ],
        "requirements": [
            {
                "requirementId": "income-monthly",
                "sourceId": "operations",
                "tables": [invalid_output["requirements"][0]["tables"][0]],
                "dimensionColumns": ["period_code", "area"],
                "grainColumns": ["period_code", "area"],
                "relations": [],
            },
            {
                "requirementId": "budget-annual",
                "sourceId": "operations",
                "tables": [invalid_output["requirements"][0]["tables"][1]],
                "dimensionColumns": ["period_year", "area"],
                "grainColumns": ["period_year", "area"],
                "relations": [],
            },
        ],
    }
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._analysis_agent = object()

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        output = invalid_output if len(captured) == 1 else valid_output
        return AnalysisBundle.model_validate(output)

    runtime._run_planner = run_planner
    context = data_understanding_context(snapshot)
    state = context.session_state
    state[REPORT_OUTLINE_STATE_KEY] = {
        "title": "运营分析",
        "sections": ["预算分析"],
        "assumptions": [],
    }
    state[REPORT_OUTLINE_CONTEXT_STATE_KEY] = {}
    state[REPORT_DATA_UNDERSTANDING_STATE_KEY] = {
        "tables": [
            {
                "sourceId": "operations",
                "table": "reporting.income",
                "role": "月度收入",
                "periodColumn": "period_code",
                "periodGranularity": "month",
            },
            {
                "sourceId": "operations",
                "table": "reporting.project_budget",
                "role": "年度项目预算",
                "periodColumn": "period_year",
                "periodGranularity": "year",
            },
        ]
    }

    await runtime.generate_analysis_plan(StepInput(input=envelope()), context)

    assert len(captured) == 2
    issues = captured[1]["correction"]["validationFeedback"]["issues"]
    assert any(issue["path"] == "requirements[0].tables" for issue in issues)
    assert any("拆分为单表 requirements" in issue["requiredAction"] for issue in issues)
    assert [item["requirementId"] for item in state[REPORT_DATA_REQUIREMENTS_STATE_KEY]] == [
        "income-monthly",
        "budget-annual",
    ]


def test_分析计划允许期间语义和完整共同粒度一致的多表requirement():
    requirement = query_requirement(
        tables=[
            {"table": "reporting.income", "periodColumn": "month"},
            {"table": "reporting.cost", "periodColumn": "month"},
        ],
        grain_columns=("month", "campus"),
    )
    bundle = AnalysisBundle.model_validate(
        {
            "analyses": [
                {
                    "code": "margin",
                    "description": "收入成本分析",
                    "requirementIds": [requirement.requirement_id],
                }
            ],
            "requirements": [requirement.model_dump(mode="json", by_alias=True)],
        }
    )
    understanding = DataUnderstandingPlan.model_validate(
        {
            "tables": [
                {
                    "sourceId": "operations",
                    "table": f"reporting.{name}",
                    "role": name,
                    "periodColumn": "month",
                    "periodGranularity": "date",
                }
                for name in ("income", "cost")
            ]
        }
    )

    assert _analysis_bundle_semantic_issues(bundle, understanding, approval_snapshots()) == []


def test_分析计划拒绝requirement扩展请求比较范围():
    requirement = query_requirement().model_copy(update={"comparison_roles": ("yoy", "mom")})
    bundle = AnalysisBundle.model_validate(
        {
            "analyses": [
                {
                    "code": "income",
                    "description": "收入分析",
                    "requirementIds": [requirement.requirement_id],
                }
            ],
            "requirements": [requirement.model_dump(mode="json", by_alias=True)],
        }
    )
    understanding = DataUnderstandingPlan.model_validate(valid_data_understanding_output())

    issues = _analysis_bundle_semantic_issues(
        bundle,
        understanding,
        approval_snapshots(),
        envelope(),
    )

    assert issues == [
        {
            "path": "requirements[0].comparisonRoles",
            "rejectedValue": ["mom"],
            "reason": "comparisonRoles 超出请求允许的比较范围",
            "allowedValues": ["yoy"],
            "requiredAction": (
                "删除 rejectedValue，只保留 allowedValues；省略 comparisonRoles 表示继承请求范围"
            ),
        }
    ]


def test_分析计划合并同一物理表重复需求并重写分析引用():
    def requirement(requirement_id: str, measures: list[str], grain: list[str]):
        return QueryRequirement.model_validate(
            {
                "requirementId": requirement_id,
                "sourceId": "operations",
                "tables": [
                    {
                        "table": "reporting.income",
                        "periodColumn": "month",
                        "periodGranularity": "date",
                        "measureColumns": measures,
                    }
                ],
                "dimensionColumns": grain,
                "grainColumns": grain,
            }
        )

    first = requirement("income-area", ["amount"], ["month", "campus"])
    duplicate = requirement("income-dept", ["amount", "visits"], ["month", "department"])
    bundle = AnalysisBundle(
        analyses=(
            AnalysisItem(
                code="income",
                description="收入分析",
                requirementIds=(first.requirement_id, duplicate.requirement_id),
            ),
        ),
        requirements=(first, duplicate),
    )

    normalized, repairs = _normalize_duplicate_requirements(bundle)

    assert repairs == [
        {
            "removedRequirementId": "income-dept",
            "canonicalRequirementId": "income-area",
            "table": "reporting.income",
        }
    ]
    assert [item.requirement_id for item in normalized.requirements] == ["income-area"]
    assert normalized.requirements[0].tables[0].measure_columns == ("amount", "visits")
    assert normalized.requirements[0].dimension_columns == ("month", "campus", "department")
    assert normalized.analyses[0].requirement_ids == ("income-area",)


def test_分析计划将快照外维度和粒度定点反馈给模型():
    requirement = query_requirement(grain_columns=("month", "company"))
    bundle = AnalysisBundle.model_validate(
        {
            "analyses": [
                {
                    "code": "income",
                    "description": "收入分析",
                    "requirementIds": [requirement.requirement_id],
                }
            ],
            "requirements": [requirement.model_dump(mode="json", by_alias=True)],
        }
    )
    understanding = DataUnderstandingPlan.model_validate(valid_data_understanding_output())

    issues = _analysis_bundle_semantic_issues(bundle, understanding, approval_snapshots())

    assert issues == [
        {
            "path": "requirements[0].dimensionColumns",
            "rejectedValue": ["company"],
            "reason": "dimensionColumns 引用了 requirement 数据表结构快照中不存在的字段",
            "allowedValues": ["amount", "campus", "month"],
            "requiredAction": "删除或替换 rejectedValue，保留其他有效维度",
        },
        {
            "path": "requirements[0].grainColumns",
            "rejectedValue": ["company"],
            "reason": "grainColumns 引用了当前表结构快照中不存在的字段",
            "allowedValues": ["amount", "campus", "month"],
            "requiredAction": "删除或替换 rejectedValue，保留其他有效粒度",
        },
    ]
    assert _analysis_allowed_mutation_paths(issues) == (
        "requirements[0].dimensionColumns",
        "requirements[0].grainColumns",
    )


@pytest.mark.anyio
async def test_分析计划快照外字段纠错只允许修改对应维度和粒度():
    invalid_requirement = query_requirement(grain_columns=("month", "company"))
    valid_requirement = invalid_requirement.model_copy(
        update={"dimension_columns": ("month",), "grain_columns": ("month",)}
    )
    invalid = AnalysisBundle.model_validate(
        {
            "analyses": [
                {
                    "code": "income",
                    "description": "收入分析",
                    "requirementIds": [invalid_requirement.requirement_id],
                }
            ],
            "requirements": [invalid_requirement.model_dump(mode="json", by_alias=True)],
        }
    )
    valid = invalid.model_copy(update={"requirements": (valid_requirement,)})
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._analysis_agent = SimpleNamespace(id="analysis-planner")

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        return invalid if len(captured) == 1 else valid

    runtime._run_planner = run_planner
    context = data_understanding_context()
    state = context.session_state
    state[REPORT_OUTLINE_STATE_KEY] = {
        "title": "运营分析",
        "sections": ["收入分析"],
        "assumptions": [],
    }
    state[REPORT_OUTLINE_CONTEXT_STATE_KEY] = {}
    state[REPORT_DATA_UNDERSTANDING_STATE_KEY] = valid_data_understanding_output()

    await runtime.generate_analysis_plan(StepInput(input=envelope()), context)

    correction = captured[1]["correction"]
    assert correction["previousOutput"] == invalid.model_dump(mode="json", by_alias=True)
    assert correction["allowedMutationPaths"] == [
        "requirements[0].dimensionColumns",
        "requirements[0].grainColumns",
    ]
    assert [issue["rejectedValue"] for issue in correction["validationFeedback"]["issues"]] == [
        ["company"],
        ["company"],
    ]
    assert state[REPORT_DATA_REQUIREMENTS_STATE_KEY] == [
        valid_requirement.model_dump(mode="json", by_alias=True)
    ]


def test_分析计划将快照外指标定点反馈给模型():
    requirement = query_requirement(
        tables=[
            {
                "table": "reporting.income",
                "periodColumn": "month",
                "measureColumns": ["amount", "invented_amount"],
            }
        ]
    )
    bundle = AnalysisBundle.model_validate(
        {
            "analyses": [
                {
                    "code": "income",
                    "description": "收入分析",
                    "requirementIds": [requirement.requirement_id],
                }
            ],
            "requirements": [requirement.model_dump(mode="json", by_alias=True)],
        }
    )
    understanding = DataUnderstandingPlan.model_validate(valid_data_understanding_output())

    issues = _analysis_bundle_semantic_issues(bundle, understanding, approval_snapshots())

    assert issues == [
        {
            "path": "requirements[0].tables[0].measureColumns",
            "rejectedValue": ["invented_amount"],
            "reason": "measureColumns 引用了当前表结构快照中不存在的字段",
            "allowedValues": ["amount"],
            "requiredAction": "删除 rejectedValue，或从 allowedValues 选择真实数值指标字段",
        }
    ]


def test_分析计划将非数值指标定点反馈给模型():
    requirement = QueryRequirement.model_validate(
        {
            "requirementId": "income-monthly",
            "sourceId": "operations",
            "tables": [
                {
                    "table": "reporting.income",
                    "periodColumn": "month",
                    "periodGranularity": "date",
                    "measureColumns": ["amount", "campus"],
                }
            ],
            "dimensionColumns": ["month", "campus"],
            "grainColumns": ["month", "campus"],
            "relations": [],
        }
    )
    bundle = AnalysisBundle.model_validate(
        {
            "analyses": [
                {
                    "code": "income",
                    "description": "收入分析",
                    "requirementIds": [requirement.requirement_id],
                }
            ],
            "requirements": [requirement.model_dump(mode="json", by_alias=True)],
        }
    )
    understanding = DataUnderstandingPlan.model_validate(valid_data_understanding_output())

    issues = _analysis_bundle_semantic_issues(bundle, understanding, approval_snapshots())

    assert len(issues) == 1
    assert issues[0]["path"] == "requirements[0].tables[0].measureColumns"
    assert issues[0]["rejectedValue"] == [{"column": "campus", "dataType": "VARCHAR(100)"}]
    assert issues[0]["allowedValues"] == ["amount"]
    assert "可聚合数值字段" in issues[0]["requiredAction"]


def test_分析计划将数值指标与维度重叠定点反馈到维度路径():
    requirement = QueryRequirement.model_validate(
        {
            "requirementId": "income-monthly",
            "sourceId": "operations",
            "tables": [
                {
                    "table": "reporting.income",
                    "periodColumn": "month",
                    "periodGranularity": "date",
                    "measureColumns": ["amount"],
                }
            ],
            "dimensionColumns": ["month", "campus", "amount"],
            "grainColumns": ["month", "campus"],
            "relations": [],
        }
    )
    bundle = AnalysisBundle.model_validate(
        {
            "analyses": [
                {
                    "code": "income",
                    "description": "收入分析",
                    "requirementIds": [requirement.requirement_id],
                }
            ],
            "requirements": [requirement.model_dump(mode="json", by_alias=True)],
        }
    )
    understanding = DataUnderstandingPlan.model_validate(valid_data_understanding_output())

    issues = _analysis_bundle_semantic_issues(bundle, understanding, approval_snapshots())

    assert issues == [
        {
            "path": "requirements[0].dimensionColumns",
            "rejectedValue": ["amount"],
            "reason": "数值指标不能同时声明为 measureColumns 和 dimensionColumns",
            "allowedValues": ["month", "campus"],
            "requiredAction": "从 dimensionColumns 删除 rejectedValue，保留原有其他维度",
        }
    ]
    assert _analysis_allowed_mutation_paths(issues) == ("requirements[0].dimensionColumns",)


@pytest.mark.anyio
async def test_sql审核错误会按查询路径反馈模型纠错(tmp_path: Path):
    requirement = query_requirement()
    invalid_output = {
        "queries": [
            {
                "requirementId": requirement.requirement_id,
                "sourceId": "operations",
                "sql": (
                    "SELECT month, SUM(amount) AS amount FROM reporting.income "
                    "WHERE month BETWEEN '2024-01-01' AND '2024-12-31' GROUP BY month"
                ),
            }
        ]
    }
    valid_output = {
        "queries": [
            {
                **invalid_output["queries"][0],
                "sql": (
                    "SELECT month, SUM(amount) AS amount FROM reporting.income "
                    "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY month"
                ),
            }
        ]
    }
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._sql_agent = object()
    source = source_config(tmp_path)
    runtime._sources = lambda _run_context: (source,)

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        output = invalid_output if len(captured) == 1 else valid_output
        return GeneratedQueryBatch.model_validate(output)

    runtime._run_planner = run_planner
    context = data_understanding_context()
    state = context.session_state
    state[REPORT_DATA_UNDERSTANDING_STATE_KEY] = valid_data_understanding_output()
    state[REPORT_DATA_REQUIREMENTS_STATE_KEY] = [requirement.model_dump(mode="json", by_alias=True)]

    await runtime.generate_query_candidates(StepInput(input=envelope()), context)

    assert len(captured) == 2
    assert [table["table"] for schema in captured[0]["schemas"] for table in schema["tables"]] == [
        "reporting.income"
    ]
    correction = captured[1]["correction"]
    assert "previousOutput" not in correction
    issue = correction["validationFeedback"]["issues"][0]
    assert issue["path"] == "queries[0].sql"
    assert "report_query_period_invalid" in issue["reason"]
    assert issue["expectedPeriodPredicates"] == [
        "reporting.income.month BETWEEN '2025-01-01' AND '2025-12-31'"
    ]
    assert "expectedPeriodPredicates" in issue["requiredAction"]
    assert state[REPORT_APPROVED_QUERIES_STATE_KEY][0]["requirementId"] == "income-monthly"


@pytest.mark.anyio
async def test_sql粒度错误反馈明确区分grain和dimension(tmp_path: Path):
    requirement = QueryRequirement.model_validate(
        {
            "requirementId": "income-monthly",
            "sourceId": "operations",
            "tables": [
                {
                    "table": "reporting.income",
                    "periodColumn": "month",
                    "periodGranularity": "date",
                    "measureColumns": ["amount"],
                }
            ],
            "dimensionColumns": ["month", "campus"],
            "grainColumns": ["month"],
            "relations": [],
        }
    )
    invalid_sql = (
        "SELECT month, campus, SUM(amount) AS amount FROM reporting.income "
        "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY month, campus"
    )
    valid_sql = (
        "SELECT month, SUM(amount) AS amount FROM reporting.income "
        "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY month"
    )
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._sql_agent = object()
    runtime._sources = lambda _run_context: (source_config(tmp_path),)

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        return GeneratedQueryBatch.model_validate(
            {
                "queries": [
                    {
                        "requirementId": requirement.requirement_id,
                        "sourceId": "operations",
                        "sql": invalid_sql if len(captured) == 1 else valid_sql,
                    }
                ]
            }
        )

    runtime._run_planner = run_planner
    context = data_understanding_context()
    context.session_state[REPORT_DATA_UNDERSTANDING_STATE_KEY] = valid_data_understanding_output()
    context.session_state[REPORT_DATA_REQUIREMENTS_STATE_KEY] = [
        requirement.model_dump(mode="json", by_alias=True)
    ]

    await runtime.generate_query_candidates(StepInput(input=envelope()), context)

    issue = captured[1]["correction"]["validationFeedback"]["issues"][0]
    assert issue["rejectedValue"] == invalid_sql
    assert issue["expectedGrainColumns"] == ["month"]
    assert "不得把 dimensionColumns 全量带入" in issue["requiredAction"]


@pytest.mark.anyio
async def test_数据理解持续失败最多调用模型五次并返回最后诊断():
    invalid_output = {"tables": []}
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._data_understanding_agent = object()

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        return invalid_output

    runtime._run_planner = run_planner

    with pytest.raises(ReportingError) as rejected:
        await runtime.plan_data_scope(StepInput(input=envelope()), data_understanding_context())

    assert rejected.value.code == "report_data_understanding_invalid"
    assert len(captured) == 5
    assert [payload.get("correction", {}).get("attempt") for payload in captured] == [
        None,
        2,
        3,
        4,
        5,
    ]
    assert "连续五次" in rejected.value.message
    assert '"validationFeedback"' in rejected.value.message
    assert '"path":"tables"' in rejected.value.message


@pytest.mark.anyio
async def test_数据理解基础设施错误不进入模型纠错():
    calls = 0
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._data_understanding_agent = object()

    async def run_planner(_agent, _payload, _run_context):
        nonlocal calls
        calls += 1
        raise ReportingError("report_planner_unavailable", "模型服务不可用。")

    runtime._run_planner = run_planner

    with pytest.raises(ReportingError) as rejected:
        await runtime.plan_data_scope(StepInput(input=envelope()), data_understanding_context())

    assert rejected.value.code == "report_planner_unavailable"
    assert calls == 1


@pytest.mark.anyio
async def test_动态提纲只接收冻结分析且code由服务端生成():
    captured: dict[str, object] = {}
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._outline_agent = object()

    async def run_planner(_agent, payload, _run_context):
        captured.update(payload)
        return ReportOutlineProposal(
            reportType="comprehensive",
            title="2025年综合运营报告",
            sections=(
                OutlineSectionProposal(
                    title="收入趋势与异常",
                    focus=("核对收入趋势和异常月份",),
                    analysisIds=("analysis_001",),
                ),
            ),
        )

    runtime._run_planner = run_planner
    profile = resolve_reporting_profile(
        ReportingProfileRegistry(documents={}, config_paths=()), None
    )
    context = RunContext(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        session_state={
            REPORT_WORKFLOW_INPUT_STATE_KEY: envelope().workflow_payload(
                default_source_ids=("operations",)
            ),
            REPORT_SCHEMA_SNAPSHOTS_STATE_KEY: [],
            REPORT_EFFECTIVE_PROFILE_STATE_KEY: profile.model_dump(mode="json", by_alias=True),
            REPORT_REQUEST_CONTEXT_STATE_KEY: {"originalGoal": "分析经营情况", "feedback": []},
            REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY: {
                "datasetIds": ["dataset-income"],
                "analyses": [
                    {
                        "analysisId": "analysis_001",
                        "domain": "income",
                        "managementQuestion": "收入规模与期间变化形成管理判断。",
                        "datasetIds": ["dataset-income"],
                        "fields": ["amount"],
                        "metrics": ["amount"],
                        "periods": ["2025-01"],
                        "actions": ["规模分析"],
                        "evidenceSummary": "CSV 已完成全量画像。",
                        "suggestedSection": "收入分析",
                        "completionConditions": ["覆盖数据集"],
                    }
                ],
            },
        },
    )

    output = await runtime.generate_outline(StepInput(input=envelope()), context)

    assert set(captured) == {"reportGoal", "reportType", "period", "outlineContext", "feedback"}
    outline_context = captured["outlineContext"]
    assert isinstance(outline_context, dict)
    assert [item["analysisId"] for item in outline_context["analyses"]] == ["analysis_001"]
    assert "fixedSections" not in outline_context
    assert "structuralSchemas" not in outline_context
    assert [section.code for section in output.content.sections] == ["section_001"]
    assert output.content.sections[0].analysis_ids == ("analysis_001",)


def test_提纲顶层章节不再由profile决定():
    profile = resolve_reporting_profile(
        ReportingProfileRegistry(documents={}, config_paths=()), None
    )
    outline = make_outline("comprehensive", title="运营分析报告")

    assert _outline_section_issues(outline, profile) == []
    assert [item.code for item in outline.sections] == [
        "operation_overview",
        "income",
        "workload",
        "budget",
        "full_cost",
        "cost_control",
        "funds",
        "cross_domain",
        "risk_and_data_quality",
        "management_actions",
    ]


def test_模型纠错反馈限制拒绝值大小但保留允许值和修复动作():
    feedback = {
        "code": "invalid",
        "issues": [
            {
                "path": "items",
                "rejectedValue": [f"bad-{index}" for index in range(100)],
                "allowedValues": [f"allowed-{index}" for index in range(30)],
                "reason": "字段无效",
                "requiredAction": "从允许值中选择并返回完整 JSON",
            }
        ],
    }

    compact = _compact_validation_feedback(feedback)

    assert compact is not None
    issue = compact["issues"][0]
    assert issue["rejectedValue"][-1] == {"__truncated__": {"omittedItems": 92}}
    assert issue["allowedValues"] == feedback["issues"][0]["allowedValues"]
    assert issue["requiredAction"] == "从允许值中选择并返回完整 JSON"


@pytest.mark.parametrize(
    "title",
    [
        '{"displayCoverpage": false, "pageSize": "A4"}',
        '"displayCoverpage": false, "pageSize": "A4"',
        'displayCoverpage\\": false, pageSize\\": \\"A4\\"',
    ],
)
def test_提纲章节标题拒绝json或配置序列化片段(title: str):
    with pytest.raises(ValueError):
        ReportOutlineSection(code="income", title=title)


def test_提纲章节允许正常中文标题和标点():
    sections = make_outline("comprehensive", title="占位").sections
    outline = ReportOutline(
        reportType="comprehensive",
        title="2025年运营分析报告",
        sections=sections,
        assumptions=("分析期间为2025年。",),
    )

    assert outline.title == "2025年运营分析报告"
    assert outline.sections[7].title == "跨域运营分析"


def test_提纲拒绝孤立标点前缀但允许句内标点():
    with pytest.raises(ValueError):
        ReportOutlineSection(code="income", title=": 收入分析")

    section = ReportOutlineSection(code="risk_and_data_quality", title="结论：风险与建议")

    assert section.title == "结论：风险与建议"


def test_提纲假设拒绝填补缺失数据但允许如实披露():
    sections = make_outline("comprehensive", title="占位").sections
    with pytest.raises(ValueError):
        ReportOutline(
            reportType="comprehensive",
            title="运营分析报告",
            sections=sections,
            assumptions=("缺失月份按趋势估算或视为未发生",),
        )

    outline = ReportOutline(
        reportType="comprehensive",
        title="运营分析报告",
        sections=sections,
        assumptions=("2025年12月数据缺失，报告仅披露可用期间，不进行估算。",),
    )

    assert outline.assumptions == ("2025年12月数据缺失，报告仅披露可用期间，不进行估算。",)


@pytest.mark.parametrize(
    "assumption",
    (
        "应完成收入基于去年同期收入与预算的比例推算。",
        "将全年结果年化后展示。",
        "对月度波动进行平滑处理。",
        "采用拟合值补齐尚未发生的月份。",
    ),
)
def test_提纲假设拒绝任何派生或拟合数据(assumption: str):
    with pytest.raises(ValueError, match="不得拟合、估算、推算、插值、外推、年化、平滑或补齐数据"):
        ReportOutline(
            reportType="comprehensive",
            title="运营分析报告",
            sections=make_outline("comprehensive", title="占位").sections,
            assumptions=(assumption,),
        )


def test_分析描述拒绝派生数据但允许否定披露():
    with pytest.raises(ValueError, match="不得拟合、估算、推算、插值、外推、年化、平滑或补齐数据"):
        AnalysisItem(code="income", description="根据去年同期比例推算收入", requirementIds=("r1",))

    item = AnalysisItem(
        code="income",
        description="只分析观测值，不进行估算或年化",
        requirementIds=("r1",),
    )

    assert item.description == "只分析观测值，不进行估算或年化"


@pytest.mark.anyio
async def test_规划器严格解析保留污染字段供模型纠错(caplog):
    caplog.set_level("INFO", logger="agentos_dev.coding.reporting.workflow.runtime")
    payload = make_outline("comprehensive", title="运营分析报告").model_dump(
        mode="json", by_alias=True
    )
    payload["sections"].append(
        {"code": "correction_applied_clean", "title": "correctionAppliedClean: true"}
    )
    raw = json.dumps(payload)

    class FakeAgent:
        id = "strict-planner"
        output_schema = ReportOutline

        async def arun(self, *_args, **_kwargs):
            return SimpleNamespace(
                content=raw,
                metrics=SimpleNamespace(
                    input_tokens=100,
                    output_tokens=20,
                    total_tokens=120,
                    cache_read_tokens=80,
                    cache_write_tokens=0,
                    reasoning_tokens=10,
                    duration=1.25,
                    time_to_first_token=0.5,
                ),
            )

    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._scope = lambda _context: {"userId": "user-1"}
    context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    with pytest.raises(_PlannerOutputValidationError) as captured:
        await runtime._run_planner(FakeAgent(), {}, context)

    assert captured.value.output["sections"][-1]["title"] == "correctionAppliedClean: true"
    assert captured.value.issues[0]["path"] == "sections[10].title"
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "report_planner_request" in messages
    assert "report_planner_response" in messages
    assert "cache_read_tokens=80" in messages
    assert "report_planner_validation_failed" in messages


@pytest.mark.anyio
@pytest.mark.parametrize("wrapper", ["fence", "encoded"])
async def test_规划器只弱解包完整结构化JSON(wrapper: str):
    expected = make_outline("comprehensive", title="运营分析报告")
    raw = json.dumps(
        expected.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
    )
    content = f"```json\n{raw}\n```" if wrapper == "fence" else json.dumps(raw)

    class FakeAgent:
        id = "strict-planner"
        output_schema = ReportOutline

        async def arun(self, *_args, **_kwargs):
            return SimpleNamespace(content=content, metrics=None)

    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._scope = lambda _context: {"userId": "user-1"}
    context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    output = await runtime._run_planner(FakeAgent(), {}, context)

    assert output == expected


@pytest.mark.anyio
async def test_规划器超时返回稳定错误且不进入结构纠错():
    class TimeoutAgent:
        id = "analysis-planner"
        model = SimpleNamespace(timeout=180)
        output_schema = ReportOutline

        async def arun(self, *_args, **_kwargs):
            raise TimeoutError

    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._scope = lambda _context: {"userId": "user-1"}
    context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    with pytest.raises(ReportingError) as captured:
        await runtime._run_planner(TimeoutAgent(), {}, context)

    assert captured.value.code == "report_planner_timeout"
    assert "180 秒" in captured.value.message
    assert "analysis-planner" in captured.value.message


@pytest.mark.anyio
async def test_规划器上下文硬上限作为确定性错误只执行一次():
    calls = 0

    class HardLimitAgent:
        id = "detailed-analysis-planner"
        output_schema = ReportOutline

        async def arun(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            return SimpleNamespace(
                content="不可约简的编码上下文前缀与工具 schema 超过模型输入 hard cap。",
                metrics=None,
            )

    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._scope = lambda _context: {"userId": "user-1"}
    context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    with pytest.raises(ReportingError) as captured:
        await runtime._run_planner(HardLimitAgent(), {}, context)

    assert captured.value.code == "report_planner_context_budget_exceeded"
    assert calls == 1


@pytest.mark.parametrize("field", ["host", "username", "password", "dsn", "databaseUrl"])
def test_envelope任何层级出现连接字段均返回稳定错误(field: str):
    with pytest.raises(ReportingError) as captured:
        envelope(schemaInput={field: "secret"})
    assert captured.value.code == "report_connection_input_forbidden"


def test_agui提取envelope和ddl后从模型上下文删除():
    ddl = "CREATE TABLE reporting.income (month DATE NOT NULL);"
    run_input = RunAgentInput.model_validate(
        {
            "threadId": "thread-1",
            "runId": "run-1",
            "state": {},
            "messages": [
                {
                    "id": "message-1",
                    "role": "user",
                    "content": f"```json\n{envelope().model_dump_json(by_alias=True)}\n```\n```sql\n{ddl}\n```",
                }
            ],
            "tools": [],
            "context": [],
            "forwardedProps": {},
        }
    )

    prepared = prepare_agui_envelope(run_input)

    assert prepared.envelope.schema_input is not None
    assert prepared.envelope.schema_input.ddl == ddl
    assert ddl not in repr(prepared.run_input)
    assert "分析经营情况" in str(prepared.run_input.messages[-1].content)


def test_agent分流覆盖零个一个多个和显式选择():
    empty = AgentQueryResponse(agents=())
    assert select_reporting_agent(empty, None) is None
    one = AgentQueryResponse.model_validate(
        {
            "agents": [
                {
                    "code": "1",
                    "name": "A",
                    "description": "",
                    "enabled": True,
                }
            ],
        }
    )
    assert select_reporting_agent(one, None).code == "1"  # type: ignore[union-attr]
    multiple = AgentQueryResponse(
        agents=one.agents + (one.agents[0].model_copy(update={"code": "2", "name": "B"}),),
    )
    selected = select_reporting_agent(multiple, "2")
    assert selected.code == "2"  # type: ignore[union-attr]
    pending = select_reporting_agent(multiple, None)
    assert isinstance(pending, tuple) and len(pending) == 2


@pytest.mark.anyio
async def test_metadata故障不会降级为零agent():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "unavailable"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://metadata.internal"
    )
    service = ReportingMetadataClient("https://metadata.internal", client_factory=lambda: client)
    try:
        with pytest.raises(ReportingError) as captured:
            await service.query_agents(("operations",))
        assert captured.value.code == "report_metadata_unavailable"
    finally:
        await client.aclose()


def test_api与ddl冲突但字段类型以实时catalog为准(tmp_path: Path):
    source = source_config(tmp_path)
    api_tables = tables(nullable=False)
    metadata = ModelTermsResponse(
        revision="m1",
        schemaHash=schema_hash(api_tables),
        sourceRefs=({"sourceId": "operations"},),
        ddlModels=raw_ddl_models(),
        tables=api_tables,
        terms=(),
    )
    conflicting = envelope(schemaInput={"ddl": "CREATE TABLE reporting.income (month DATE);"})
    with pytest.raises(ReportingError) as conflict:
        resolve_schema_snapshot(
            conflicting,
            source=source,
            metadata=metadata,
            catalog=api_tables,
        )
    assert conflict.value.code == "report_schema_conflict"

    valid = envelope()
    incompatible_catalog = (
        api_tables[0].model_copy(
            update={"columns": (ModelColumn(name="month", dataType="INT", nullable=True),)}
        ),
    )
    snapshot = resolve_schema_snapshot(
        valid,
        source=source,
        metadata=metadata,
        catalog=incompatible_catalog,
    )
    assert snapshot.tables[0].columns == (ModelColumn(name="month", dataType="INT", nullable=True),)
    assert snapshot.schema_hash == schema_hash(snapshot.tables)

    missing_column_catalog = (
        api_tables[0].model_copy(
            update={"columns": (ModelColumn(name="other", dataType="INT", nullable=True),)}
        ),
    )
    with pytest.raises(ReportingError) as drift:
        resolve_schema_snapshot(
            valid,
            source=source,
            metadata=metadata,
            catalog=missing_column_catalog,
        )
    assert drift.value.code == "report_catalog_drift"

    catalog_with_extra = (
        api_tables[0].model_copy(
            update={
                "columns": api_tables[0].columns
                + (ModelColumn(name="unexpected", dataType="INT", nullable=True),)
            }
        ),
    )
    snapshot = resolve_schema_snapshot(
        valid,
        source=source,
        metadata=metadata,
        catalog=catalog_with_extra,
    )
    assert snapshot.tables == api_tables


def test_catalog允许decimal使用默认精度(tmp_path: Path):
    source = source_config(tmp_path)
    metadata_table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="income",
        columns=(ModelColumn(name="amount", dataType="DECIMAL", nullable=True),),
    )
    metadata = ModelTermsResponse(
        revision="m1",
        schemaHash=schema_hash((metadata_table,)),
        sourceRefs=({"sourceId": "operations"},),
        ddlModels=(
            RawDdlModel(
                id=1,
                modelName="income",
                modelDesc="收入模型",
                ddl="CREATE TABLE reporting.income (amount DECIMAL)",
            ),
        ),
        tables=(metadata_table,),
        terms=(),
    )
    default_decimal_catalog = (
        metadata_table.model_copy(
            update={
                "columns": (ModelColumn(name="amount", dataType="DECIMAL(10, 0)", nullable=True),)
            }
        ),
    )

    snapshot = resolve_schema_snapshot(
        envelope(),
        source=source,
        metadata=metadata,
        catalog=default_decimal_catalog,
    )

    assert snapshot.tables == default_decimal_catalog


def test_catalog不因decimal精度差异阻断工作流(tmp_path: Path):
    source = source_config(tmp_path)
    metadata_table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="income",
        columns=(ModelColumn(name="amount", dataType="DECIMAL(10,2)", nullable=True),),
    )
    metadata = ModelTermsResponse(
        revision="m1",
        schemaHash=schema_hash((metadata_table,)),
        sourceRefs=({"sourceId": "operations"},),
        ddlModels=(
            RawDdlModel(
                id=1,
                modelName="income",
                modelDesc="收入模型",
                ddl="CREATE TABLE reporting.income (amount DECIMAL(10,2))",
            ),
        ),
        tables=(metadata_table,),
        terms=(),
    )
    different_catalog = (
        metadata_table.model_copy(
            update={
                "columns": (ModelColumn(name="amount", dataType="DECIMAL(10,0)", nullable=True),)
            }
        ),
    )

    snapshot = resolve_schema_snapshot(
        envelope(),
        source=source,
        metadata=metadata,
        catalog=different_catalog,
    )

    assert snapshot.tables == different_catalog


def test_metadata术语保存在通用结构快照(tmp_path: Path):
    source = source_config(tmp_path)
    api_tables = tables()
    term = ModelTerm(
        code="actual_amount",
        name="实际金额",
        kind="measure",
        fieldRefs=("operations.reporting.income.month",),
    )
    metadata = ModelTermsResponse(
        revision="m1",
        schemaHash=schema_hash(api_tables),
        sourceRefs=({"sourceId": "operations"},),
        ddlModels=raw_ddl_models(),
        tables=api_tables,
        terms=(term,),
    )

    snapshot = resolve_schema_snapshot(
        envelope(),
        source=source,
        metadata=metadata,
        catalog=api_tables,
    )

    assert snapshot.terms == (term,)


def test_metadata与profile指标语义一致时去重且冲突时失败关闭(tmp_path: Path):
    source = source_config(tmp_path)
    api_tables = (
        ModelTable(
            sourceId="operations",
            database="reporting",
            name="income",
            columns=(ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),),
        ),
    )
    raw = (
        RawDdlModel(
            id=1,
            modelName="income",
            modelDesc="收入模型",
            ddl="CREATE TABLE reporting.income (amount DECIMAL(18,2))",
        ),
    )
    semantic = MeasureSemantic(
        fieldRef="operations.reporting.income.amount",
        aggregation="sum",
    )
    metadata = ModelTermsResponse(
        revision="m1",
        schemaHash=schema_hash(api_tables),
        sourceRefs=({"sourceId": "operations"},),
        ddlModels=raw,
        tables=api_tables,
        terms=(),
        measureSemantics=(semantic,),
    )

    snapshot = resolve_schema_snapshot(
        envelope(),
        source=source,
        metadata=metadata,
        catalog=api_tables,
        profile_measure_semantics=(semantic,),
    )
    assert snapshot.measure_semantics == (semantic,)

    with pytest.raises(ReportingError) as conflict:
        resolve_schema_snapshot(
            envelope(),
            source=source,
            metadata=metadata,
            catalog=api_tables,
            profile_measure_semantics=(semantic.model_copy(update={"aggregation": "average"}),),
        )
    assert conflict.value.code == "report_measure_semantic_conflict"


def test_ddl_fallback使用profile指标语义(tmp_path: Path):
    source = source_config(tmp_path)
    ddl = "CREATE TABLE reporting.income (month DATE, amount DECIMAL(18,2));"
    catalog = (
        ModelTable(
            sourceId="operations",
            database="reporting",
            name="income",
            columns=(
                ModelColumn(name="month", dataType="DATE", nullable=True),
                ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
            ),
        ),
    )
    semantic = MeasureSemantic(
        fieldRef="operations.reporting.income.amount",
        aggregation="sum",
        additiveAcross=("month",),
    )

    snapshot = resolve_schema_snapshot(
        envelope(schemaInput={"ddl": ddl}),
        source=source,
        metadata=None,
        catalog=catalog,
        profile_measure_semantics=(semantic,),
    )

    assert snapshot.source == "ddl"
    assert snapshot.measure_semantics == (semantic,)


@pytest.mark.anyio
async def test_ddl解析后不进入workflow_state(tmp_path: Path, monkeypatch):
    source = source_config(tmp_path)
    ddl = "CREATE TABLE reporting.income (month DATE NOT NULL);"

    class FakeAdapter:
        def __init__(self, _source, *, allowed_tables=()):
            self.allowed_tables = allowed_tables
            pass

        async def catalog(self):
            return (
                SimpleNamespace(
                    source_id="operations",
                    database="reporting",
                    name="income",
                    columns=(SimpleNamespace(name="month", data_type="DATE", nullable=False),),
                ),
            )

        async def aclose(self):
            return None

    monkeypatch.setattr(
        "agentos_dev.coding.reporting.workflow.runtime.StarRocksDataSourceAdapter", FakeAdapter
    )
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.registry = SimpleNamespace(
        sources={"operations": source}, default_source_ids=("operations",)
    )
    runtime.profiles = ReportingProfileRegistry(documents={}, config_paths=())
    runtime.metadata_client = None
    state = {}
    context = RunContext(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        session_state=state,
    )

    await runtime.confirm_source(
        StepInput(input=envelope(schemaInput={"ddl": ddl})),
        context,
    )

    assert "schemaInput" not in state[REPORT_WORKFLOW_INPUT_STATE_KEY]
    assert REPORT_SCHEMA_SNAPSHOTS_STATE_KEY in state
    assert "CREATE TABLE" not in repr(state)


@pytest.mark.anyio
async def test_多个metadata_agent先暂停展示再在同一步继续(tmp_path: Path, monkeypatch):
    source = source_config(tmp_path)
    model_tables = tables()
    agents = AgentQueryResponse.model_validate(
        {
            "agents": [
                {
                    "code": code,
                    "name": name,
                    "description": "",
                    "enabled": True,
                }
                for code, name in (("1", "Agent A"), ("2", "Agent B"))
            ],
        }
    )
    metadata = ModelTermsResponse(
        revision="model-r1",
        schemaHash=schema_hash(model_tables),
        sourceRefs=({"sourceId": "operations"},),
        ddlModels=raw_ddl_models(),
        tables=model_tables,
        terms=(),
    )

    class FakeMetadata:
        async def query_agents(self, _source_ids):
            return agents

        async def query_model(self, *, agent_id, sources):
            assert agent_id == "2"
            assert tuple(item.id for item in sources) == ("operations",)
            return metadata

    class FakeAdapter:
        def __init__(self, _source, *, allowed_tables=()):
            self.allowed_tables = allowed_tables
            pass

        async def catalog(self):
            return (
                SimpleNamespace(
                    source_id="operations",
                    database="reporting",
                    name="income",
                    columns=(SimpleNamespace(name="month", data_type="DATE", nullable=False),),
                ),
            )

        async def aclose(self):
            return None

    monkeypatch.setattr(
        "agentos_dev.coding.reporting.workflow.runtime.StarRocksDataSourceAdapter", FakeAdapter
    )
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.registry = SimpleNamespace(
        sources={"operations": source}, default_source_ids=("operations",)
    )
    runtime.profiles = ReportingProfileRegistry(documents={}, config_paths=())
    runtime.metadata_client = FakeMetadata()
    state = {}
    context = RunContext(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        session_state=state,
    )

    pending = await runtime.confirm_source(StepInput(input=envelope()), context)
    confirmed = await runtime.confirm_source(
        StepInput(
            input=envelope(),
            additional_data={"rejection_feedback": "agentId:2"},
        ),
        context,
    )

    assert [item["code"] for item in pending.content["agents"]] == ["1", "2"]
    assert confirmed.content["sources"][0]["sourceId"] == "operations"
    assert state[REPORT_WORKFLOW_INPUT_STATE_KEY]["agentId"] == "2"


def test_sql审核后只允许执行完全相同的原文(tmp_path: Path):
    source = source_config(tmp_path)
    requirement = QueryRequirement.model_validate(
        {
            "requirementId": "income-monthly",
            "sourceId": "operations",
            "tables": [
                {
                    "table": "reporting.income",
                    "periodColumn": "month",
                    "periodGranularity": "date",
                    "measureColumns": ["amount"],
                }
            ],
            "dimensionColumns": ["month"],
            "grainColumns": ["month"],
        }
    )
    (approved,) = approve_query_batch(
        [
            {
                "requirementId": "income-monthly",
                "sourceId": "operations",
                "sql": (
                    "SELECT month, SUM(amount) AS amount FROM reporting.income "
                    "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY month"
                ),
            }
        ],
        sources={"operations": source},
        snapshots=approval_snapshots(),
        envelope=envelope(),
        requirements=(requirement,),
    )

    assert require_approved_sql(approved, approved.sql) == approved.sql
    with pytest.raises(ReportingError) as changed:
        require_approved_sql(approved, f"{approved.sql};")
    assert changed.value.code == "report_sql_hash_mismatch"


def test_重复冲突探测查询保留原始行且拒绝提前sum(tmp_path: Path):
    source = source_config(tmp_path)
    requirement = QueryRequirement.model_validate(
        {
            "requirementId": "income-monthly",
            "sourceId": "operations",
            "tables": [
                {
                    "table": "reporting.income",
                    "periodColumn": "month",
                    "periodGranularity": "date",
                    "measureColumns": ["amount"],
                }
            ],
            "dimensionColumns": ["month", "campus"],
            "grainColumns": ["month", "campus"],
        }
    )
    raw_sql = (
        "SELECT month, campus, amount FROM reporting.income "
        "WHERE month BETWEEN '2025-01-01' AND '2025-12-31'"
    )

    (approved,) = approve_query_batch(
        [{"requirementId": "income-monthly", "sourceId": "operations", "sql": raw_sql}],
        sources={"operations": source},
        snapshots=approval_snapshots(),
        envelope=envelope(),
        requirements=(requirement,),
        row_preserving_requirement_ids=("income-monthly",),
    )
    assert approved.sql == raw_sql

    with pytest.raises(ReportingError) as captured:
        approve_query_batch(
            [
                {
                    "requirementId": "income-monthly",
                    "sourceId": "operations",
                    "sql": (
                        "SELECT month, campus, SUM(amount) AS amount FROM reporting.income "
                        "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' "
                        "GROUP BY month, campus"
                    ),
                }
            ],
            sources={"operations": source},
            snapshots=approval_snapshots(),
            envelope=envelope(),
            requirements=(requirement,),
            row_preserving_requirement_ids=("income-monthly",),
        )
    assert captured.value.code == "report_query_row_preserving_invalid"


def test_原始行权限只由profile受治理项目表自动签发():
    project = QueryRequirement.model_validate(
        {
            "requirementId": "project-budget-probe",
            "sourceId": "rj",
            "tables": [
                {
                    "table": "rj.dwd_project_budget_view",
                    "periodColumn": "period_year",
                    "periodGranularity": "year",
                    "measureColumns": ["budget_project_amount"],
                }
            ],
            "dimensionColumns": ["period_year", "project_code"],
            "grainColumns": ["period_year", "project_code"],
        }
    )
    ordinary = project.model_copy(
        update={
            "requirement_id": "income",
            "tables": (
                project.tables[0].model_copy(update={"table": "rj.dwd_income_budget_view"}),
            ),
        }
    )

    assert _row_preserving_requirement_ids((ordinary, project), ruijin_profile()) == (
        "project-budget-probe",
    )


def test_医院运营profile在真实表列漂移时启动失败关闭():
    def snapshot(column_name: str) -> SourceSchemaSnapshot:
        table = ModelTable(
            sourceId="rj",
            database="rj",
            name="dwd_hdc_income_summary_view",
            columns=tuple(
                ModelColumn(name=name, dataType="DECIMAL(18,2)", nullable=True)
                for name in (column_name, "area", "stlevel_analytic_unit")
            ),
        )
        return SourceSchemaSnapshot(
            source="metadata_api",
            revision="m1",
            schemaHash=schema_hash((table,)),
            tables=(table,),
        )

    _validate_hospital_operation_profile_schema(
        ruijin_profile(),
        (snapshot("indicator_value"),),
    )

    with pytest.raises(ReportingError) as captured:
        _validate_hospital_operation_profile_schema(
            ruijin_profile(),
            (snapshot("indicator_name"),),
        )
    assert captured.value.code == "hospital_operation_profile_schema_mismatch"
    assert "rj.rj.dwd_hdc_income_summary_view.indicator_value" in captured.value.message


@pytest.mark.anyio
async def test_对账步骤冻结下游可解析的未物化计划():
    state: dict[str, Any] = {}
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._state = lambda _context: state
    runtime._profile = lambda _context: SimpleNamespace(
        reconciliations=(
            SimpleNamespace(
                code="income_cross_check",
                left_metric="income_total",
                right_metric="income_summary",
                grain=("month", "campus"),
            ),
        )
    )
    runtime._assert_state_safe = lambda _state: None
    context = RunContext(run_id="run", session_id="session")

    await runtime.reconcile_sources(StepInput(input={}), context)

    frozen = state[REPORT_RECONCILIATIONS_STATE_KEY]
    assert frozen == [
        {
            "code": "income_cross_check",
            "status": "unavailable",
            "leftMetric": "income_total",
            "rightMetric": "income_summary",
            "grain": ["month", "campus"],
            "leftTotal": None,
            "rightTotal": None,
            "difference": None,
            "differenceRate": None,
            "commonKeyCount": 0,
            "leftOnlyKeyCount": 0,
            "rightOnlyKeyCount": 0,
            "zeroDenominatorCount": 0,
            "exceedsTolerance": None,
            "issues": ["等待语义事实物化后执行服务端对账。"],
        }
    ]
    assert runtime._reconciliations(context)[0].status == "unavailable"


@pytest.mark.parametrize(("start", "end"), [("2024", "2025"), ("'2024'", "'2025'")])
def test_sql审核年度期间支持数字或字符串年份边界(tmp_path: Path, start: str, end: str):
    source = source_config(tmp_path)
    table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="income",
        columns=(
            ModelColumn(name="period_year", dataType="INT", nullable=False),
            ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
        ),
    )
    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision="m1",
        schemaHash=schema_hash((table,)),
        tables=(table,),
        measureSemantics=(
            MeasureSemantic(
                fieldRef="operations.reporting.income.amount",
                aggregation="sum",
                additiveAcross=("period_year",),
            ),
        ),
    )
    requirement = QueryRequirement.model_validate(
        {
            "requirementId": "annual-income",
            "sourceId": "operations",
            "tables": [
                {
                    "table": "reporting.income",
                    "periodColumn": "period_year",
                    "periodGranularity": "year",
                    "measureColumns": ["amount"],
                }
            ],
            "dimensionColumns": ["period_year"],
            "grainColumns": ["period_year"],
        }
    )
    annual_envelope = envelope(period={"start": "2024-06-01", "end": "2025-03-31"})

    (approved,) = approve_query_batch(
        [
            {
                "requirementId": "annual-income",
                "sourceId": "operations",
                "sql": (
                    "SELECT period_year, SUM(amount) AS amount FROM reporting.income "
                    f"WHERE period_year BETWEEN {start} AND {end} GROUP BY period_year"
                ),
            }
        ],
        sources={"operations": source},
        snapshots=(snapshot,),
        envelope=annual_envelope,
        requirements=(requirement,),
    )

    assert f"BETWEEN {start} AND {end}" in approved.sql

    with pytest.raises(ReportingError) as captured:
        approve_query_batch(
            [
                {
                    "requirementId": "annual-income",
                    "sourceId": "operations",
                    "sql": (
                        "SELECT period_year, SUM(amount) AS amount FROM reporting.income "
                        "WHERE period_year = 2024 GROUP BY period_year"
                    ),
                }
            ],
            sources={"operations": source},
            snapshots=(snapshot,),
            envelope=annual_envelope,
            requirements=(requirement,),
        )
    assert captured.value.code == "report_query_period_invalid"


@pytest.mark.parametrize(
    ("start", "end"),
    [("2025/01", "2025/12"), ("2025-01", "2025-12"), ("202501", "202512")],
)
def test_sql审核字符串月份支持常见编码边界(tmp_path: Path, start: str, end: str):
    source = source_config(tmp_path)
    table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="income",
        columns=(
            ModelColumn(name="period_code", dataType="VARCHAR(7)", nullable=False),
            ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
        ),
    )
    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision="m1",
        schemaHash=schema_hash((table,)),
        tables=(table,),
        measureSemantics=(
            MeasureSemantic(
                fieldRef="operations.reporting.income.amount",
                aggregation="sum",
                additiveAcross=("period_code",),
            ),
        ),
    )
    requirement = QueryRequirement.model_validate(
        {
            "requirementId": "monthly-income",
            "sourceId": "operations",
            "tables": [
                {
                    "table": "reporting.income",
                    "periodColumn": "period_code",
                    "periodGranularity": "month",
                    "measureColumns": ["amount"],
                }
            ],
            "dimensionColumns": ["period_code"],
            "grainColumns": ["period_code"],
        }
    )

    (approved,) = approve_query_batch(
        [
            {
                "requirementId": "monthly-income",
                "sourceId": "operations",
                "sql": (
                    "SELECT period_code, SUM(amount) AS amount FROM reporting.income "
                    f"WHERE period_code BETWEEN '{start}' AND '{end}' GROUP BY period_code"
                ),
            }
        ],
        sources={"operations": source},
        snapshots=(snapshot,),
        envelope=envelope(),
        requirements=(requirement,),
    )

    assert f"BETWEEN '{start}' AND '{end}'" in approved.sql


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2025-01-01", "2025-12-31"),
        ("2025/01/01", "2025/12/31"),
        ("20250101", "20251231"),
    ],
)
def test_sql审核日期期间支持常见字符串编码(tmp_path: Path, start: str, end: str):
    sql = (
        "SELECT month, SUM(amount) AS amount FROM reporting.income "
        f"WHERE month BETWEEN '{start}' AND '{end}' GROUP BY month"
    )

    (approved,) = approve_sql(tmp_path, sql)

    assert f"BETWEEN '{start}' AND '{end}'" in approved.sql


def query_requirement(*, tables=None, grain_columns=("month",), relation_columns=None):
    table_values = [
        dict(item) for item in (tables or [{"table": "reporting.income", "periodColumn": "month"}])
    ]
    for item in table_values:
        item.setdefault("measureColumns", ["amount"])
        item.setdefault("periodGranularity", "date")
    relations = [
        {
            "leftTable": table_values[index - 1]["table"],
            "rightTable": table_values[index]["table"],
            "joinColumns": relation_columns or grain_columns,
        }
        for index in range(1, len(table_values))
    ]
    return QueryRequirement.model_validate(
        {
            "requirementId": "income-monthly",
            "sourceId": "operations",
            "tables": table_values,
            "dimensionColumns": grain_columns,
            "grainColumns": grain_columns,
            "relations": relations,
        }
    )


def approve_sql(tmp_path: Path, sql: str, *, requirement=None):
    return approve_query_batch(
        [
            {
                "requirementId": "income-monthly",
                "sourceId": "operations",
                "sql": sql,
            }
        ],
        sources={"operations": source_config(tmp_path)},
        snapshots=approval_snapshots(),
        envelope=envelope(),
        requirements=(requirement or query_requirement(),),
    )


def test_sql显式期间角色分别使用所属窗口(tmp_path: Path):
    queries = [
        {
            "requirementId": "income-monthly",
            "sourceId": "operations",
            "periodRole": role,
            "sql": (
                "SELECT month, SUM(amount) AS amount FROM reporting.income "
                f"WHERE month BETWEEN '{start}' AND '{end}' GROUP BY month"
            ),
        }
        for role, start, end in (
            ("current", "2025-01-01", "2025-12-31"),
            ("yoy", "2024-01-01", "2024-12-31"),
        )
    ]

    approved = approve_query_batch(
        queries,
        sources={"operations": source_config(tmp_path)},
        snapshots=approval_snapshots(),
        envelope=envelope(),
        requirements=(query_requirement(),),
    )

    assert [item.period_roles for item in approved] == [("current",), ("yoy",)]
    assert len({item.query_window_id for item in approved}) == 2


def test_sql本期角色访问同比窗口被拒绝(tmp_path: Path):
    with pytest.raises(ReportingError) as captured:
        approve_query_batch(
            [
                {
                    "requirementId": "income-monthly",
                    "sourceId": "operations",
                    "periodRole": "current",
                    "sql": (
                        "SELECT month, SUM(amount) AS amount FROM reporting.income "
                        "WHERE month BETWEEN '2024-01-01' AND '2024-12-31' GROUP BY month"
                    ),
                }
            ],
            sources={"operations": source_config(tmp_path)},
            snapshots=approval_snapshots(),
            envelope=envelope(),
            requirements=(query_requirement(),),
        )

    assert captured.value.code == "report_query_period_invalid"


def test_sql显式期间角色缺少窗口被拒绝(tmp_path: Path):
    with pytest.raises(ReportingError) as captured:
        approve_query_batch(
            [
                {
                    "requirementId": "income-monthly",
                    "sourceId": "operations",
                    "periodRole": "current",
                    "sql": (
                        "SELECT month, SUM(amount) AS amount FROM reporting.income "
                        "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY month"
                    ),
                }
            ],
            sources={"operations": source_config(tmp_path)},
            snapshots=approval_snapshots(),
            envelope=envelope(),
            requirements=(query_requirement(),),
        )

    assert captured.value.code == "report_query_batch_invalid"


def test_运行时按共享queryWindowId拒绝重复查询(tmp_path: Path):
    request = envelope(period={"start": "2023-01-01", "end": "2023-12-31"})
    generated = GeneratedQueryBatch.model_validate(
        {
            "queries": [
                {
                    "requirementId": "income-monthly",
                    "sourceId": "operations",
                    "periodRole": role,
                    "sql": (
                        "SELECT month, SUM(amount) AS amount FROM reporting.income "
                        f"WHERE month BETWEEN '{start}' AND '{end}' GROUP BY month"
                    ),
                }
                for role, start, end in (
                    ("current", "2023-01-01", "2023-12-31"),
                    ("yoy", "2022-01-01", "2022-12-31"),
                    ("mom", "2022-01-01", "2022-12-31"),
                )
            ]
        }
    )

    approved, issues = _approve_generated_queries(
        generated,
        sources={"operations": source_config(tmp_path)},
        snapshots=approval_snapshots(),
        envelope=request,
        requirements=(query_requirement(),),
    )

    assert len(approved) == 2
    assert approved[1].period_roles == ("yoy",)
    assert approved[0].query_window_id != approved[1].query_window_id
    assert issues == [
        {
            "path": "queries[2].periodRole",
            "rejectedValue": "mom",
            "reason": "periodRole 超出 requirement 允许的比较范围",
            "allowedValues": ["current", "yoy"],
            "requiredAction": "删除超出请求或 requirement 比较范围的查询",
        }
    ]


def test_sql审核将历史requirement比较范围越界转换为结构化issue(tmp_path: Path):
    requirement = query_requirement().model_copy(update={"comparison_roles": ("yoy", "mom")})
    generated = GeneratedQueryBatch.model_validate(
        {
            "queries": [
                {
                    "requirementId": requirement.requirement_id,
                    "sourceId": "operations",
                    "periodRole": "current",
                    "sql": (
                        "SELECT month, SUM(amount) AS amount FROM reporting.income "
                        "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY month"
                    ),
                }
            ]
        }
    )

    approved, issues = _approve_generated_queries(
        generated,
        sources={"operations": source_config(tmp_path)},
        snapshots=approval_snapshots(),
        envelope=envelope(),
        requirements=(requirement,),
    )

    assert approved == ()
    assert issues == [
        {
            "path": "requirements[0].comparisonRoles",
            "rejectedValue": ["mom"],
            "reason": "comparisonRoles 超出请求允许的比较范围",
            "allowedValues": ["yoy"],
            "requiredAction": (
                "删除 rejectedValue，只保留 allowedValues；省略 comparisonRoles 表示继承请求范围"
            ),
        }
    ]


@pytest.mark.parametrize(
    ("sql", "expected_code"),
    [
        (
            "SELECT month, AVG(amount) FROM reporting.income "
            "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' "
            "AND income_nature = '开单收入' GROUP BY month",
            "report_query_aggregation_invalid",
        ),
        (
            "SELECT month, SUM(amount) FROM reporting.income "
            "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY month",
            "report_query_scope_semantic_invalid",
        ),
    ],
)
def test_sql审核强制执行指标聚合与固定口径契约(tmp_path: Path, sql: str, expected_code: str):
    table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="income",
        columns=(
            ModelColumn(name="month", dataType="DATE", nullable=False),
            ModelColumn(name="income_nature", dataType="VARCHAR(20)", nullable=False),
            ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
        ),
    )
    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision="m1",
        schemaHash=schema_hash((table,)),
        tables=(table,),
        measureSemantics=(
            MeasureSemantic(
                fieldRef="operations.reporting.income.amount",
                aggregation="sum",
                additiveAcross=("month",),
                exclusiveScope={"income_nature": "开单收入"},
            ),
        ),
    )
    requirement = query_requirement()

    with pytest.raises(ReportingError) as captured:
        approve_query_batch(
            [{"requirementId": "income-monthly", "sourceId": "operations", "sql": sql}],
            sources={"operations": source_config(tmp_path)},
            snapshots=(snapshot,),
            envelope=envelope(),
            requirements=(requirement,),
        )

    assert captured.value.code == expected_code


def test_sql固定口径拒绝反馈包含服务端确认的精确过滤(tmp_path: Path):
    table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="income",
        columns=(
            ModelColumn(name="month", dataType="DATE", nullable=False),
            ModelColumn(name="income_nature", dataType="VARCHAR(20)", nullable=False),
            ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
        ),
    )
    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision="m1",
        schemaHash=schema_hash((table,)),
        tables=(table,),
        measureSemantics=(
            MeasureSemantic(
                fieldRef="operations.reporting.income.amount",
                aggregation="sum",
                additiveAcross=("month",),
                exclusiveScope={"income_nature": "开单收入"},
            ),
        ),
    )
    generated = GeneratedQueryBatch.model_validate(
        {
            "queries": [
                {
                    "requirementId": "income-monthly",
                    "sourceId": "operations",
                    "sql": (
                        "SELECT month, SUM(amount) AS amount FROM reporting.income "
                        "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' "
                        "GROUP BY month"
                    ),
                }
            ]
        }
    )

    approved, issues = _approve_generated_queries(
        generated,
        sources={"operations": source_config(tmp_path)},
        snapshots=(snapshot,),
        envelope=envelope(),
        requirements=(query_requirement(),),
    )

    assert approved == ()
    assert issues[0]["expectedScopeFilters"] == [
        {
            "table": "reporting.income",
            "column": "income_nature",
            "value": "开单收入",
        }
    ]


def test_sql审核拒绝通过省略层级维度绕过可加性契约(tmp_path: Path):
    table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="income",
        columns=(
            ModelColumn(name="month", dataType="DATE", nullable=False),
            ModelColumn(name="department_level", dataType="VARCHAR(20)", nullable=False),
            ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
        ),
    )
    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision="m1",
        schemaHash=schema_hash((table,)),
        tables=(table,),
        measureSemantics=(
            MeasureSemantic(
                fieldRef="operations.reporting.income.amount",
                aggregation="sum",
                additiveAcross=("month",),
            ),
        ),
    )

    with pytest.raises(ReportingError) as captured:
        approve_query_batch(
            [
                {
                    "requirementId": "income-monthly",
                    "sourceId": "operations",
                    "sql": (
                        "SELECT month, SUM(amount) FROM reporting.income "
                        "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY month"
                    ),
                }
            ],
            sources={"operations": source_config(tmp_path)},
            snapshots=(snapshot,),
            envelope=envelope(),
            requirements=(query_requirement(),),
        )

    assert captured.value.code == "report_measure_additivity_invalid"


@pytest.mark.parametrize(
    ("requirement", "sql"),
    [
        (
            query_requirement(
                tables=[
                    {
                        "table": "reporting.cost",
                        "periodColumn": "month",
                        "measureColumns": ["amount"],
                    }
                ]
            ),
            "SELECT month, SUM(amount) FROM reporting.cost "
            "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY month",
        ),
        (
            query_requirement(
                tables=[
                    {
                        "table": "reporting.income",
                        "periodColumn": "month",
                        "measureColumns": ["amount"],
                    }
                ]
            ),
            "SELECT month, SUM(amount) FROM reporting.income "
            "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY month",
        ),
    ],
)
def test_sql审核拒绝服务端白名单内但结构快照外的表和字段(
    tmp_path: Path, requirement: QueryRequirement, sql: str
):
    snapshot_table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="income",
        columns=(ModelColumn(name="month", dataType="DATE", nullable=False),),
    )
    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision="m1",
        schemaHash=schema_hash((snapshot_table,)),
        tables=(snapshot_table,),
    )

    with pytest.raises(ReportingError) as captured:
        approve_query_batch(
            [
                {
                    "requirementId": requirement.requirement_id,
                    "sourceId": "operations",
                    "sql": sql,
                }
            ],
            sources={"operations": source_config(tmp_path)},
            snapshots=(snapshot,),
            envelope=envelope(),
            requirements=(requirement,),
        )

    assert captured.value.code == "report_query_scope_invalid"


@pytest.mark.parametrize(
    "sql, code",
    [
        (
            "SELECT month, SUM(amount) FROM reporting.income GROUP BY month",
            "report_query_period_invalid",
        ),
        (
            "SELECT month, SUM(amount) FROM reporting.income "
            "WHERE month >= '2025-01-01' GROUP BY month",
            "report_query_period_invalid",
        ),
        (
            "SELECT month, SUM(amount) FROM reporting.income "
            "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' "
            "AND month >= '2025-06-01' GROUP BY month",
            "report_query_period_invalid",
        ),
        (
            "SELECT month, SUM(amount) FROM reporting.income "
            "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY month",
            "report_query_grain_invalid",
        ),
    ],
)
def test_sql审核验证完整期间和requirement粒度(tmp_path: Path, sql: str, code: str):
    requirement = query_requirement(grain_columns=("month", "campus"))

    with pytest.raises(ReportingError) as captured:
        approve_sql(tmp_path, sql, requirement=requirement)

    assert captured.value.code == code


def test_sql审核拒绝未聚合声明指标字段(tmp_path: Path):
    sql = (
        "SELECT month, COUNT(*) FROM reporting.income "
        "WHERE month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY month"
    )

    with pytest.raises(ReportingError) as captured:
        approve_sql(tmp_path, sql)

    assert captured.value.code == "report_query_measure_invalid"


@pytest.mark.parametrize(
    "condition",
    [
        "period_year BETWEEN 2025 AND 2025",
        "period_year = 2025",
        "period_year = '2025'",
        "2025 = period_year",
    ],
)
def test_sql审核按数据源年度粒度校验期间(tmp_path: Path, condition: str):
    source = source_config(tmp_path)
    table = ModelTable(
        sourceId="operations",
        database="reporting",
        name="income",
        columns=(
            ModelColumn(name="period_year", dataType="INT", nullable=False),
            ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
        ),
    )
    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision="m1",
        schemaHash=schema_hash((table,)),
        tables=(table,),
        measureSemantics=(
            MeasureSemantic(
                fieldRef="operations.reporting.income.amount",
                aggregation="sum",
                additiveAcross=("period_year",),
            ),
        ),
    )
    requirement = query_requirement(
        tables=[
            {
                "table": "reporting.income",
                "periodColumn": "period_year",
                "periodGranularity": "year",
                "measureColumns": ["amount"],
            }
        ],
        grain_columns=("period_year",),
    )
    sql = (
        "SELECT period_year, SUM(amount) FROM reporting.income "
        f"WHERE {condition} GROUP BY period_year"
    )

    approved = approve_query_batch(
        [{"requirementId": "income-monthly", "sourceId": "operations", "sql": sql}],
        sources={"operations": source},
        snapshots=(snapshot,),
        envelope=envelope(),
        requirements=(requirement,),
    )

    assert approved[0].sql == sql


def test_sql审核拒绝跨表明细连接放大(tmp_path: Path):
    requirement = query_requirement(
        tables=[
            {"table": "reporting.income", "periodColumn": "month"},
            {"table": "reporting.cost", "periodColumn": "month"},
        ]
    )
    sql = (
        "SELECT i.month, SUM(i.amount), SUM(c.amount) "
        "FROM reporting.income i JOIN reporting.cost c ON i.month = c.month "
        "WHERE i.month BETWEEN '2025-01-01' AND '2025-12-31' "
        "AND c.month BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY i.month"
    )

    with pytest.raises(ReportingError) as captured:
        approve_sql(tmp_path, sql, requirement=requirement)

    assert captured.value.code == "report_query_join_grain_invalid"


def test_sql审核允许各表先聚合后按完整共同粒度连接(tmp_path: Path):
    requirement = query_requirement(
        tables=[
            {"table": "reporting.income", "periodColumn": "month"},
            {"table": "reporting.cost", "periodColumn": "month"},
        ],
        grain_columns=("month", "campus"),
    )
    sql = """
        WITH income AS (
            SELECT month, campus, SUM(amount) AS amount
            FROM reporting.income
            WHERE month BETWEEN '2025-01-01' AND '2025-12-31'
            GROUP BY month, campus
        ), cost AS (
            SELECT month, campus, SUM(amount) AS amount
            FROM reporting.cost
            WHERE month BETWEEN '2025-01-01' AND '2025-12-31'
            GROUP BY month, campus
        )
        SELECT income.month, income.campus, income.amount, cost.amount
        FROM income JOIN cost
          ON income.month = cost.month AND income.campus = cost.campus
    """

    (approved,) = approve_sql(tmp_path, sql, requirement=requirement)

    assert approved.requirement_id == requirement.requirement_id


def test_sql审核使用模型声明的relation键而非固定聚合粒度(tmp_path: Path):
    requirement = query_requirement(
        tables=[
            {"table": "reporting.income", "periodColumn": "month"},
            {"table": "reporting.cost", "periodColumn": "month"},
        ],
        grain_columns=("month", "campus"),
        relation_columns=("campus",),
    )
    sql = """
        WITH income AS (
            SELECT month, campus, SUM(amount) AS amount
            FROM reporting.income
            WHERE month BETWEEN '2025-01-01' AND '2025-12-31'
            GROUP BY month, campus
        ), cost AS (
            SELECT month, campus, SUM(amount) AS amount
            FROM reporting.cost
            WHERE month BETWEEN '2025-01-01' AND '2025-12-31'
            GROUP BY month, campus
        )
        SELECT income.month, income.campus, income.amount, cost.amount
        FROM income JOIN cost ON income.campus = cost.campus
    """

    (approved,) = approve_sql(tmp_path, sql, requirement=requirement)

    assert approved.requirement_id == requirement.requirement_id


def test_sql审核拒绝聚合结果遗漏共同粒度连接键(tmp_path: Path):
    requirement = query_requirement(
        tables=[
            {"table": "reporting.income", "periodColumn": "month"},
            {"table": "reporting.cost", "periodColumn": "month"},
        ],
        grain_columns=("month", "campus"),
    )
    sql = """
        WITH income AS (
            SELECT month, campus, SUM(amount) AS amount
            FROM reporting.income
            WHERE month BETWEEN '2025-01-01' AND '2025-12-31'
            GROUP BY month, campus
        ), cost AS (
            SELECT month, campus, SUM(amount) AS amount
            FROM reporting.cost
            WHERE month BETWEEN '2025-01-01' AND '2025-12-31'
            GROUP BY month, campus
        )
        SELECT income.month, income.campus, income.amount, cost.amount
        FROM income JOIN cost ON income.month = cost.month
    """

    with pytest.raises(ReportingError) as captured:
        approve_sql(tmp_path, sql, requirement=requirement)

    assert captured.value.code == "report_query_join_grain_invalid"


@pytest.mark.anyio
async def test_download_grant绑定scope_revision和文件hash且cli不返回url():
    repository = InMemoryDownloadGrantRepository()
    service = ReportDownloadGrantService(repository)
    scope = ReportDownloadScope("db", "u", "c", "s", "t", "run")
    now = datetime(2026, 7, 28, tzinfo=UTC)
    raw, grant = await service.issue(
        scope=scope,
        report_id="report-1",
        revision=1,
        pdf_path="reports/result.pdf",
        pdf_size=100,
        pdf_sha256="a" * 64,
        word_path="reports/result.docx",
        word_size=200,
        word_sha256="c" * 64,
        now=now,
    )

    assert raw not in repository.records
    assert (
        await service.resolve(
            raw,
            scope=scope,
            current_pdf_sha256="a" * 64,
            current_revision=1,
            now=now,
        )
        == grant
    )
    for values, code in (
        (
            {"scope": ReportDownloadScope("db", "other", "c", "s", "t", "run")},
            "report_download_scope_mismatch",
        ),
        ({"current_revision": 2}, "report_download_revision_changed"),
        ({"current_pdf_sha256": "b" * 64}, "report_download_file_changed"),
        ({"now": now + timedelta(hours=24)}, "report_download_grant_expired"),
    ):
        arguments = {
            "scope": scope,
            "current_pdf_sha256": "a" * 64,
            "current_revision": 1,
            "now": now,
            **values,
        }
        with pytest.raises(ReportingError) as captured:
            await service.resolve(raw, **arguments)
        assert captured.value.code == code

    warning = SourceWarning(
        code="source_period_difference",
        message="期间不同",
        datasetIds=("dataset-1",),
    ).model_dump(mode="json", by_alias=True)
    receipt = PlanExecutionReceipt(
        planId="table-1",
        planHash="d" * 64,
        inputSnapshotHash="e" * 64,
        actualSource=SourceBinding(
            sourcePolicy="csv",
            datasetIds=("dataset-1",),
            warnings=(SourceWarning.model_validate(warning),),
        ),
        inputRowCount=1,
        outputSummary={"kind": "table"},
        warnings=(SourceWarning.model_validate(warning),),
        artifactSha256="f" * 64,
    ).model_dump(mode="json", by_alias=True)
    http = publication_result(
        report_id="report-1",
        revision=1,
        raw_grant=raw,
        grant=grant,
        source_warnings=[warning],
        coding_receipts=[receipt],
    )
    cli = cli_result(
        path="/tmp/result.pdf",
        size=100,
        sha256="a" * 64,
        word_path="/tmp/result.docx",
        word_size=200,
        word_sha256="c" * 64,
        source_warnings=[warning],
        coding_receipts=[receipt],
    )
    assert "downloadUrl" in http["pdf"]  # type: ignore[operator]
    assert "downloadUrl" in http["word"]  # type: ignore[operator]
    assert http["sourceWarnings"] == [warning]
    assert http["codingReceipts"] == [receipt]
    assert cli["word"] == {
        "path": "/tmp/result.docx",
        "size": 200,
        "sha256": "c" * 64,
    }
    assert "Url" not in repr(cli) and "url" not in repr(cli)
    assert cli["sourceWarnings"][0]["code"] == "source_period_difference"  # type: ignore[index]
    assert cli["codingReceipts"][0]["planId"] == "table-1"  # type: ignore[index]


def test_发布内容拒绝非法来源warning或coding回执():
    base = {
        "reportId": "report-1",
        "revision": 1,
        "pdfPath": "report.pdf",
        "pdfSize": 10,
        "pdfSha256": "a" * 64,
        "wordPath": "report.docx",
        "wordSize": 20,
        "wordSha256": "b" * 64,
    }
    for invalid in (
        {"sourceWarnings": [{"code": "unknown"}]},
        {"codingReceipts": [{"planId": "table-1"}]},
    ):
        with pytest.raises(ReportingError) as captured:
            ReportWorkflowRuntime._publication_content(base | invalid)
        assert captured.value.code == "report_publication_invalid"
