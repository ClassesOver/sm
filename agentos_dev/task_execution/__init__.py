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
]
