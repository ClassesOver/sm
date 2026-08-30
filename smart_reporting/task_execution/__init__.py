"""领域无关的受控软件任务执行原语。"""

from .models import CodingScope, TaskState
from .repository import CodingRepositoryError, CodingTaskRepository

TaskExecutionRepository = CodingTaskRepository
TaskScope = CodingScope

__all__ = [
    "CodingRepositoryError",
    "CodingScope",
    "CodingTaskRepository",
    "TaskState",
    "TaskExecutionRepository",
    "TaskScope",
    "TaskExecutionKernel",
    "WorkspaceTaskToolkit",
    "create_files_patch",
]


def __getattr__(name: str):
    if name in {"TaskExecutionKernel", "WorkspaceTaskToolkit", "create_files_patch"}:
        from .execution import TaskExecutionKernel, WorkspaceTaskToolkit, create_files_patch

        return {
            "TaskExecutionKernel": TaskExecutionKernel,
            "WorkspaceTaskToolkit": WorkspaceTaskToolkit,
            "create_files_patch": create_files_patch,
        }[name]
    raise AttributeError(name)
