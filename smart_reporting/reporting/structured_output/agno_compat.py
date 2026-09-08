"""Agno 结构化响应解析的 Reporting 兼容边界。"""

from __future__ import annotations

from typing import Any

from agno.agent import _response as agno_response
from agno.utils import string as agno_string
from pydantic import ValidationError

from .execution import _validate_structured_text

_ORIGINAL_PARSE_RESPONSE_MODEL_STR = agno_string.parse_response_model_str


def _parse_reporting_response_model(content: str, output_schema: type[Any]) -> Any | None:
    module = str(getattr(output_schema, "__module__", ""))
    if not module.startswith("smart_reporting.reporting."):
        return _ORIGINAL_PARSE_RESPONSE_MODEL_STR(content, output_schema)
    json_validator = getattr(output_schema, "model_validate_json", None)
    if not callable(json_validator):
        return _ORIGINAL_PARSE_RESPONSE_MODEL_STR(content, output_schema)
    try:
        return _validate_structured_text(content, output_schema, json_validator)
    except ValidationError:
        # ReportingStructuredOutputExecutor 保留原始响应并统一生成安全的纠错 issues。
        return None


def install_agno_structured_output_parser() -> None:
    """幂等安装完整对象解析器，禁止 Agno 拼接残缺的 Reporting JSON。"""

    agno_string.parse_response_model_str = _parse_reporting_response_model
    # agno.agent._response 使用模块级导入别名，必须同步替换真实调用点。
    agno_response.parse_response_model_str = _parse_reporting_response_model
