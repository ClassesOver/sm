"""幻灯片与工作簿 AI 经 Reporting 结构化输出执行器返回 Schema 校验后的候选。"""

from __future__ import annotations

import json

import pytest
from agno.models.openai import OpenAIChat
from pydantic import ValidationError

from smart_reporting.report_editor.slides_ai import (
    AgnoSlidesProposalPlanner,
    SlidesAIProposal,
    create_report_slides_ai_service,
)
from smart_reporting.report_editor.workbook_ai import (
    AgnoWorkbookProposalPlanner,
    WorkbookAIProposal,
    create_report_workbook_ai_service,
)
from smart_reporting.reporting.structured_output.agno_compat import _parse_reporting_response_model
from smart_reporting.reporting.structured_output.wire_schema import StructuredOutputWireSchemaResolver


def _model() -> OpenAIChat:
    return OpenAIChat(id="qwen3.8-flash", api_key="test", base_url="https://dashscope.example/v1")


@pytest.mark.parametrize(
    ("factory", "planner_type", "schema"),
    [
        (create_report_slides_ai_service, AgnoSlidesProposalPlanner, SlidesAIProposal),
        (create_report_workbook_ai_service, AgnoWorkbookProposalPlanner, WorkbookAIProposal),
    ],
)
def test_editor_ai_factories_use_structured_generator_agents(factory, planner_type, schema):
    service = factory(_model(), object())

    assert isinstance(service.planner, planner_type)
    assert service.planner.agent.output_schema is schema
    assert service.planner.agent.tools == []


@pytest.mark.parametrize("schema", [SlidesAIProposal, WorkbookAIProposal])
def test_editor_ai_schemas_use_the_reporting_response_parser(schema):
    """未登记的 Schema 会回落到 Agno 默认解析，无法恢复围栏包裹的 JSON。"""
    payload = (
        {"summary": "精简标题", "edits": [{"slideIndex": 0, "elementId": "t1", "text": "新标题"}], "order": [1, 0]}
        if schema is SlidesAIProposal
        else {"summary": "加粗", "operations": [{"kind": "applyCellEdits", "arguments": {"edits": []}}]}
    )
    fenced = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"

    parsed = _parse_reporting_response_model(fenced, schema)

    assert isinstance(parsed, schema)
    assert _parse_reporting_response_model(json.dumps({**payload, "extra": 1}), schema) is None


def test_workbook_strict_wire_decodes_to_engine_operations():
    contract = StructuredOutputWireSchemaResolver().resolve(
        WorkbookAIProposal, model_id="qwen3.8-flash", endpoint="https://dashscope.example/v1",
    )
    edits = [{"sheetName": "汇总", "row": 0, "column": 0, "writeValue": True, "cell": {"value": 1}}]
    wire = {"summary": "改值", "operations": [{"kind": "applyCellEdits", "arguments": [
        {"key": "edits", "valueJson": json.dumps(edits, ensure_ascii=False)},
    ]}]}

    proposal = WorkbookAIProposal.model_validate(contract.decode(json.dumps(wire, ensure_ascii=False)))

    assert contract.instruction is not None and "arguments" in contract.instruction
    assert proposal.engine_operations() == [{"kind": "applyCellEdits", "edits": edits}]


def test_workbook_proposal_rejects_disallowed_and_ambiguous_operations():
    with pytest.raises(ValidationError):
        WorkbookAIProposal.model_validate({"summary": "x", "operations": [{"kind": "protectSheet", "arguments": {}}]})
    proposal = WorkbookAIProposal.model_validate(
        {"summary": "x", "operations": [{"kind": "applyCellEdits", "arguments": {"kind": "addPivot"}}]},
    )
    with pytest.raises(ValueError, match="arguments_invalid"):
        proposal.engine_operations()
