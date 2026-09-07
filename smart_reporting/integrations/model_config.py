import re
from typing import Any
from urllib.parse import urlparse

_QWEN_MODEL_PATTERN = re.compile(r"(?:^|[/\\:_-])qwen(?:\d|[/\\:_-])", re.IGNORECASE)

OPENAI_COMPATIBLE_ROLE_MAP = {
    "system": "system",
    "user": "user",
    "assistant": "assistant",
    "tool": "tool",
    "model": "assistant",
}


def is_dashscope_endpoint(endpoint: str | None) -> bool:
    if not endpoint:
        return False
    hostname = (urlparse(endpoint).hostname or "").casefold()
    return hostname.endswith(".maas.aliyuncs.com") or hostname in {
        "dashscope.aliyuncs.com",
        "dashscope-intl.aliyuncs.com",
    }


def is_ark_endpoint(endpoint: str | None) -> bool:
    if not endpoint:
        return False
    hostname = (urlparse(endpoint).hostname or "").casefold()
    return bool(re.fullmatch(r"ark\.[a-z0-9-]+\.volces\.com", hostname))


def normalize_openai_chat_output_limit(
    params: dict[str, Any],
    *,
    endpoint: str | None,
    structured_output: bool,
) -> dict[str, Any]:
    """按兼容端点的公开 Chat API 契约投影统一输出预算。"""

    normalized = dict(params)
    extra_body = normalized.get("extra_body")
    uses_vllm_protocol = isinstance(extra_body, dict) and isinstance(
        extra_body.get("chat_template_kwargs"), dict
    )

    if structured_output and is_dashscope_endpoint(endpoint):
        # DashScope 官方要求结构化输出时不设置 max_tokens，省略后才会使用
        # 模型最大输出长度，避免人为上限在 JSON 闭合前截断响应。
        normalized.pop("max_tokens", None)
        normalized.pop("max_completion_tokens", None)
        return normalized

    if is_ark_endpoint(endpoint) or uses_vllm_protocol:
        # Ark Chat API 使用 max_completion_tokens 约束思维链与最终回答总长度；
        # vLLM 当前同时兼容两者，但已将 max_tokens 标记为弃用。一次请求只发送
        # 一个字段，防止兼容网关对冲突参数采用不同优先级。
        completion_limit = normalized.get("max_completion_tokens")
        if completion_limit is None:
            completion_limit = normalized.get("max_tokens")
        normalized.pop("max_tokens", None)
        if completion_limit is not None:
            normalized["max_completion_tokens"] = completion_limit
    return normalized


def normalize_openai_chat_reasoning(
    params: dict[str, Any],
    *,
    endpoint: str | None,
) -> dict[str, Any]:
    """把内部统一 thinking 配置投影为端点公开的 Chat API 参数。"""

    if not is_ark_endpoint(endpoint):
        return params
    normalized = dict(params)
    raw_extra_body = normalized.get("extra_body")
    if not isinstance(raw_extra_body, dict):
        return normalized
    extra_body = dict(raw_extra_body)
    enabled = extra_body.pop("enable_thinking", None)
    # Ark 使用顶层 reasoning_effort 控制思考长度，不接受 DashScope 的预算字段。
    extra_body.pop("thinking_budget", None)
    if isinstance(enabled, bool):
        extra_body["thinking"] = {"type": "enabled" if enabled else "disabled"}
    if extra_body:
        normalized["extra_body"] = extra_body
    else:
        normalized.pop("extra_body", None)
    return normalized


def uses_dashscope_qwen_thinking_protocol(model_id: str | None, endpoint: str | None) -> bool:
    return bool(_QWEN_MODEL_PATTERN.search(str(model_id or "")) and is_dashscope_endpoint(endpoint))


def openai_compatible_extra_body(
    *,
    enable_thinking: bool | None,
    use_vllm_reasoning: bool,
) -> dict[str, Any] | None:
    extra_body: dict[str, Any] = {}
    if enable_thinking is not None:
        extra_body["enable_thinking"] = enable_thinking
    if use_vllm_reasoning:
        extra_body["chat_template_kwargs"] = {}
    return extra_body or None


def reasoning_transport_fields(
    *,
    extra_body: dict[str, Any],
    enabled: bool,
    reasoning_effort: str | None,
) -> tuple[dict[str, Any], str | None]:
    body = dict(extra_body)
    raw_template_kwargs = body.get("chat_template_kwargs")
    if not isinstance(raw_template_kwargs, dict):
        # 普通 OpenAI-compatible 传输完全服从调用方传值。Coding 历史行为在
        # enable_thinking=false 时仍保留顶层 effort，不能在共享层擅自清除。
        return body, reasoning_effort

    # vLLM 的 DeepSeek V4 recipe 要求 thinking 配置进入 chat template。
    # 空字典由环境能力开关在模型装配时放入，作为 transport 标记；未带标记的
    # OpenAI-compatible 服务继续使用 Agno 顶层 reasoning_effort，避免云端漂移。
    template_kwargs = dict(raw_template_kwargs)
    template_kwargs["enable_thinking"] = enabled
    template_kwargs["thinking"] = enabled
    if enabled and reasoning_effort is not None:
        template_kwargs["reasoning_effort"] = reasoning_effort
    else:
        template_kwargs.pop("reasoning_effort", None)
    body["chat_template_kwargs"] = template_kwargs
    return body, None
