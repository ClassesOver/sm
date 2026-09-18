"""Code Agent 工具调用的 INFO 观测，不干预执行。"""

import json
from typing import Any

from loguru import logger


def log_tool_event(*, session_id: str, call_id: str | None, tool: str,
                   status: str, payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    limit = 8192
    logger.info(
        "code_monitor_tool session_id={} call_id={} tool={} status={} truncated={} payload={}",
        session_id, call_id, tool, status, len(text) > limit, text[:limit],
    )
