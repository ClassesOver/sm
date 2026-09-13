from dingyi_agno import PlatformModel

from smart_reporting.reporting.agent import (
    ReportingPhaseOpenAIChat,
    _report_facade_model,
    _report_model,
    _reporting_code_model,
    _reporting_phase_model,
)
from smart_reporting.runtime.settings import AgentSettings


def test_platform_defaults_allow_component_binding_to_choose_models():
    settings = AgentSettings.from_environment({
        "DINGYI_PLATFORM_URL": "http://platform.test",
        "DINGYI_PLATFORM_SERVICE_TOKEN": "test-service-token",
    }, load_env_file=False)
    assert settings.model_fast_id == "platform-managed"
    assert settings.model_standard_id == "platform-managed"
    assert settings.model_strong_id == "platform-managed"


def test_platform_sdk_identity_survives_report_model_wrappers():
    settings = AgentSettings.from_environment({
        "DINGYI_PLATFORM_URL": "http://platform.test",
        "DINGYI_PLATFORM_SERVICE_TOKEN": "test-service-token",
        "AGENT_MODEL_STANDARD": "configured-profile",
    }, load_env_file=False)
    model = _report_model(settings, enable_thinking=False)
    assert isinstance(model, PlatformModel)
    assert model.id == "configured-profile"
    for wrapped in (
        model,
        _reporting_phase_model(model),
        _report_facade_model(_reporting_phase_model(model)),
        _reporting_code_model(_reporting_phase_model(model)),
    ):
        assert wrapped.base_url == "http://platform.test/llm/v1"
        assert wrapped.api_key == "test-service-token"
        assert wrapped.extra_headers["X-Agno-Component-Id"] == "smart-reporting"
        assert wrapped.extra_headers["X-Agno-Component-Type"] == "agent"


def test_gateway_url_does_not_imply_qwen_reasoning_protocol():
    model = ReportingPhaseOpenAIChat(
        id="another-model", base_url="http://platform.test/llm/v1",
        reasoning_effort="high", extra_body={"thinking_budget": 1024},
    )
    assert model.get_request_params()["reasoning_effort"] == "high"
