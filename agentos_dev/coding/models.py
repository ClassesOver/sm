from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class TaskState(StrEnum):
    NEW = "new"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    FINISHING = "finishing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    FINISH_REQUESTED = "finish_requested"
    CLOSED = "closed"


class AttemptOutcome(StrEnum):
    FINISH_ACCEPTED = "finish_accepted"
    NO_FINISH = "no_finish"
    ERROR = "error"
    CANCELLED = "cancelled"
    LOST = "lost"


class InstructionState(StrEnum):
    PENDING = "pending"
    APPLIED = "applied"
    REJECTED = "rejected"


class ExecutionKind(StrEnum):
    TERMINAL = "terminal"
    PROCESS_WRITE = "process_write"
    PROCESS_SUBMIT = "process_submit"
    PATCH = "patch"
    VERIFICATION = "verification"


TERMINAL_TASK_STATES = frozenset({TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED})
RUNNABLE_TASK_STATES = frozenset({TaskState.NEW, TaskState.ACTIVE, TaskState.SUSPENDED})


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CodingScope:
    external_run_id: str
    owner_user_id: str
    thread_id: str
    sandbox_id: str
    agent_id: str


@dataclass(frozen=True)
class Lease:
    owner: str
    epoch: int
    expires_at: datetime


@dataclass(frozen=True)
class TaskSnapshot:
    scope: CodingScope
    state: TaskState
    state_version: int
    lease_epoch: int
    continuation_count: int
    instruction_sequence: int
    current_internal_run_id: str
    current_attempt_no: int
    deadline_at: datetime
    mutation_sequence: int = 0
    same_error_count: int = 0
    error_fingerprint: str | None = None
    predecessor_task_id: str | None = None
    acceptance_contract: dict[str, Any] | None = None
    finish_receipt: dict[str, Any] | None = None
    result_text: str | None = None


@dataclass(frozen=True)
class AttemptSnapshot:
    internal_run_id: str
    external_run_id: str
    attempt_no: int
    state: AttemptState
    resume_count: int
    lease_epoch: int
    outcome: AttemptOutcome | None = None
    agno_status: str | None = None
    terminal_output: str = ""
    error_fingerprint: str | None = None


@dataclass(frozen=True)
class InstructionReceipt:
    instruction_id: str
    sequence: int
    state: InstructionState
    code: str | None = None
    applied_attempt_no: int | None = None


@dataclass(frozen=True)
class CodingEvent:
    event_id: str
    type: str
    data: dict[str, Any] = field(default_factory=dict)
