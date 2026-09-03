"""模型路由的 Loguru 观测边界。"""

from __future__ import annotations

from collections.abc import Mapping

from loguru import logger


def log_model_selection(fields: Mapping[str, object]) -> None:
    """记录不含 prompt、响应和凭据的稳定选择事件。"""

    logger.info(
        "report_model_selected task_kind={} complexity={} tier={} model_id={} "
        "attempt={} reason={} policy_version={}",
        fields.get("task_kind", "-"),
        fields.get("complexity", "-"),
        fields.get("tier", "-"),
        fields.get("model_id", "-"),
        fields.get("attempt", 0),
        fields.get("reason", "-"),
        fields.get("policy_version", "v1"),
    )
