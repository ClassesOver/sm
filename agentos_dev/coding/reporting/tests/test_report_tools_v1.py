from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from agentos_dev.coding.reporting.delivery.draft_v1 import (
    ReportChartRegistration,
    ReportDraftBlock,
)
from agentos_dev.coding.reporting.hospital_operation.detailed_analysis import (
    build_profile_model_view,
)
from agentos_dev.coding.reporting.models import ReportingError
from agentos_dev.coding.reporting.tests.workspace_fakes import service
from agentos_dev.coding.reporting.tools import ReportWorkspaceTaskToolkit
from agentos_dev.task_execution.execution import WorkspaceTaskToolkit


class _EmptyExecutionRepository:
    async def list_executions(self, _external_run_id: str) -> list[object]:
        return []


def _identity(path: str, content: bytes) -> dict[str, object]:
    return {
        "path": path,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _profile_pointer_toolkit(monkeypatch, tmp_path, *, extra_field_count: int = 0):
    profile = {
        "table": {"n": 100, "n_var": 1, "types": {"Numeric": 1}},
        "variables": {
            "amount": {
                "type": "Numeric",
                "count": 100,
                "skewness": 4.5,
                "kurtosis": 21.0,
                "histogram": {
                    "counts": list(range(100)),
                    "bin_edges": list(range(101)),
                },
            },
            **{
                f"field_{index}": {
                    "type": "Numeric",
                    "count": 100,
                    "histogram": {"counts": [1]},
                }
                for index in range(extra_field_count)
            },
        },
        "alerts": ["[amount] is highly skewed"],
        "correlations": {"pearson": [{"amount": 1.0}]},
        "time_series_analysis": {
            "enabled": True,
            "sort_field": "period",
            "fields": {
                "amount": {
                    "acf": [{"lag": 0, "value": 1.0}],
                    "pacf": [{"lag": 0, "value": 1.0}],
                    "seasonality": {"presence": False, "periods": []},
                }
            },
        },
    }
    profile_content = json.dumps(profile, separators=(",", ":")).encode()
    profile_identity = _identity("profiles/dataset-1.json", profile_content)
    analysis_context = json.dumps(
        {
            "datasetContexts": [
                {
                    "datasetId": "dataset-1",
                    "fields": list(profile["variables"]),
                    "profileFile": profile_identity,
                    "profileModelView": build_profile_model_view(profile),
                }
            ]
        },
        separators=(",", ":"),
    ).encode()
    analysis_identity = _identity("contexts/analysis.json", analysis_context)
    validation_context = json.dumps(
        {"analysisContextFile": analysis_identity}, separators=(",", ":")
    ).encode()
    validation_identity = _identity("contexts/validation.json", validation_context)
    files = {
        profile_identity["path"]: profile_content,
        analysis_identity["path"]: analysis_context,
        validation_identity["path"]: validation_context,
    }
    workspace_service = service(tmp_path)
    monkeypatch.setattr(
        workspace_service,
        "file_bytes",
        lambda _thread_id, path: (files[path], "application/json"),
    )
    toolkit = ReportWorkspaceTaskToolkit(workspace_service, _EmptyExecutionRepository())
    scope = SimpleNamespace(
        thread_id="thread-1",
        task=SimpleNamespace(
            acceptance_contract={
                "requirements": [
                    {
                        "id": "report-artifact",
                        "parameters": {"validationContextFile": validation_identity},
                    }
                ]
            }
        ),
    )

    async def resolve_scope(_run_context):
        return scope

    monkeypatch.setattr(toolkit.kernel, "scope", resolve_scope)
    return toolkit, files, profile_identity


def test_report工具schema只暴露dataset引用和analysis计划() -> None:
    chart_schema = ReportChartRegistration.model_json_schema(by_alias=True)
    assert set(chart_schema["properties"]) == {
        "chartId",
        "sourcePath",
        "title",
        "altText",
        "citationIds",
    }

    block_schema = ReportDraftBlock.model_json_schema(by_alias=True)
    serialized = str(block_schema)
    assert "markdown" in block_schema["properties"]
    assert "analysisIds" in serialized
    assert "$defs" not in block_schema
    assert "table" not in block_schema["properties"]
    assert "factIds" not in serialized
    assert "seriesId" not in serialized


def test_report图表路径必须为安全相对路径() -> None:
    registration = ReportChartRegistration(
        chartId="income-trend",
        sourcePath="analysis/income.png",
        title="收入趋势",
        altText="收入趋势图",
        citationIds=("citation_001",),
    )
    assert registration.source_path == "analysis/income.png"


def test_report_finish_task_schema不暴露verification_ids(tmp_path) -> None:
    toolkit = ReportWorkspaceTaskToolkit(service(tmp_path), _EmptyExecutionRepository())

    properties = toolkit.async_functions["finish_task"].parameters["properties"]

    assert "verification_ids" not in properties
    assert "verification_ids" not in toolkit.instructions
    assert "verify" not in toolkit.instructions


@pytest.mark.anyio
async def test_report_finish_task无verify时绕过Coding验证门禁(tmp_path) -> None:
    repository = _EmptyExecutionRepository()
    workspace_service = service(tmp_path)
    report_toolkit = ReportWorkspaceTaskToolkit(workspace_service, repository)
    coding_toolkit = WorkspaceTaskToolkit(workspace_service, repository)
    scope = SimpleNamespace(
        task=SimpleNamespace(mutation_sequence=1),
        external_run_id="report-run",
    )
    arguments = {"summary": "done", "artifact_paths": []}

    report_rejection = await report_toolkit._state_admission_rejection(
        scope,
        "finish_task",
        arguments,
        {},
    )
    coding_rejection = await coding_toolkit._state_admission_rejection(
        scope,
        "finish_task",
        arguments,
        {},
    )

    assert report_rejection is None
    assert coding_rejection is not None
    assert coding_rejection["code"] == "coding_verification_required"


@pytest.mark.anyio
async def test_read_profile_pointer只读取受信节点且输出有界(monkeypatch, tmp_path) -> None:
    toolkit, _files, _profile_identity = _profile_pointer_toolkit(monkeypatch, tmp_path)

    result = await toolkit.read_profile_pointer(
        datasetId="dataset-1",
        profilePointer="/variables/amount/histogram",
        maxItems=5,
    )

    assert result["ok"] is True
    assert result["datasetId"] == "dataset-1"
    assert result["profilePointer"] == "/variables/amount/histogram"
    assert result["truncated"] is True
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= 16 * 1024


@pytest.mark.anyio
async def test_read_profile_pointer拒绝整份展开和身份变化(monkeypatch, tmp_path) -> None:
    toolkit, files, profile_identity = _profile_pointer_toolkit(monkeypatch, tmp_path)

    with pytest.raises(ReportingError, match="Pointer"):
        await toolkit.read_profile_pointer(
            datasetId="dataset-1",
            profilePointer="/variables",
        )

    files[profile_identity["path"]] += b" "
    with pytest.raises(ReportingError, match="身份"):
        await toolkit.read_profile_pointer(
            datasetId="dataset-1",
            profilePointer="/variables/amount",
        )


@pytest.mark.anyio
async def test_inspect_profile_index返回紧凑覆盖告警和pointer目录(monkeypatch, tmp_path) -> None:
    toolkit, _files, _profile_identity = _profile_pointer_toolkit(monkeypatch, tmp_path)

    result = await toolkit.inspect_profile_index(datasetId="dataset-1")

    assert result["ok"] is True
    assert result["datasetId"] == "dataset-1"
    assert result["coverage"]["fullAlertCount"] == 1
    assert result["coverage"]["indexedAlertCount"] == 1
    assert result["truncation"] == {
        "variableIndexTruncated": False,
        "detailIndexTruncated": False,
        "alertIndexTruncated": False,
    }
    assert result["pointerCatalog"]["variableRoots"] == {
        "amount": "/variables/amount"
    }
    assert result["pointerCatalog"]["indexedFieldTypes"] == {"amount": "Numeric"}
    assert result["pointerCatalog"]["correlations"] == {
        "pearson": "/correlations/pearson"
    }
    assert result["pointerCatalog"]["timeSeriesFields"][0]["acfPointer"] == (
        "/time_series_analysis/fields/amount/acf"
    )
    assert "/variables/{field}/histogram" in result["pointerCatalog"][
        "numericDetailTemplates"
    ]
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= 16 * 1024


@pytest.mark.anyio
async def test_inspect_profile_index可发现未进入模型视图的字段(monkeypatch, tmp_path) -> None:
    toolkit, _files, _profile_identity = _profile_pointer_toolkit(
        monkeypatch, tmp_path, extra_field_count=50
    )

    result = await toolkit.inspect_profile_index(datasetId="dataset-1")

    assert len(result["pointerCatalog"]["variableRoots"]) == 51
    assert result["pointerCatalog"]["variableRoots"]["field_49"] == (
        "/variables/field_49"
    )
