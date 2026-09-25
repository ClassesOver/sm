"""Coding task budget transitions; Agno remains authoritative for tool charges."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass
class CodeBudget:
    request_limit: int
    reserve: int
    requests: int = 0
    rejections: int = 0
    tool_calls: int = 0
    custom_inputs: int = 0
    invalid_custom_inputs: int = 0
    envelope_normalized_inputs: int = 0
    wire_shape_rejections: int = 0
    protocol_violations: int = 0
    stage_mismatch_rejections: int = 0
    continued: bool = False

    def claim_continuation(self, tool_limit: int) -> int | None:
        remaining = tool_limit - self.tool_calls
        if self.continued or self.requests >= self.request_limit or remaining <= 0:
            return None
        self.continued = True
        return remaining

    def consume_request(self) -> bool:
        if self.requests >= self.request_limit:
            return False
        self.requests += 1
        return True

    def reserved(self, used: int, limit: int | None) -> bool:
        return limit is not None and used >= limit - self.reserve

    def reject_exploration(self) -> bool:
        self.rejections += 1
        return self.rejections >= 2

    def delivery_succeeded(self) -> None:
        self.rejections = 0

    def record_custom_input(self, *, protocol_correct: bool) -> None:
        self.custom_inputs += 1
        if not protocol_correct:
            self.invalid_custom_inputs += 1

    def record_envelope_normalized(self) -> None:
        # provider 把 free-form 输入包进单层 data 信封：宿主兼容解封执行，不记协议
        # 违规，单列计数作为 provider 稳定性观测指标（rawProtocolCorrect 只统计真违规）。
        self.envelope_normalized_inputs += 1

    def record_wire_shape_rejection(self) -> None:
        # provider grammar 退化时任务集内 FREEFORM 工具可能以 function 形态返回。
        # 只有结构化 custom_tool_call 可执行，该调用补未执行回执；单列计数并设上限，
        # 超限后按协议违规终止，防止 wire 混淆无限循环。
        self.wire_shape_rejections += 1

    def record_protocol_violation(self) -> None:
        self.protocol_violations += 1

    def record_stage_mismatch_rejection(self) -> None:
        # 工具在任务集内且 wire 类型正确，只是不在当前交付阶段白名单：这是状态机
        # 与模型的博弈信号，不是 provider 协议异常；单列计数，不计入
        # rawProtocolCorrect 的违规口径。
        self.stage_mismatch_rejections += 1

    def raw_protocol_correct(self) -> bool | str:
        # function 形态的 FREEFORM 调用虽以软拒绝继续，仍是 provider wire 协议偏差。
        if (
            self.custom_inputs == 0
            and self.protocol_violations == 0
            and self.wire_shape_rejections == 0
        ):
            return "unknown"
        return (
            self.invalid_custom_inputs == 0
            and self.protocol_violations == 0
            and self.wire_shape_rejections == 0
        )

    @staticmethod
    def exempt(payload: Mapping) -> bool:
        details = payload.get("details")
        if isinstance(details, Mapping) and details.get("escalated") is True:
            return False
        return (payload.get("code"), payload.get("status")) in {
            ("report_code_delivery_budget_reserved", "rejected"),
            ("report_code_batch_stopped", "skipped"),
            ("report_code_visual_review_redundant", "skipped"),
            ("report_code_stage_tool_unavailable", "rejected"),
            ("report_code_tool_wire_type_invalid", "rejected"),
        }

    @staticmethod
    def snapshot(used: int, limit: int) -> dict[str, int]:
        used = min(limit, max(0, used))
        return {"used": used, "limit": limit, "remaining": limit - used}
