from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from ag_ui.core import RunAgentInput
from agno.run import RunContext
from agno.workflow.types import StepInput, StepOutput

from agentos_dev.coding.reporting.contract import (
    AgentQueryResponse,
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
from agentos_dev.coding.reporting.entrypoints import prepare_agui_envelope
from agentos_dev.coding.reporting.metadata import ReportingMetadataClient, select_reporting_agent
from agentos_dev.coding.reporting.models import ReportingError
from agentos_dev.coding.reporting.profile import (
    ReportingProfileRegistry,
    resolve_capabilities,
    resolve_reporting_profile,
)
from agentos_dev.coding.reporting.publishing import (
    InMemoryDownloadGrantRepository,
    ReportDownloadGrantService,
    ReportDownloadScope,
    cli_result,
    publication_result,
)
from agentos_dev.coding.reporting.runtime import (
    REPORT_ANALYSIS_PLAN_STATE_KEY,
    REPORT_APPROVED_QUERIES_STATE_KEY,
    REPORT_CAPABILITIES_STATE_KEY,
    REPORT_DATA_REQUIREMENTS_STATE_KEY,
    REPORT_DATA_SHAPES_STATE_KEY,
    REPORT_DATA_UNDERSTANDING_STATE_KEY,
    REPORT_EFFECTIVE_PROFILE_STATE_KEY,
    REPORT_OUTLINE_CONTEXT_STATE_KEY,
    REPORT_OUTLINE_STATE_KEY,
    REPORT_RECONCILIATIONS_STATE_KEY,
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
    _coding_observed_data_facts,
    _compact_validation_feedback,
    _outline_section_issues,
    _PlannerOutputValidationError,
    _planning_schema_payload,
    _validate_data_understanding,
)
from agentos_dev.coding.reporting.workflow import _requires_source_review
from agentos_dev.coding.reporting.workflow_v1 import (
    DatasetLineage,
    QueryRequirement,
    approve_query_batch,
    require_approved_sql,
    resolve_schema_snapshot,
)


def envelope(**updates):
    value = {
        "version": "1",
        "reportGoal": "分析经营情况",
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
    assert set(captured[0]) == {"reportGoal", "period", "schemas"}
    schemas = captured[0]["schemas"]
    assert isinstance(schemas, list)
    assert set(schemas[0]) == {"tables"}
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
        "outline",
        "analysisContext",
        "dataUnderstanding",
        "schemas",
    }
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
async def test_提纲要求使用领域无关的通用章节():
    captured: dict[str, object] = {}
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._outline_agent = object()

    async def run_planner(_agent, payload, _run_context):
        captured.update(payload)
        return ReportOutline(
            title="通用分析报告",
            sections=("执行摘要", "分析范围与方法", "关键发现", "局限性", "建议"),
        )

    runtime._run_planner = run_planner
    profile_registry = ReportingProfileRegistry(documents={}, config_paths=())
    profile = resolve_reporting_profile(profile_registry, None)
    capabilities = resolve_capabilities(profile, (), ())
    context = RunContext(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        session_state={
            REPORT_WORKFLOW_INPUT_STATE_KEY: envelope().workflow_payload(
                default_source_ids=("operations",)
            ),
            REPORT_SCHEMA_SNAPSHOTS_STATE_KEY: [],
            REPORT_DATA_SHAPES_STATE_KEY: [],
            REPORT_EFFECTIVE_PROFILE_STATE_KEY: profile.model_dump(mode="json", by_alias=True),
            REPORT_CAPABILITIES_STATE_KEY: capabilities.model_dump(mode="json", by_alias=True),
            REPORT_RECONCILIATIONS_STATE_KEY: [],
        },
    )

    await runtime.generate_outline(StepInput(input=envelope()), context)

    assert set(captured) == {"reportGoal", "period", "outlineContext", "feedback"}
    outline_context = captured["outlineContext"]
    assert isinstance(outline_context, dict)
    sections = outline_context["profile"]["sections"]
    assert [item["title"] for item in sections] == [
        "执行摘要",
        "分析范围与方法",
        "关键发现",
        "局限性",
        "建议",
    ]
    required_sections = "\n".join(item["title"] for item in sections)
    assert all(term not in required_sections for term in ("院区", "科室", "预算", "收入"))


@pytest.mark.anyio
async def test_提纲结构错误会携带强反馈纠错而不是盲重试():
    invalid_output = {
        "title": "运营分析报告",
        "sections": ['{"code":"summary","content":"正文"}'],
        "assumptions": [],
    }
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._outline_agent = object()

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        if len(captured) == 1:
            raise _PlannerOutputValidationError(
                invalid_output,
                [
                    {
                        "path": "sections",
                        "rejectedValue": invalid_output["sections"],
                        "reason": "章节必须是自然语言标题，不得包含 JSON 或配置序列化片段",
                        "requiredAction": "只返回章节标题，并返回完整 ReportOutline",
                    }
                ],
            )
        return ReportOutline(
            title="运营分析报告",
            sections=("执行摘要", "分析范围与方法", "关键发现", "局限性", "建议"),
        )

    runtime._run_planner = run_planner
    profile_registry = ReportingProfileRegistry(documents={}, config_paths=())
    profile = resolve_reporting_profile(profile_registry, None)
    capabilities = resolve_capabilities(profile, (), ())
    context = RunContext(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        session_state={
            REPORT_WORKFLOW_INPUT_STATE_KEY: envelope().workflow_payload(
                default_source_ids=("operations",)
            ),
            REPORT_SCHEMA_SNAPSHOTS_STATE_KEY: [],
            REPORT_DATA_SHAPES_STATE_KEY: [],
            REPORT_EFFECTIVE_PROFILE_STATE_KEY: profile.model_dump(mode="json", by_alias=True),
            REPORT_CAPABILITIES_STATE_KEY: capabilities.model_dump(mode="json", by_alias=True),
            REPORT_RECONCILIATIONS_STATE_KEY: [],
        },
    )

    await runtime.generate_outline(StepInput(input=envelope()), context)

    assert len(captured) == 2
    assert "correction" not in captured[0]
    correction = captured[1]["correction"]
    assert correction["attempt"] == 2
    assert "previousOutput" not in correction
    assert correction["validationFeedback"]["issues"][0]["path"] == "sections"
    assert "自然语言章节标题" in correction["instruction"]


def test_提纲允许在profile必选章节之间增加中文章节():
    profile = resolve_reporting_profile(
        ReportingProfileRegistry(documents={}, config_paths=()), None
    )
    outline = ReportOutline(
        title="运营分析报告",
        sections=(
            "执行摘要",
            "分析范围与方法",
            "收入与预算执行分析",
            "关键发现",
            "局限性",
            "建议",
        ),
    )

    assert _outline_section_issues(outline, profile) == []


@pytest.mark.parametrize(
    ("sections", "reason"),
    (
        (
            ("执行摘要", "分析范围与方法", "关键发现", "建议"),
            "必须使用原始 title",
        ),
        (
            ("摘要", "分析范围与方法", "关键发现", "局限性", "建议"),
            "必须使用原始 title",
        ),
        (
            ("分析范围与方法", "执行摘要", "关键发现", "局限性", "建议"),
            "相对顺序",
        ),
    ),
)
def test_提纲拒绝删除改名或打乱profile必选章节(sections: tuple[str, ...], reason: str):
    profile = resolve_reporting_profile(
        ReportingProfileRegistry(documents={}, config_paths=()), None
    )

    issues = _outline_section_issues(
        ReportOutline(title="运营分析报告", sections=sections), profile
    )

    assert len(issues) == 1
    assert issues[0]["path"] == "sections"
    assert issues[0]["requiredTitles"] == [section.title for section in profile.sections]
    assert reason in issues[0]["reason"]


def test_提纲必选章节只使用自定义profile_title():
    profile = resolve_reporting_profile(
        ReportingProfileRegistry(documents={}, config_paths=()), None
    )
    custom_sections = tuple(
        section.model_copy(update={"title": "管理层摘要"})
        if section.code == "executive_summary"
        else section
        for section in profile.sections
    )
    custom_profile = profile.model_copy(update={"sections": custom_sections})
    outline = ReportOutline(
        title="运营分析报告",
        sections=("管理层摘要", "分析范围与方法", "关键发现", "局限性", "建议"),
    )

    assert _outline_section_issues(outline, custom_profile) == []
    issues = _outline_section_issues(
        ReportOutline(
            title="运营分析报告",
            sections=("执行摘要", "分析范围与方法", "关键发现", "局限性", "建议"),
        ),
        custom_profile,
    )
    assert issues[0]["missingTitles"] == ["管理层摘要"]


@pytest.mark.anyio
async def test_提纲未保留profile章节时携带精确标题纠错():
    captured: list[dict[str, object]] = []
    runtime: Any = object.__new__(ReportWorkflowRuntime)
    runtime._outline_agent = object()

    async def run_planner(_agent, payload, _run_context):
        captured.append(payload)
        sections = (
            ("执行摘要", "收入分析")
            if len(captured) == 1
            else ("执行摘要", "分析范围与方法", "收入分析", "关键发现", "局限性", "建议")
        )
        return ReportOutline(title="运营分析报告", sections=sections)

    runtime._run_planner = run_planner
    profile = resolve_reporting_profile(
        ReportingProfileRegistry(documents={}, config_paths=()), None
    )
    capabilities = resolve_capabilities(profile, (), ())
    context = RunContext(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        session_state={
            REPORT_WORKFLOW_INPUT_STATE_KEY: envelope().workflow_payload(
                default_source_ids=("operations",)
            ),
            REPORT_SCHEMA_SNAPSHOTS_STATE_KEY: [],
            REPORT_DATA_SHAPES_STATE_KEY: [],
            REPORT_EFFECTIVE_PROFILE_STATE_KEY: profile.model_dump(mode="json", by_alias=True),
            REPORT_CAPABILITIES_STATE_KEY: capabilities.model_dump(mode="json", by_alias=True),
            REPORT_RECONCILIATIONS_STATE_KEY: [],
        },
    )

    output = await runtime.generate_outline(StepInput(input=envelope()), context)

    assert output.content.sections[2] == "收入分析"
    correction = captured[1]["correction"]
    issue = correction["validationFeedback"]["issues"][0]
    assert issue["requiredTitles"] == [section.title for section in profile.sections]
    assert issue["missingTitles"] == ["分析范围与方法", "关键发现", "局限性", "建议"]
    assert "可以根据报告目标和真实数据增加其他中文章节" in correction["instruction"]


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
    "section",
    [
        '{"displayCoverpage": false, "pageSize": "A4"}',
        '"displayCoverpage": false, "pageSize": "A4"',
        'displayCoverpage\\": false, pageSize\\": \\"A4\\"',
    ],
)
def test_提纲章节拒绝json或配置序列化片段(section: str):
    with pytest.raises(ValueError):
        ReportOutline(title="运营分析报告", sections=(section,))


def test_提纲章节允许正常中文标题和标点():
    outline = ReportOutline(
        title="2025年运营分析报告",
        sections=("执行摘要", "收入、成本与工作量分析", "结论：风险与建议"),
        assumptions=("分析期间为2025年。",),
    )

    assert outline.sections == ("执行摘要", "收入、成本与工作量分析", "结论：风险与建议")


def test_提纲拒绝孤立标点前缀但允许句内标点():
    with pytest.raises(ValueError):
        ReportOutline(title="运营分析报告", sections=(": 执行摘要",))

    outline = ReportOutline(title="运营分析报告", sections=("结论：风险与建议",))

    assert outline.sections == ("结论：风险与建议",)


def test_提纲假设拒绝填补缺失数据但允许如实披露():
    with pytest.raises(ValueError):
        ReportOutline(
            title="运营分析报告",
            sections=("数据限制",),
            assumptions=("缺失月份按趋势估算或视为未发生",),
        )

    outline = ReportOutline(
        title="运营分析报告",
        sections=("数据限制",),
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
            title="运营分析报告",
            sections=("数据限制",),
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


@pytest.mark.parametrize(
    "updates",
    [
        {"title": ": "},
        {"sections": (": ",)},
        {"assumptions": ("——",)},
        {"sections": ("收入分析", " 收入分析 ")},
        {"assumptions": ("数据口径一致", "数据口径一致")},
        {"sections": ("executive_summary",)},
        {"assumptions": ("default_assumption",)},
    ],
)
def test_提纲拒绝纯标点或重复的自然语言字段(updates: dict[str, object]):
    payload = {
        "title": "运营分析报告",
        "sections": ("执行摘要",),
        "assumptions": (),
        **updates,
    }

    with pytest.raises(ValueError):
        ReportOutline.model_validate(payload)


@pytest.mark.anyio
async def test_规划器严格解析保留污染字段供模型纠错(caplog):
    caplog.set_level("INFO", logger="agentos_dev.coding.reporting.runtime")
    raw = json.dumps(
        {
            "title": "运营分析报告",
            "sections": ["执行摘要", "correctionAppliedClean: true"],
            "assumptions": [],
        }
    )

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

    assert captured.value.output["sections"][1] == "correctionAppliedClean: true"
    assert captured.value.issues[0]["path"] == "sections"
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "report_planner_request" in messages
    assert "report_planner_response" in messages
    assert "cache_read_tokens=80" in messages
    assert "report_planner_validation_failed" in messages


@pytest.mark.anyio
@pytest.mark.parametrize("wrapper", ["fence", "encoded"])
async def test_规划器只弱解包完整结构化JSON(wrapper: str):
    raw = json.dumps(
        {
            "title": "运营分析报告",
            "sections": ["执行摘要"],
            "assumptions": [],
        },
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

    assert output == ReportOutline(
        title="运营分析报告",
        sections=("执行摘要",),
        assumptions=(),
    )


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


def test_来源唯一时不审核仅多个agent时审核():
    assert (
        _requires_source_review(StepOutput(content={"sources": [{"sourceId": "operations"}]}))
        is False
    )
    assert _requires_source_review(StepOutput(content={"agents": [{"code": "1"}]})) is False
    assert (
        _requires_source_review(StepOutput(content={"agents": [{"code": "1"}, {"code": "2"}]}))
        is True
    )


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
        "agentos_dev.coding.reporting.runtime.StarRocksDataSourceAdapter", FakeAdapter
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
        "agentos_dev.coding.reporting.runtime.StarRocksDataSourceAdapter", FakeAdapter
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

    http = publication_result(report_id="report-1", revision=1, raw_grant=raw, grant=grant)
    cli = cli_result(path="/tmp/result.pdf", size=100, sha256="a" * 64)
    assert "downloadUrl" in http["pdf"]  # type: ignore[operator]
    assert "Url" not in repr(cli) and "url" not in repr(cli)
