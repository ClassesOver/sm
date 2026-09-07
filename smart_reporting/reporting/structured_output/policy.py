"""Reporting 模型结构化输出能力策略。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from ...integrations.model_config import is_dashscope_endpoint

REPORTING_STRUCTURED_MODES_MODEL_ATTR = "_reporting_structured_modes"
REPORTING_STRUCTURED_REQUEST_MODEL_ATTR = "_reporting_structured_request"
REPORTING_VERIFIED_STRUCTURED_MODES_MODEL_ATTR = "_reporting_verified_structured_modes"

_QWEN_MODEL_PATTERN = re.compile(r"(?:^|[/\\:_-])qwen(?:\d|[/\\:_-])", re.IGNORECASE)
_DASHSCOPE_JSON_SCHEMA_QWEN_PATTERN = re.compile(
    r"(?:^|[/\\:_-])qwen3\.(?:7-(?:plus|flash|max)|8-(?:flash|max))(?:$|[/\\:_-])",
    re.IGNORECASE,
)


class StructuredOutputMode(StrEnum):
    """Agno 向当前模型提交结构契约的传输方式。"""

    JSON_OBJECT = "json_object"
    JSON_SCHEMA = "json_schema"


@dataclass(frozen=True, slots=True)
class ModelStructuredCapabilities:
    """一个已选模型经过真实 Reporting 验证的结构化输出能力。"""

    primary: StructuredOutputMode
    fallback: StructuredOutputMode | None
    source: str = "configured_model_tier"


class VerifiedModelCapabilityResolver:
    """把模型档位配置解析为与具体模型供应商解耦的协议计划。"""

    def resolve(
        self,
        model_id: str,
        *,
        configured_mode: str | StructuredOutputMode | None = None,
        verified_mode: str | StructuredOutputMode | None = None,
        endpoint: str | None = None,
    ) -> ModelStructuredCapabilities:
        try:
            mode = StructuredOutputMode(
                verified_mode or configured_mode or StructuredOutputMode.JSON_SCHEMA
            )
        except ValueError as error:
            raise ValueError("Reporting 结构化输出模式配置无效") from error
        source = "runtime_verified_mode" if verified_mode is not None else "configured_model_tier"
        if (
            mode is StructuredOutputMode.JSON_SCHEMA
            and is_dashscope_endpoint(endpoint)
            and _QWEN_MODEL_PATTERN.search(model_id)
            and not _DASHSCOPE_JSON_SCHEMA_QWEN_PATTERN.search(model_id)
        ):
            # DashScope 官方仅为 Qwen3.7 Plus、Qwen3.7/3.8 Flash 和 Max
            # 系列承诺 JSON Schema。其他 Qwen（包括 3.6、3.8 Plus 与开源
            # 权重系列）只能按 json_object 生成后再执行领域 Pydantic 校验，
            # 不能把偶发成功当成能力。
            mode = StructuredOutputMode.JSON_OBJECT
            source = "provider_model_capability"
        fallback = (
            StructuredOutputMode.JSON_OBJECT if mode is StructuredOutputMode.JSON_SCHEMA else None
        )
        return ModelStructuredCapabilities(
            primary=mode,
            fallback=fallback,
            source=source,
        )
