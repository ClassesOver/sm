"""Reporting 模型结构化输出能力策略。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

REPORTING_STRUCTURED_MODES_MODEL_ATTR = "_reporting_structured_modes"


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
    ) -> ModelStructuredCapabilities:
        del model_id
        try:
            mode = StructuredOutputMode(configured_mode or StructuredOutputMode.JSON_OBJECT)
        except ValueError as error:
            raise ValueError("Reporting 结构化输出模式配置无效") from error
        fallback = (
            StructuredOutputMode.JSON_OBJECT if mode is StructuredOutputMode.JSON_SCHEMA else None
        )
        return ModelStructuredCapabilities(primary=mode, fallback=fallback)
