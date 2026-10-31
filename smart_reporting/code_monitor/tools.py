"""Code Agent 工具调用的 DEBUG 观测，不干预执行。"""

import json
from typing import Any

from loguru import logger


def log_tool_event(
    *, session_id: str, call_id: str | None, tool: str, status: str, payload: Any
) -> None:
    limit = 8192
    encoded: list[str] = []

    def text() -> str:
        # 惰性序列化：DEBUG 未启用时不对整段脚本等参数做 json.dumps。
        if not encoded:
            encoded.append(json.dumps(payload, ensure_ascii=False, default=str))
        return encoded[0]

    logger.opt(lazy=True).debug(
        "code_monitor_tool session_id={} call_id={} tool={} status={} truncated={} payload={}",
        lambda: session_id,
        lambda: call_id,
        lambda: tool,
        lambda: status,
        lambda: len(text()) > limit,
        lambda: text()[:limit],
    )
