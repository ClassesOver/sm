import pytest
from dingyi_agno import PlatformModel

from smart_reporting.reporting.agent import (
    ReportingPhaseOpenAIChat,
    _report_facade_model,
    _report_model,
    _reporting_code_model,
    _reporting_phase_model,
)
from smart_reporting.reporting.model_policy import (
    ReportingThinkingProfile,
    ThinkingDecision,
    apply_reporting_thinking_profile,
    bind_reporting_thinking,
)
from smart_reporting.runtime.settings import AgentSettings


@pytest.mark.parametrize("platform", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_native_responses_thinking_switch_matches_observation(platform, enabled):
    environ = {
        "AGENT_MODEL_VLLM_REASONING": "true",
        "AGENT_MODEL_VLLM_THINKING_BUDGET": "true",
        "AGENT_MODEL_LITELLM_PROXY": "true",
        "OPENAI_BASE_URL": "http://proxy.test/v1",
        "OPENAI_API_KEY": "test",
        "AGENT_MODEL_STANDARD": "deepseek-v4-flash-0731",
    }
    if platform:
        environ.update(
            DINGYI_PLATFORM_URL="http://platform.test",
            DINGYI_PLATFORM_SERVICE_TOKEN="test",
        )
    settings = AgentSettings.from_environment(environ, load_env_file=False)
    base = _report_model(settings, enable_thinking=not enabled)
    profile = (
        ReportingThinkingProfile.off()
        if enabled
        else ReportingThinkingProfile.on(reasoning_effort="high", thinking_budget=8192)
    )
    apply_reporting_thinking_profile(base, profile)
    model = _reporting_code_model(base)
    decision = ThinkingDecision(
        operation="analysis_script",
        complexity="standard",
        enabled=enabled,
        reasoning_effort="high" if enabled else None,
        thinking_budget=8192 if enabled else 0,
        attempt=1,
        reason="test",
    )
    with bind_reporting_thinking(decision):
        request_model = model._phase_request_model([])
        params = request_model.get_request_params()
    assert params["reasoning"]["effort"] == ("high" if enabled else "none")
    assert params["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": enabled},
    }
    observation = request_model._request_params_observation(params, [])
    assert observation["enableThinking"] is enabled
    assert observation["enableThinkingLocation"] == "chat_template_kwargs"
    assert base.extra_body["chat_template_kwargs"]["thinking"] is (not enabled)
    assert model.extra_body == base.extra_body


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
