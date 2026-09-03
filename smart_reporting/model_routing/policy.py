"""Reporting 的默认三档模型目录和阶段策略。"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from .models import ModelProfile, ModelTier, TaskPolicy

DEFAULT_FAST_MODEL_ID = "qwen3.6-35b-a3b"
DEFAULT_STANDARD_MODEL_ID = "deepseek-v4-flash-0731"
DEFAULT_STRONG_MODEL_ID = "deepseek-v4-flash-0731"


DEFAULT_MODEL_PROFILES: Mapping[ModelTier, ModelProfile] = MappingProxyType(
    {
        "fast": ModelProfile(tier="fast", model_id=DEFAULT_FAST_MODEL_ID, reasoning_effort="off"),
        "standard": ModelProfile(
            tier="standard", model_id=DEFAULT_STANDARD_MODEL_ID, reasoning_effort="high"
        ),
        "strong": ModelProfile(
            tier="strong", model_id=DEFAULT_STRONG_MODEL_ID, reasoning_effort="max"
        ),
    }
)


def build_model_profiles(
    *,
    fast_model_id: str = DEFAULT_FAST_MODEL_ID,
    standard_model_id: str = DEFAULT_STANDARD_MODEL_ID,
    strong_model_id: str = DEFAULT_STRONG_MODEL_ID,
) -> Mapping[ModelTier, ModelProfile]:
    """根据部署配置创建完整三档目录；空 ID 由 ModelProfile 拒绝。"""

    return MappingProxyType(
        {
            "fast": ModelProfile(
                tier="fast", model_id=fast_model_id.strip(), reasoning_effort="off"
            ),
            "standard": ModelProfile(
                tier="standard", model_id=standard_model_id.strip(), reasoning_effort="high"
            ),
            "strong": ModelProfile(
                tier="strong", model_id=strong_model_id.strip(), reasoning_effort="max"
            ),
        }
    )


def _policy(task_kind: str, tiers: tuple[ModelTier, ModelTier, ModelTier]) -> TaskPolicy:
    return TaskPolicy(task_kind, *tiers)


DEFAULT_TASK_POLICIES: Mapping[str, TaskPolicy] = MappingProxyType(
    {
        "facade": _policy("facade", ("standard", "standard", "standard")),
        "data_understanding": _policy("data_understanding", ("fast", "standard", "strong")),
        "outline_planning": _policy("outline_planning", ("fast", "standard", "strong")),
        "sql_planning": _policy("sql_planning", ("standard", "standard", "strong")),
        "analysis_item": _policy("analysis_item", ("standard", "standard", "strong")),
        "section_generation": _policy("section_generation", ("standard", "standard", "strong")),
        "visualization_section": _policy(
            "visualization_section", ("standard", "standard", "strong")
        ),
    }
)
