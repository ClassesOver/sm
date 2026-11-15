from urllib.parse import urlsplit

from agno.models.openai import OpenAIChat

from ..runtime.settings import AgentSettings


def office_model(settings: AgentSettings, fallback):
    """Select the server-side GenOffice model while preserving the report route."""
    model_id, base_url, api_key = (settings.office_model_id, settings.office_model_base_url,
                                   settings.office_model_api_key)
    if not settings.native_ai_enabled or not any((model_id, base_url, api_key)):
        return fallback
    if not model_id or not base_url:
        raise ValueError("配置 GenOffice 独立模型时须同时设置 AGENT_OFFICE_MODEL 和 AGENT_OFFICE_MODEL_BASE_URL。")
    try:
        endpoint = urlsplit(base_url)
        valid = endpoint.scheme in {"http", "https"} and endpoint.hostname and endpoint.port != 0
    except ValueError:
        valid = False
    if not valid or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        raise ValueError("AGENT_OFFICE_MODEL_BASE_URL 必须是有效的 HTTP(S) API 地址，凭据请单独配置。")
    return OpenAIChat(id=model_id, base_url=base_url, api_key=api_key or "not-required",
                      timeout=settings.model_timeout_seconds)
