from .adapters import (
    AguiCodingAdapter,
    CliCodingAdapter,
    CodingMemberAdapter,
)
from .completion import CompletionGate
from .executor import AgnoCodingExecutor, AgnoRunState
from .models import (
    AttemptOutcome,
    AttemptSnapshot,
    AttemptState,
    CodingEvent,
    CodingScope,
    ExecutionKind,
    InstructionReceipt,
    InstructionState,
    Lease,
    TaskSnapshot,
    TaskState,
)
from .policy import ContinuationAction, ContinuationDecision, ContinuationPolicy
from .repository import CodingRepositoryError, CodingTaskRepository
from .run_manager import InternalRunManager
from .session import TaskSession
from .supervisor import CodingTaskSupervisor


def create_agentos(settings=None):
    from .agentos import create_agentos as factory

    return factory(settings)


def main() -> None:
    from .agentos import main as run

    run()


__all__ = [
    "AttemptOutcome",
    "AttemptSnapshot",
    "AttemptState",
    "AguiCodingAdapter",
    "AgnoCodingExecutor",
    "AgnoRunState",
    "CodingEvent",
    "CodingMemberAdapter",
    "CompletionGate",
    "CliCodingAdapter",
    "CodingScope",
    "CodingRepositoryError",
    "CodingTaskRepository",
    "ContinuationAction",
    "ContinuationDecision",
    "ContinuationPolicy",
    "ExecutionKind",
    "InstructionReceipt",
    "InstructionState",
    "InternalRunManager",
    "Lease",
    "TaskSnapshot",
    "TaskSession",
    "TaskState",
    "CodingTaskSupervisor",
    "create_agentos",
    "main",
]
