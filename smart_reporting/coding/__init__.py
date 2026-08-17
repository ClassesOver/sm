"""纯 Coding 产品公共 API；重型状态机按需加载。"""

# ruff: noqa: F401 - TYPE_CHECKING 导入为延迟公共 API 提供静态类型。

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..task_execution.models import (
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
    from ..task_execution.repository import CodingRepositoryError, CodingTaskRepository
    from ..task_execution.session import TaskSession
    from .adapters import CliCodingAdapter, CodingMemberAdapter
    from .completion import CompletionGate
    from .executor import AgnoCodingExecutor, AgnoRunState
    from .policy import ContinuationAction, ContinuationDecision, ContinuationPolicy
    from .run_manager import InternalRunManager
    from .supervisor import CodingTaskSupervisor


_EXPORT_MODULES = {
    "CliCodingAdapter": ".adapters",
    "CodingMemberAdapter": ".adapters",
    "CompletionGate": ".completion",
    "AgnoCodingExecutor": ".executor",
    "AgnoRunState": ".executor",
    "ContinuationAction": ".policy",
    "ContinuationDecision": ".policy",
    "ContinuationPolicy": ".policy",
    "InternalRunManager": ".run_manager",
    "CodingTaskSupervisor": ".supervisor",
    "AttemptOutcome": "..task_execution.models",
    "AttemptSnapshot": "..task_execution.models",
    "AttemptState": "..task_execution.models",
    "CodingEvent": "..task_execution.models",
    "CodingScope": "..task_execution.models",
    "ExecutionKind": "..task_execution.models",
    "InstructionReceipt": "..task_execution.models",
    "InstructionState": "..task_execution.models",
    "Lease": "..task_execution.models",
    "TaskSnapshot": "..task_execution.models",
    "TaskState": "..task_execution.models",
    "CodingRepositoryError": "..task_execution.repository",
    "CodingTaskRepository": "..task_execution.repository",
    "TaskSession": "..task_execution.session",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


__all__ = list(_EXPORT_MODULES)
