from agno.models.openai import OpenAIChat

from smart_reporting.reporting.agent import create_reporting_generator_agent
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import AnalysisEvidencePlan
from smart_reporting.reporting.workflow.runtime.phase_models import (
    SectionDecisionOutput,
    VisualizationScriptDraft,
)


def test_reporting_generator_agent_is_structured_and_has_no_tools() -> None:
    model = OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost")
    agent = create_reporting_generator_agent(
        model=model,
        output_schema=VisualizationScriptDraft,
        name="reporting-visualization-generator",
    )
    assert agent.output_schema is VisualizationScriptDraft
    assert agent.structured_outputs is True
    assert agent.use_json_mode is False
    assert agent.tools == []
    assert agent.retries == 0
    assert agent.markdown is False
    assert agent.instructions == [
        "只返回一个严格满足 output_schema 的 JSON 对象，不得返回推理、解释、Markdown 或代码围栏。",
        "所有必填顶层字段必须各出现一次；不得把 charts 等顶层字段只写入 pythonSource。",
        "pythonSource 等长文本字段必须是合法 JSON 字符串，换行和引号必须按 JSON 转义。",
        "每个 charts[].sourcePath 必须是 visualizationWorkspace.chartOutputRoot 下带 "
        ".png、.jpg 或 .jpeg 后缀的具体文件；pythonSource 必须写入完全相同的路径。",
        (
            "pythonSource 是由固定 Workflow 执行的独立 Python 程序；不得调用或导入 "
            "submit_visualization_charts、run_python_script、apply_analysis_patch 等编排工具，"
            "不得把工具参数或调用写进脚本。"
        ),
        (
            "Python 从工作区根目录执行；逐字使用任务 JSON 签发的 factFile.path 和输出路径，"
            "不得使用 __file__、Path.parents、cwd 或目录探测重新推导路径。"
        ),
        "pythonSource 必须使用 Python 的 None、True、False，不得写入 JSON 常量 null、true、false。",
    ]


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


def test_reporting_evidence_generator_declares_mutually_exclusive_branches() -> None:
    agent = create_reporting_generator_agent(
        model=OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost"),
        output_schema=AnalysisEvidencePlan,
        name="reporting-analysis-evidence-generator",
    )

    assert any(
        "requiresSupplementalEvidence=true" in instruction and "script" in instruction
        for instruction in agent.instructions
    )
    assert any("script 必须是完整" in instruction for instruction in agent.instructions)
