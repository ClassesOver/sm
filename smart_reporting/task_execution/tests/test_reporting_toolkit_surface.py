from smart_reporting.task_execution.execution import TOOL_SPECS, WorkspaceTaskToolkit


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

    instructions = toolkit.instructions or ""
    for unsupported_tool in (
        "create_files",
        "overwrite_file",
        "replace_text",
        "apply_patch",
        "verify",
        "list_files",
        "read_lines",
        "search_text",
        "tree",
        "git_status",
        "git_diff",
        "update_plan",
    ):
        assert unsupported_tool not in instructions


def test_workspace_task_toolkit_does_not_expose_unused_sync_patch_entrypoint() -> None:
    toolkit = WorkspaceTaskToolkit(None, None)  # type: ignore[arg-type]

    assert not hasattr(toolkit.kernel, "apply_patch_sync")
    assert not hasattr(toolkit.kernel, "cleanup_task_outputs")
    assert not hasattr(toolkit.kernel, "batch_copy_files")


def test_tool_specs_cover_only_registered_generic_tools() -> None:
    assert set(TOOL_SPECS) == {
        "finish_task",
        "process",
        "read_file",
        "read_tool_output",
        "terminal",
        "view_image",
    }
