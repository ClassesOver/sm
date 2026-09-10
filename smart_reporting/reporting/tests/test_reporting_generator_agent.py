from agno.models.openai import OpenAIChat

from smart_reporting.reporting.agent import (
    create_reporting_code_agent,
    create_reporting_generator_agent,
)
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisEvidenceDecision,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    SectionDecisionOutput,
    VisualizationPlanDraft,
)


def test_reporting_generator_agent_is_structured_and_has_no_tools() -> None:
    model = OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost")
    agent = create_reporting_generator_agent(
        model=model,
        output_schema=VisualizationPlanDraft,
        name="reporting-visualization-generator",
    )
    assert agent.output_schema is VisualizationPlanDraft
    assert agent.structured_outputs is True
    assert agent.use_json_mode is False
    assert agent.tools == []
    assert agent.retries == 0
    assert agent.markdown is False
    assert agent.instructions == [
        "只返回一个严格满足 output_schema 的 JSON 对象，不得返回推理、解释、Markdown 或代码围栏。",
        "所有必填顶层字段必须各出现一次；不得把 schema 顶层字段只写入其他字段。",
        "长文本字段必须是合法 JSON 字符串，换行和引号必须按 JSON 转义。",
        "每个 charts[].sourcePath 必须是 visualizationWorkspace.chartOutputRoot 下带 "
        ".png、.jpg 或 .jpeg 后缀的具体文件。",
    ]


def test_visualization_generator_does_not_carry_python_source_contract() -> None:
    agent = create_reporting_generator_agent(
        model=OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost"),
        output_schema=VisualizationPlanDraft,
        name="reporting-visualization-generator",
    )

    instructions = "\n".join(agent.instructions)
    assert "pythonSource" not in instructions
    assert "Matplotlib" not in instructions


def test_reporting_section_generator_uses_agno_supported_root_model() -> None:
    model = OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost")
    agent = create_reporting_generator_agent(
        model=model,
        output_schema=SectionDecisionOutput,
        name="reporting-section-generator",
    )

    assert agent.output_schema is SectionDecisionOutput
    schema = SectionDecisionOutput.model_json_schema()
    assert schema["discriminator"]["propertyName"] == "kind"
    assert any(
        "根 JSON" in instruction and "kind" in instruction for instruction in agent.instructions
    )


def test_reporting_evidence_generator_has_no_tools_or_source_contract() -> None:
    agent = create_reporting_generator_agent(
        model=OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost"),
        output_schema=AnalysisEvidenceDecision,
        name="reporting-analysis-evidence-generator",
    )

    assert agent.tools == []
    instructions = "\n".join(agent.instructions)
    assert "script" not in instructions
    assert "pythonSource" not in instructions


def test_reporting_code_agent_is_unstructured_and_has_no_history_or_tools() -> None:
    agent = create_reporting_code_agent(
        model=OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost"),
        name="reporting-code-agent",
        role="签发分析脚本",
        instructions=["只修改签发路径。"],
    )

    assert agent.output_schema is None
    assert agent.parse_response is False
    assert agent.structured_outputs is False
    assert agent.use_json_mode is False
    assert agent.tools == []
    assert agent.retries == 0
    assert agent.add_history_to_context is False
    prompt = "\n".join(agent.instructions)
    assert "普通文本、Markdown、代码围栏和解释都不算成功" in prompt
    assert "完整原始 Python 源码" in prompt
