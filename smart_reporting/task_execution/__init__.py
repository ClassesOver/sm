"""领域无关的受控任务执行原语。"""

from .models import (
    AttemptSnapshot,
    AttemptState,
    Lease,
    TaskExecutionScope,
    TaskSnapshot,
    TaskState,
)
from .repository import TaskExecutionRepository, TaskExecutionRepositoryError
from .session import TaskSession

__all__ = [
    "TaskExecutionRepositoryError",
    "AttemptSnapshot",
    "AttemptState",
    "Lease",
    "TaskExecutionScope",
    "TaskExecutionRepository",
    "TaskSnapshot",
    "TaskState",
    "TaskSession",
    "TASK_EXECUTION_CONTEXT_TOKEN_LIMIT",
    "TASK_EXECUTION_OUTPUT_TOKEN_RESERVE",
    "TaskExecutionKernel",
    "TaskExecutionRuntime",
    "TASK_EXECUTION_DEPENDENCY",
    "TASK_EXECUTION_TOOL_FAILURE_STATE_KEY",
    "TASK_EXECUTION_TOOL_PROGRESS_STATE_KEY",
    "DEFAULT_TERMINAL_TIMEOUT",
    "MAX_READ_FILE_BYTES",
    "MAX_TERMINAL_COMMAND_BYTES",
    "MAX_TOOL_OUTPUT_READ_BYTES",
    "MAX_TOOL_FAILURE_ENTRIES",
    "MAX_TOOL_PROGRESS_ENTRIES",
    "NO_PROGRESS_EXEMPT_TOOLS",
    "TOOL_SPECS",
    "ToolSpec",
    "absolute_paths",
    "create_task_tool_scheduler_hook",
    "failed_result_resources",
    "is_read_only_terminal_command",
    "is_task_tool_scheduler_hook",
    "normalize_task_function_call_arguments",
    "paths_related",
    "stable_progress_result",
    "suggested_workspace_path",
    "TERMINAL_EXECUTION_STATUSES",
    "create_files_patch",
    "abuild_workspace_changes",
    "build_workspace_changes",
    "parse_unified_diff",
]


def __getattr__(name: str):
    if name in {
        "TASK_EXECUTION_CONTEXT_TOKEN_LIMIT",
        "TASK_EXECUTION_OUTPUT_TOKEN_RESERVE",
    }:
        from .. import context_management

        return getattr(context_management, name)
    execution_exports = {
        "TaskExecutionKernel",
        "TaskExecutionRuntime",
        "TASK_EXECUTION_DEPENDENCY",
        "TASK_EXECUTION_TOOL_FAILURE_STATE_KEY",
        "TASK_EXECUTION_TOOL_PROGRESS_STATE_KEY",
        "DEFAULT_TERMINAL_TIMEOUT",
        "MAX_READ_FILE_BYTES",
        "MAX_TERMINAL_COMMAND_BYTES",
        "MAX_TOOL_OUTPUT_READ_BYTES",
        "MAX_TOOL_FAILURE_ENTRIES",
        "MAX_TOOL_PROGRESS_ENTRIES",
        "NO_PROGRESS_EXEMPT_TOOLS",
        "TOOL_SPECS",
        "ToolSpec",
        "absolute_paths",
        "create_files_patch",
        "create_task_tool_scheduler_hook",
        "failed_result_resources",
        "is_read_only_terminal_command",
        "is_task_tool_scheduler_hook",
        "normalize_task_function_call_arguments",
        "paths_related",
        "stable_progress_result",
        "suggested_workspace_path",
    }
    if name in execution_exports:
        from . import execution

        return getattr(execution, name)
    if name == "TERMINAL_EXECUTION_STATUSES":
        from .repository import TERMINAL_EXECUTION_STATUSES

        return TERMINAL_EXECUTION_STATUSES
    if name in {"abuild_workspace_changes", "build_workspace_changes", "parse_unified_diff"}:
        from .changes import abuild_workspace_changes, build_workspace_changes, parse_unified_diff

        return {
            "abuild_workspace_changes": abuild_workspace_changes,
            "build_workspace_changes": build_workspace_changes,
            "parse_unified_diff": parse_unified_diff,
        }[name]
    raise AttributeError(name)
