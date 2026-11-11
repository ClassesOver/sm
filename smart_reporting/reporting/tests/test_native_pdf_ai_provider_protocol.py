"""真实故障形态回归：工具读取正常，未遵循生产结构化协议导致 Markdown 无法校验。"""
import json
from dataclasses import dataclass

import pytest
from agno.models.response import ModelResponse

from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel, sample


@dataclass
class ProviderProtocolModel(ScriptedModel):
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    supports_native_structured_outputs: bool = True

    def invoke(self, *args, **kwargs):
        if len(self.responses) == 1:
            # 与真实故障一致：端点接受 schema 参数，但此模型不兑现 schema；JSON Object 可用。
            structured = kwargs.get("response_format") == {"type": "json_object"}
            self.responses[0] = ModelResponse(content=json.dumps({"answer": "Alpha 42 + Beta 17 = 59 million", "citations": [1, 2]})
                if structured else "## 两页总结\nAlpha 42 + Beta 17 = 59 million")
        return super().invoke(*args, **kwargs)


@pytest.mark.anyio
async def test_pdf_reader_uses_production_json_object_policy_without_losing_tools(monkeypatch):
    from smart_reporting.report_editor import native_pdf_ai as module

    context, content, model = sample()
    model["pages"][0]["textObjects"][0]["text"] = "Alpha revenue is 42 million."
    model["pages"][1]["textObjects"][0]["text"] = "Beta revenue is 17 million."
    monkeypatch.setattr(module, "inspect_pdf", lambda *args, **kwargs: model)
    provider = ProviderProtocolModel(id="deepseek-v4.1-flash", expected_tool_text="Beta revenue is 17", responses=[
        ModelResponse(tool_calls=[{"id": "actual-read", "type": "function", "function": {"name": "read_pages", "arguments": '{"start_page":1,"page_count":2}'}}]),
        ModelResponse(content="provider final response"),
    ])
    result = await module.create_native_pdf_read_planner(provider)(context=context, content=content, operations=[],
        action="summarize", instruction="读取两页并总结合计", selection=[], session_id="protocol-regression", user_id="user")
    assert "59" in result["answer"]
    assert result["coverage"]["fullyReadPages"] == [1, 2]
    assert [citation["pageNumber"] for citation in result["citations"]] == [1, 2]
    assert [event["tool"] for event in result["toolEvents"]] == ["read_pages"]
