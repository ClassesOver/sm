from agno.models.openai import OpenAIChat

from smart_reporting.reporting.agent import create_reporting_generator_agent
from smart_reporting.reporting.workflow.runtime.phase_models import VisualizationScriptDraft


def test_reporting_generator_agent_is_structured_and_has_no_tools() -> None:
    model = OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost")
    agent = create_reporting_generator_agent(
        model=model,
        output_schema=VisualizationScriptDraft,
        name="reporting-visualization-generator",
    )
    assert agent.output_schema is VisualizationScriptDraft
    assert agent.tools == []
    assert agent.retries == 0
    assert agent.markdown is False
