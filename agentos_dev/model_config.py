from collections.abc import Callable

AgentInstructions = str | list[str] | Callable[..., str | list[str]]

OPENAI_COMPATIBLE_ROLE_MAP = {
    "system": "system",
    "user": "user",
    "assistant": "assistant",
    "tool": "tool",
    "model": "assistant",
}
