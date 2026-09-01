from smart_reporting.task_execution.execution import WorkspaceTaskToolkit


def test_workspace_task_toolkit_exposes_only_reporting_execution_primitives() -> None:
    toolkit = WorkspaceTaskToolkit(None, None)  # type: ignore[arg-type]

    assert set(toolkit.async_functions) == {
        "finish_task",
        "process",
        "read_file",
        "read_tool_output",
        "terminal",
        "view_image",
    }
