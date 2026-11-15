"""Office 文件内 AI 模型：按部署配置独立创建，并遵守结构化执行器的 wire schema 契约。"""

from smart_reporting.office.model import OfficeOpenAIChat, create_office_model
from smart_reporting.reporting.structured_output.policy import REPORTING_STRUCTURED_MODES_MODEL_ATTR
from smart_reporting.reporting.structured_output.wire_schema import REPORTING_WIRE_SCHEMA_MODEL_ATTR
from smart_reporting.runtime.settings import AgentSettings


def _settings() -> AgentSettings:
    return AgentSettings.from_environment(
        {
            "OPENAI_BASE_URL": "https://example.invalid/v1",
            "OPENAI_API_KEY": "test-key",
            "AGENT_MODEL_STANDARD": "office-standard",
        },
        load_env_file=False,
    )


def test_office_model_is_built_from_settings_without_report_runtime():
    settings = _settings()
    model = create_office_model(settings)

    assert isinstance(model, OfficeOpenAIChat)
    assert model.id == "office-standard"
    assert model.max_tokens == settings.report_output_token_reserve
    assert getattr(model, "_task_execution_input_token_budget") > 0
    assert set(getattr(model, REPORTING_STRUCTURED_MODES_MODEL_ATTR)) == {"fast", "standard", "strong"}


def test_office_model_sends_registered_wire_schema_instead_of_domain_schema():
    model = create_office_model(_settings())
    wire = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    setattr(model, REPORTING_WIRE_SCHEMA_MODEL_ATTR, wire)

    params = model.get_request_params(
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "Domain", "schema": {"type": "object"}, "strict": True},
        }
    )

    assert params["response_format"]["json_schema"]["schema"] == wire
    assert params["response_format"]["json_schema"]["name"] == "Domain"
