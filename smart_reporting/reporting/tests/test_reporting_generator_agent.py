from agno.models.openai import OpenAIChat

from smart_reporting.reporting.agent import (
    create_reporting_code_agent,
    create_reporting_generator_agent,
)
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
        (
            'facts 文件中 metrics[].periodValues 的每个元素固定为 {"period": string,'
            '"value": number}；必须读取 period，不得使用 periodStart。'
        ),
        (
            "编写每张图的 Matplotlib 调用前，先以冻结 facts 校验待绘制数据：空数据、未知/空/重复占位分类、"
            "缺失声明系列或无法按同月对齐的跨年同比不得绘制；跳过该图并输出结构化诊断。图中数值、单位、"
            "期间和预算执行率必须直接来自冻结 facts；所有中文文字必须可显示，数值标签不得重叠。"
        ),
        (
            "pythonSource 绘图只能使用 Matplotlib；必须在导入 matplotlib.pyplot 之前调用 "
            'matplotlib.use("Agg")，并统一使用 fig.savefig(...) 写入图表文件；'
            "禁止使用 Plotly、Kaleido 或 Seaborn。"
        ),
    ]


def test_visualization_generator_requires_headless_matplotlib_output() -> None:
    agent = create_reporting_generator_agent(
        model=OpenAIChat(
            id="test-model", api_key="test-key", base_url="http://localhost"
        ),
        output_schema=VisualizationScriptDraft,
        name="reporting-visualization-generator",
    )

    instructions = "\n".join(agent.instructions)
    assert "只能使用 Matplotlib" in instructions
    assert 'matplotlib.use("Agg")' in instructions
    assert "导入 matplotlib.pyplot 之前" in instructions
    assert "fig.savefig" in instructions
    assert "禁止使用 Plotly、Kaleido 或 Seaborn" in instructions


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
    assert "普通文本不算成功" in prompt
    assert "unified diff" in prompt
