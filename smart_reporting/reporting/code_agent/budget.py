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
    protocol_violations: int = 0
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

    def record_protocol_violation(self) -> None:
        self.protocol_violations += 1

    def raw_protocol_correct(self) -> bool | str:
        if self.custom_inputs == 0 and self.protocol_violations == 0:
            return "unknown"
        return self.invalid_custom_inputs == 0 and self.protocol_violations == 0

    @staticmethod
    def exempt(payload: Mapping) -> bool:
        details = payload.get("details")
        if isinstance(details, Mapping) and details.get("escalated") is True:
            return False
        return (payload.get("code"), payload.get("status")) in {
            ("report_code_delivery_budget_reserved", "rejected"),
            ("report_code_batch_stopped", "skipped"),
            ("report_code_visual_review_redundant", "skipped"),
        }

    @staticmethod
    def snapshot(used: int, limit: int) -> dict[str, int]:
        used = min(limit, max(0, used))
        return {"used": used, "limit": limit, "remaining": limit - used}
