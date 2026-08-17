from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from ..task_execution.models import AttemptSnapshot, TaskSnapshot, utcnow


class CompletionGate:
    """生成 finish_task 通过全部外部检查后的不可变完成回执。"""

    def build_receipt(
        self,
        task: TaskSnapshot,
        attempt: AttemptSnapshot,
        *,
        summary: str,
        artifacts: list[dict[str, Any]],
        verification_ids: list[str],
        service_sessions: list[dict[str, str]],
        accepted_at: datetime | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        receipt: dict[str, Any] = {
            "taskId": task.scope.external_run_id,
            "attemptNo": attempt.attempt_no,
            "internalRunId": attempt.internal_run_id,
            "sandboxId": task.scope.sandbox_id,
            "mutationSequence": task.mutation_sequence,
            "summary": summary,
            "artifacts": artifacts,
            "verificationIds": verification_ids,
            "serviceSessions": service_sessions,
            "acceptedAt": (accepted_at or utcnow()).isoformat(),
            **(extra or {}),
        }
        receipt["digest"] = hashlib.sha256(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return receipt
