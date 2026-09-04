from typing import Any

OPENAI_COMPATIBLE_ROLE_MAP = {
    "system": "system",
    "user": "user",
    "assistant": "assistant",
    "tool": "tool",
    "model": "assistant",
}


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
