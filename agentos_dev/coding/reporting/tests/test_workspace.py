import json
import uuid

import pytest
from agno.models.message import Message
from agno.run import RunContext
from agno.run.agent import RunOutput

from agentos_dev.coding.reporting.agent import enforce_report_delivery_output
from agentos_dev.coding.reporting.tests.workspace_fakes import (
    AsyncFakeClient,
    AsyncMemoryRegistry,
    service,
)
from agentos_dev.coding.reporting.workspace import (
    REPORT_DELIVERY_INCOMPLETE_MESSAGE,
    REPORT_DELIVERY_STATE_KEY,
    REPORT_JOBS_STATE_KEY,
    REPORT_RUNTIME_TIMEOUT_SECONDS,
    WorkspaceReportToolkit,
)
from agentos_dev.workspace import (
    MAX_BRANCH_FILE_BYTES,
    MAX_DOWNLOAD_BYTES,
    MAX_IMAGE_BYTES,
    MAX_PROCESS_INPUT_BYTES,
    MAX_TOOL_OUTPUT_BYTES,
    MAX_UPLOAD_BYTES,
    WORKSPACE_ROOT,
    BaseToolkit,
    DaytonaToolkit,
    WorkspaceError,
    WorkspaceService,
    WorkspaceToolkit,
)


class _ReportStateService:
    def __init__(self):
        self.entries = {
            "报表/数据集/收入.csv": {
                "path": "报表/数据集/收入.csv",
                "size": 12,
                "sha256": "a" * 64,
            }
        }

    async def ahash_file(self, _thread, path):
        return dict(self.entries[path])


class _ReportDatasetResolver:
    async def resolve_dataset_paths(self, dataset_ids, *, run_context=None):
        assert dataset_ids == ["dataset-income"]
        assert run_context is not None
        return ["报表/数据集/收入.csv"]


@pytest.mark.anyio
async def test_报表任务由session_state恢复并拒绝跨thread复用和超限污染():
    service = _ReportStateService()
    context = RunContext(run_id="run-1", session_id="thread", session_state={})
    prepared = await WorkspaceReportToolkit(
        service, _ReportDatasetResolver()
    ).report_prepare_dataset(["dataset-income"], run_context=context)

    restarted = WorkspaceReportToolkit(service, _ReportDatasetResolver())
    status = await restarted.report_job_status(prepared["jobId"], run_context=context)

    assert status["status"] == "prepared"
    assert status["sources"][0]["changed"] is False
    assert prepared["jobId"] in context.session_state[REPORT_JOBS_STATE_KEY]

    other_context = RunContext(
        run_id="run-2",
        session_id="other-thread",
        session_state=json.loads(json.dumps(context.session_state)),
    )
    with pytest.raises(WorkspaceError, match="不属于当前对话"):
        await restarted.report_job_status(prepared["jobId"], run_context=other_context)

    job = restarted._load_job(prepared["jobId"], context)
    before = json.loads(json.dumps(context.session_state))
    job["validation"] = {"ok": True, "pages": ["x" * (64 * 1024)]}
    with pytest.raises(WorkspaceError, match="超过服务端边界"):
        restarted._store_job(job, context)
    assert context.session_state == before


@pytest.mark.anyio
async def test_报表交付只接受当前请求触达且仍通过哈希复核的产物():
    service = _ReportStateService()
    service.entries.update(
        {
            "报表/年度收入.md": {
                "path": "报表/年度收入.md",
                "size": 21,
                "sha256": "b" * 64,
            },
            "报表/年度收入.pdf": {
                "path": "报表/年度收入.pdf",
                "size": 34,
                "sha256": "c" * 64,
            },
        }
    )
    toolkit = WorkspaceReportToolkit(service)
    job_id = str(uuid.uuid4())
    context = RunContext(
        run_id="member-run",
        session_id="thread",
        session_state={
            REPORT_DELIVERY_STATE_KEY: {
                "deliveryId": "delivery-1",
                "jobId": job_id,
            },
            REPORT_JOBS_STATE_KEY: {
                job_id: {
                    "jobId": job_id,
                    "_threadBinding": toolkit._thread_binding("thread"),
                    "sources": [service.entries["报表/数据集/收入.csv"]],
                    "render": {
                        "markdown": service.entries["报表/年度收入.md"],
                        "pdf": service.entries["报表/年度收入.pdf"],
                        "images": [],
                    },
                    "validation": {
                        "ok": True,
                        "pdfPath": "报表/年度收入.pdf",
                    },
                }
            },
        },
    )

    evidence = await toolkit.validated_delivery("delivery-1", run_context=context)

    assert evidence == {
        "jobId": job_id,
        "status": "validated",
        "markdownPath": "报表/年度收入.md",
        "pdfPath": "报表/年度收入.pdf",
        "markdownSha256": "b" * 64,
        "pdfSha256": "c" * 64,
    }
    assert await toolkit.validated_delivery("other-delivery", run_context=context) is None

    service.entries["报表/年度收入.pdf"] = {
        "path": "报表/年度收入.pdf",
        "size": 35,
        "sha256": "d" * 64,
    }
    assert await toolkit.validated_delivery("delivery-1", run_context=context) is None


@pytest.mark.anyio
async def test_报表工具把本轮实际触达的job绑定到交付门禁():
    service = _ReportStateService()
    context = RunContext(
        run_id="member-run",
        session_id="thread",
        session_state={
            REPORT_DELIVERY_STATE_KEY: {
                "deliveryId": "delivery-1",
                "jobId": None,
            }
        },
    )
    toolkit = WorkspaceReportToolkit(service, _ReportDatasetResolver())

    prepared = await toolkit.report_prepare_dataset(["dataset-income"], run_context=context)

    assert context.session_state[REPORT_DELIVERY_STATE_KEY] == {
        "deliveryId": "delivery-1",
        "jobId": prepared["jobId"],
    }


@pytest.mark.anyio
async def test_报表post_hook同步修正持久化内容并补充真实路径():
    service = _ReportStateService()
    service.entries.update(
        {
            "报表/结果.md": {"path": "报表/结果.md", "size": 20, "sha256": "b" * 64},
            "报表/结果.pdf": {"path": "报表/结果.pdf", "size": 30, "sha256": "c" * 64},
        }
    )
    toolkit = WorkspaceReportToolkit(service)
    job_id = str(uuid.uuid4())
    context = RunContext(
        run_id="member-run",
        session_id="thread",
        session_state={
            REPORT_DELIVERY_STATE_KEY: {"deliveryId": "delivery-1", "jobId": job_id},
            REPORT_JOBS_STATE_KEY: {
                job_id: {
                    "jobId": job_id,
                    "_threadBinding": toolkit._thread_binding("thread"),
                    "sources": [service.entries["报表/数据集/收入.csv"]],
                    "render": {
                        "markdown": service.entries["报表/结果.md"],
                        "pdf": service.entries["报表/结果.pdf"],
                        "images": [],
                    },
                    "validation": {"ok": True, "pdfPath": "报表/结果.pdf"},
                }
            },
        },
    )
    output = RunOutput(
        content="报表完成。",
        messages=[Message(role="assistant", content="报表完成。")],
    )

    await enforce_report_delivery_output(output, context, service)

    assert "报表/结果.md" in output.content
    assert "报表/结果.pdf" in output.content
    assert output.messages[-1].content == output.content

    del service.entries["报表/结果.pdf"]
    failed = RunOutput(
        content="PDF 已生成。",
        messages=[Message(role="assistant", content="PDF 已生成。")],
    )
    await enforce_report_delivery_output(failed, context, service)

    assert failed.content == REPORT_DELIVERY_INCOMPLETE_MESSAGE
    assert failed.messages[-1].content == REPORT_DELIVERY_INCOMPLETE_MESSAGE

    ordinary = RunOutput(content="普通回答。")
    await enforce_report_delivery_output(
        ordinary,
        RunContext(run_id="run", session_id="thread", session_state={}),
        service,
    )
    assert ordinary.content == "普通回答。"


@pytest.mark.anyio
async def test_报表发布后状态提交失败会清理pdf和本次临时目录(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.sandbox_for("thread")
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    toolkit = WorkspaceReportToolkit(async_service)
    job_id = str(uuid.uuid4())
    context = RunContext(
        run_id="run",
        session_id="thread",
        session_state={
            REPORT_JOBS_STATE_KEY: {
                job_id: {
                    "jobId": job_id,
                    "_threadBinding": toolkit._thread_binding("thread"),
                    "sources": [{"path": "data.csv", "size": 12, "sha256": "a" * 64}],
                }
            }
        },
    )
    deleted = []

    async def status(job, _run_context):
        return {"jobId": job["jobId"], "status": "prepared", "sources": []}

    async def render(_action, payload, _run_context):
        return {
            "status": "rendered",
            "pdfPath": "report.pdf",
            "render": {
                "markdown": {"path": "report.md", "size": 1, "sha256": "b" * 64},
                "pdf": {"path": "report.pdf", "size": 20, "sha256": "c" * 64},
                "images": [],
            },
        }

    async def hash_file(_thread, path):
        return {"path": path, "size": 20, "sha256": "c" * 64}

    async def cleanup(path, _run_context, *, recursive):
        deleted.append((path, recursive))

    async def unpublish(path, _staging, _run_context):
        deleted.append((path, False))

    monkeypatch.setattr(toolkit, "_job_status", status)
    monkeypatch.setattr(toolkit, "_run_report_runtime", render)
    monkeypatch.setattr(async_service, "ahash_file", hash_file)
    monkeypatch.setattr(toolkit, "_delete_report_path", cleanup)
    monkeypatch.setattr(toolkit, "_delete_published_report", unpublish)
    monkeypatch.setattr(
        toolkit,
        "_store_job",
        lambda *_args: (_ for _ in ()).throw(WorkspaceError("state failed")),
    )

    with pytest.raises(WorkspaceError, match="state failed"):
        await toolkit.report_render_markdown(
            job_id,
            "report.md",
            "report.pdf",
            run_context=context,
        )

    assert (f"{WORKSPACE_ROOT}/report.pdf", False) in deleted
    assert len([item for item in deleted if item[0].endswith("-render")]) == 1


def test_报表动作和工作区单文件边界统一为200mib():
    assert REPORT_RUNTIME_TIMEOUT_SECONDS == 600
    assert MAX_UPLOAD_BYTES == 200 * 1024 * 1024
    assert MAX_DOWNLOAD_BYTES == 200 * 1024 * 1024
    assert MAX_BRANCH_FILE_BYTES == 200 * 1024 * 1024
    assert MAX_IMAGE_BYTES == 10 * 1024 * 1024


def test_基础和报表工具集独立且确认边界符合策略(tmp_path):
    current = service(tmp_path)
    base_toolkit = BaseToolkit(current)
    report_toolkit = WorkspaceReportToolkit(current)
    assert base_toolkit.name == "base"
    assert report_toolkit.name == "workspace_report"
    assert base_toolkit.add_instructions is True
    assert base_toolkit.instructions
    assert report_toolkit.add_instructions is True
    assert report_toolkit.instructions
    assert "report_prepare_dataset" in report_toolkit.instructions
    assert "分析和长进程统一使用 Coding 工具" in report_toolkit.instructions
    assert "report_validate_pdf" in report_toolkit.instructions
    assert isinstance(base_toolkit, WorkspaceToolkit)
    assert isinstance(base_toolkit, DaytonaToolkit)
    assert not isinstance(report_toolkit, WorkspaceToolkit)
    base_tools = {**base_toolkit.functions, **base_toolkit.async_functions}
    report_tools = {**report_toolkit.functions, **report_toolkit.async_functions}
    assert set(base_tools) == {
        "sandbox_exec",
        "sandbox_process_poll",
        "sandbox_process_write",
        "sandbox_process_interrupt",
        "sandbox_process_stop",
        "workspace_list_files",
        "workspace_read_file",
        "workspace_read_lines",
        "workspace_stat",
        "workspace_tree",
        "workspace_search_files",
        "workspace_search_text",
        "workspace_hash_file",
        "workspace_git_status",
        "workspace_git_diff",
        "workspace_git_log",
        "workspace_git_show",
        "workspace_write_file",
        "workspace_move_file",
        "workspace_replace_file",
        "workspace_apply_patch",
        "workspace_apply_patch_set",
        "workspace_apply_hunks",
        "workspace_apply_changes",
        "workspace_create_directory",
        "workspace_copy_file",
        "workspace_delete_file",
        "workspace_view_image",
        "workspace_inspect_pdf",
    }
    assert set(report_tools) == {
        "report_prepare_dataset",
        "report_job_status",
        "report_render_markdown",
        "report_validate_pdf",
    }
    assert set(base_tools).isdisjoint(report_tools)
    for name in (
        "sandbox_exec",
        "sandbox_process_write",
        "sandbox_process_interrupt",
        "sandbox_process_stop",
        "workspace_write_file",
        "workspace_move_file",
        "workspace_replace_file",
        "workspace_apply_patch",
        "workspace_apply_patch_set",
        "workspace_apply_hunks",
        "workspace_apply_changes",
        "workspace_create_directory",
        "workspace_copy_file",
        "workspace_delete_file",
    ):
        assert base_tools[name].requires_confirmation is True

    base_tools["sandbox_exec"].process_entrypoint()
    base_tools["sandbox_process_poll"].process_entrypoint()
    base_tools["sandbox_process_write"].process_entrypoint()
    base_tools["sandbox_process_stop"].process_entrypoint()
    report_tools["report_prepare_dataset"].process_entrypoint()
    report_tools["report_job_status"].process_entrypoint()
    report_tools["report_render_markdown"].process_entrypoint()
    report_tools["report_validate_pdf"].process_entrypoint()
    assert "/home/daytona/workspace" in base_tools["sandbox_exec"].description
    assert base_tools["sandbox_process_poll"].requires_confirmation is False
    assert "background" in base_tools["sandbox_exec"].parameters["properties"]
    assert "yield_time_ms" in base_tools["sandbox_exec"].parameters["properties"]
    assert base_tools["sandbox_process_poll"].parameters["required"] == [
        "session_id",
        "command_id",
    ]
    assert report_tools["report_render_markdown"].requires_confirmation is False
    assert report_tools["report_validate_pdf"].requires_confirmation is False
    assert report_tools["report_prepare_dataset"].parameters["required"] == ["dataset_ids"]
    assert "paths" not in report_tools["report_prepare_dataset"].parameters["properties"]
    assert "page_layout" not in report_tools["report_render_markdown"].parameters["properties"]
    base_tools["workspace_apply_patch"].process_entrypoint()
    assert set(base_tools["workspace_apply_patch"].parameters["required"]) == {
        "path",
        "old_text",
        "new_text",
        "expected_sha256",
    }
    assert "无需用户确认" in report_tools["report_render_markdown"].description

    for function in base_tools.values():
        function.process_entrypoint()
        assert function.parameters["additionalProperties"] is False
        for parameter, schema in function.parameters.get("properties", {}).items():
            assert schema.get("description"), f"{function.name}.{parameter} 缺少参数说明"

    exec_schema = base_tools["sandbox_exec"].parameters["properties"]
    assert exec_schema["command"]["minLength"] == 1
    assert exec_schema["timeout"]["minimum"] == 1
    assert exec_schema["timeout"]["maximum"] == 86400
    assert exec_schema["timeout"]["default"] == 30
    assert exec_schema["background"]["default"] is False
    assert exec_schema["pty"]["default"] is False
    assert exec_schema["pty_rows"]["minimum"] == 1
    assert exec_schema["pty_rows"]["maximum"] == 200
    assert exec_schema["pty_cols"]["minimum"] == 1
    assert exec_schema["pty_cols"]["maximum"] == 400
    assert exec_schema["suppress_input_echo"]["default"] is True

    process_schema = base_tools["sandbox_process_write"].parameters["properties"]
    assert process_schema["session_id"]["pattern"] == r"^agui-exec-[0-9a-f]{32}$"
    assert process_schema["command_id"]["minLength"] == 1
    assert process_schema["command_id"]["maxLength"] == 128
    assert process_schema["command_id"]["pattern"] == r"^[A-Za-z0-9._-]+$"
    assert process_schema["data"]["minLength"] == 1
    assert process_schema["data"]["maxLength"] == MAX_PROCESS_INPUT_BYTES
    poll_schema = base_tools["sandbox_process_poll"].parameters["properties"]
    assert poll_schema["offset"]["minimum"] == 0
    assert poll_schema["max_bytes"]["minimum"] == 1
    assert poll_schema["max_bytes"]["maximum"] == MAX_TOOL_OUTPUT_BYTES

    line_schema = base_tools["workspace_read_lines"].parameters["properties"]
    assert line_schema["start_line"]["minimum"] == 1
    assert line_schema["line_count"]["minimum"] == 1
    assert line_schema["line_count"]["maximum"] == 500

    for name in ("workspace_search_files", "workspace_search_text"):
        search_schema = base_tools[name].parameters["properties"]
        assert search_schema["limit"]["minimum"] == 1
        assert search_schema["limit"]["maximum"] == 100
        assert search_schema["offset"]["minimum"] == 0
        assert search_schema["offset"]["maximum"] == 1999
        assert search_schema["include_globs"]["maxItems"] == 20
        assert search_schema["exclude_globs"]["maxItems"] == 20

    text_schema = base_tools["workspace_search_text"].parameters["properties"]
    assert text_schema["case_mode"]["enum"] == ["smart", "sensitive", "insensitive"]
    assert text_schema["mode"]["enum"] == ["matches", "files_with_matches", "count"]
    assert text_schema["before_context"]["maximum"] == 5
    assert text_schema["after_context"]["maximum"] == 5

    patch_schema = base_tools["workspace_apply_patch"].parameters["properties"]
    assert patch_schema["old_text"]["minLength"] == 1
    assert patch_schema["expected_sha256"]["minLength"] == 64
    assert patch_schema["expected_sha256"]["maxLength"] == 64
    assert patch_schema["expected_sha256"]["pattern"] == r"^[0-9a-fA-F]{64}$"
    patch_set_schema = base_tools["workspace_apply_patch_set"].parameters["properties"]["patches"]
    assert patch_set_schema["minItems"] == 1
    assert patch_set_schema["maxItems"] == 20
    assert patch_set_schema["items"]["additionalProperties"] is False
    hunk_schema = base_tools["workspace_apply_hunks"].parameters["properties"]["patches"]
    assert hunk_schema["minItems"] == 1
    assert hunk_schema["maxItems"] == 20
    assert hunk_schema["items"]["properties"]["hunks"]["maxItems"] == 50
    changes_schema = base_tools["workspace_apply_changes"].parameters["properties"]["changes"]
    assert changes_schema["minItems"] == 1
    assert changes_schema["maxItems"] == 20
    assert changes_schema["items"]["properties"]["operation"]["enum"] == [
        "create",
        "update",
        "delete",
        "move",
    ]
