import asyncio
import hashlib
import json
import shlex
import uuid
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from agno.models.message import Message
from agno.run import RunContext
from agno.run.agent import RunOutput
from pypdf import PdfWriter

import agentos_dev.workspace as workspace_module
from agentos_dev.agents.report import enforce_report_delivery_output
from agentos_dev.tests.workspace_fakes import (
    SECRET,
    AsyncFakeClient,
    AsyncFakeFs,
    AsyncFakeProcess,
    AsyncMemoryRegistry,
    FakeClient,
    FakeSandbox,
    Info,
    service,
)
from agentos_dev.workspace import (
    MAX_BRANCH_FILE_BYTES,
    MAX_DOWNLOAD_BYTES,
    MAX_IMAGE_BYTES,
    MAX_MANAGED_PROCESSES,
    MAX_PATH_BYTES,
    MAX_PATH_COMPONENT_BYTES,
    MAX_PATH_DEPTH,
    MAX_PROCESS_INPUT_BYTES,
    MAX_READ_BYTES,
    MAX_TOOL_OUTPUT_BYTES,
    MAX_UPLOAD_BYTES,
    REPORT_DELIVERY_INCOMPLETE_MESSAGE,
    REPORT_DELIVERY_STATE_KEY,
    REPORT_JOBS_STATE_KEY,
    REPORT_RUNTIME_TIMEOUT_SECONDS,
    WORKSPACE_ROOT,
    WORKSPACE_SNAPSHOT,
    BaseToolkit,
    DaytonaToolkit,
    SandboxRegistry,
    WorkspaceError,
    WorkspacePathConflict,
    WorkspaceReportToolkit,
    WorkspaceService,
    WorkspaceToolkit,
)


def test_报表动作和工作区单文件边界统一为200mib():
    assert REPORT_RUNTIME_TIMEOUT_SECONDS == 600
    assert MAX_UPLOAD_BYTES == 200 * 1024 * 1024
    assert MAX_DOWNLOAD_BYTES == 200 * 1024 * 1024
    assert MAX_BRANCH_FILE_BYTES == 200 * 1024 * 1024
    assert MAX_IMAGE_BYTES == 10 * 1024 * 1024


def test_每个对话使用独立持久沙箱且注册表可跨服务复用(tmp_path):
    assert WORKSPACE_SNAPSHOT == "sandbox-tools-20260723"
    client = FakeClient()
    first = service(tmp_path, client)
    one = first.sandbox_for("thread-one")
    two = first.sandbox_for("thread-two")

    assert one.id != two.id
    assert len(client.created) == 2
    params = client.created[0]
    assert params.public is False
    assert params.ephemeral is False
    assert params.network_block_all is True
    assert params.snapshot == WORKSPACE_SNAPSHOT
    assert params.auto_stop_interval == 60
    assert list(params.labels) == ["agui-thread"]
    assert "thread-one" not in str(params.labels)

    restarted = WorkspaceService(SECRET, client=client, registry=first.registry)
    assert restarted.sandbox_for("thread-one").id == one.id
    assert len(client.created) == 2


def test_路径大小符号链接和销毁边界均生效(tmp_path, monkeypatch):
    current = service(tmp_path)
    with pytest.raises(WorkspaceError, match="目录穿越"):
        current.upload("thread", "../escape", b"bad")
    with pytest.raises(WorkspaceError, match="绝对路径"):
        current.list_files("thread", "/etc")
    with monkeypatch.context() as patch:
        patch.setattr(workspace_module, "MAX_UPLOAD_BYTES", 4)
        with pytest.raises(WorkspaceError, match="文件内容超过"):
            current.upload("thread", "large.bin", b"12345")

    current.upload("thread", "docs/readme.txt", b"hello")
    assert current.read_text("thread", "docs/readme.txt") == "hello"
    sandbox = current.sandbox_for("thread")
    sandbox.fs.entries["/home/daytona/workspace/link"] = (
        Info("link", mode="lrwxrwxrwx"),
        b"outside",
    )
    with pytest.raises(WorkspaceError, match="符号链接"):
        current.file_bytes("thread", "link")
    with pytest.raises(WorkspaceError, match="符号链接"):
        current.upload("thread", "link", b"overwrite")

    current.upload("thread", "move-source.txt", b"move")
    with pytest.raises(WorkspaceError, match="符号链接"):
        current.move_file("thread", "move-source.txt", "link")

    assert current.destroy("thread") is True
    assert current.destroy("thread") is False


def test_工作区下载允许200mib并拒绝更大文件(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "archive.bin", b"file")
    info = current.sandbox_for("thread").fs.entries[f"{WORKSPACE_ROOT}/archive.bin"][0]
    info.size = MAX_DOWNLOAD_BYTES

    assert current.file_bytes("thread", "archive.bin")[0] == b"file"

    info.size = MAX_DOWNLOAD_BYTES + 1
    with pytest.raises(WorkspaceError, match="超过 200 MiB"):
        current.file_bytes("thread", "archive.bin")


def test_销毁会删除重复标签沙箱并清理注册表(tmp_path):
    client = FakeClient()
    current = service(tmp_path, client)
    value = current._hash("thread")
    first = FakeSandbox("sandbox-1", {"agui-thread": value})
    second = FakeSandbox("sandbox-2", {"agui-thread": value})
    client.sandboxes = {first.id: first, second.id: second}
    current.registry.set(value, first.id)

    assert current.destroy("thread") is True
    assert set(client.deleted) == {first.id, second.id}
    assert current.registry.get(value) is None
    assert current.destroy("thread") is False


def test_注册表直到首次使用才初始化(monkeypatch):
    registry = SandboxRegistry("postgresql://unavailable/example")
    monkeypatch.setattr(
        registry,
        "_connect",
        lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    with pytest.raises(RuntimeError, match="offline"):
        registry.ensure_initialized()


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


@pytest.mark.anyio
async def test_基础工具支持搜索分段读取哈希精确补丁和媒体检查(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "src/app.py", b"alpha\nneedle here\nomega\n")
    current.create_file("thread", "docs/readme.md", b"needle in docs\n")
    sandbox = current.sandbox_for("thread")

    def execute_workspace_command(command, cwd=None, timeout=None):
        sandbox.process.calls.append({"command": command, "cwd": cwd, "timeout": timeout})
        if "rg --no-config" in command:
            output = (
                "./docs/readme.md\x00./src/app.py\x00" if "*.md" in command else "./src/app.py\x00"
            )
        elif "file --brief --mime-encoding" in command:
            output = "us-ascii\x0024\x003\x00"
        elif "sed -n" in command:
            output = "needle here\n"
        elif "sha256sum" in command:
            digest = hashlib.sha256(b"alpha\nneedle here\nomega\n").hexdigest()
            output = f"{digest}\x0024\x00"
        else:
            raise AssertionError(f"unexpected command: {command}")
        return type("Result", (), {"result": output, "exit_code": 0})()

    sandbox.process.exec = execute_workspace_command
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    toolkit = BaseToolkit(async_service)
    tools = {**toolkit.functions, **toolkit.async_functions}
    context = RunContext(run_id="run", session_id="thread")

    files = await toolkit.workspace_search_files(pattern="*.py", run_context=context)
    assert files == {
        "matches": [{"path": "src/app.py", "name": "app.py", "size": 24}],
        "truncated": False,
    }
    multiple = await toolkit.workspace_search_files(
        include_globs=["*.py", "*.md"],
        exclude_globs=["vendor/**"],
        run_context=context,
    )
    assert [item["path"] for item in multiple["matches"]] == [
        "docs/readme.md",
        "src/app.py",
    ]
    command = sandbox.process.calls[-1]["command"]
    for argument in ("--files", "*.py", "*.md", "!vendor/**"):
        assert argument in command
    assert sandbox.fs.download_calls == []
    lines = await toolkit.workspace_read_lines(
        path="src/app.py", start_line=2, line_count=1, run_context=context
    )
    assert lines == {
        "path": "src/app.py",
        "startLine": 2,
        "endLine": 2,
        "totalLines": 3,
        "content": "needle here\n",
        "truncated": True,
    }
    digest = await toolkit.workspace_hash_file(path="src/app.py", run_context=context)
    assert digest["path"] == "src/app.py"
    assert digest["sha256"]
    patched = tools["workspace_apply_patch"].entrypoint(
        path="src/app.py",
        old_text="needle here",
        new_text="updated value",
        expected_sha256=digest["sha256"],
        run_context=context,
    )
    assert patched["replacements"] == 1
    assert "-needle here" in patched["diff"]
    assert "+updated value" in patched["diff"]
    assert patched["diffTruncated"] is False
    assert current.read_text("thread", "src/app.py") == "alpha\nupdated value\nomega\n"

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    current.upload("thread", "chart.png", png)
    image = tools["workspace_view_image"].entrypoint(path="chart.png", run_context=context)
    assert image.images and image.images[0].content == png
    assert image.images[0].mime_type == "image/png"

    pdf_buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(pdf_buffer)
    current.upload("thread", "report.pdf", pdf_buffer.getvalue())
    pdf = tools["workspace_inspect_pdf"].entrypoint(path="report.pdf", run_context=context)
    assert pdf["pageCount"] == 1
    assert pdf["sha256"]


@pytest.mark.anyio
async def test_大文件分段读取哈希统计和目录树均在沙箱内执行(tmp_path):
    current = service(tmp_path)
    large_content = (("line value\n" * 100_000) + "last line").encode()
    current.create_file("thread", "data/large.txt", large_content)
    current.create_file("thread", "data/small.txt", b"small\n")
    sandbox = current.sandbox_for("thread")
    process = sandbox.process
    total_lines = 100_001
    digest = hashlib.sha256(large_content).hexdigest()

    def execute_command(command, cwd=None, timeout=None):
        process.calls.append({"command": command, "cwd": cwd, "timeout": timeout})
        if "file --brief --mime-encoding" in command:
            output = f"us-ascii\x00{len(large_content)}\x00{total_lines}\x00"
        elif "sed -n" in command:
            output = "line value\nline value\n"
        elif "sha256sum" in command:
            output = f"{digest}\x00{len(large_content)}\x00"
        elif "stat --printf" in command:
            output = f"regular file\x00{len(large_content)}\x001753200000\x00600\x00"
        elif "find " in command:
            output = f"d\tnested\t4096\x00f\tlarge.txt\t{len(large_content)}\x00"
        else:
            raise AssertionError(f"unexpected command: {command}")
        return type("Result", (), {"result": output, "exit_code": 0})()

    process.exec = execute_command
    toolkit = BaseToolkit(
        WorkspaceService(
            current.secret,
            client=current.client,
            registry=current.registry,
            async_client=AsyncFakeClient(current.client),
            async_registry=AsyncMemoryRegistry(current.registry.values),
        )
    )
    context = RunContext(run_id="run", session_id="thread")

    lines = await toolkit.workspace_read_lines(
        "data/large.txt", start_line=90_000, line_count=2, run_context=context
    )
    hashed = await toolkit.workspace_hash_file("data/large.txt", run_context=context)
    stat = await toolkit.workspace_stat("data/large.txt", run_context=context)
    tree = await toolkit.workspace_tree("data", max_depth=2, run_context=context)

    assert len(large_content) > MAX_READ_BYTES
    assert lines == {
        "path": "data/large.txt",
        "startLine": 90_000,
        "endLine": 90_001,
        "totalLines": total_lines,
        "content": "line value\nline value\n",
        "truncated": True,
    }
    assert hashed == {
        "path": "data/large.txt",
        "size": len(large_content),
        "sha256": digest,
    }
    assert stat == {
        "path": "data/large.txt",
        "type": "file",
        "size": len(large_content),
        "modifiedUnix": 1_753_200_000,
        "mode": "600",
    }
    assert tree == {
        "root": "data",
        "entries": [
            {"path": "data/nested", "type": "directory", "size": 4096},
            {"path": "data/large.txt", "type": "file", "size": len(large_content)},
        ],
        "truncated": False,
    }
    assert sandbox.fs.download_calls == []
    assert any("wc -l" in call["command"] for call in process.calls)
    assert any("sed -n" in call["command"] for call in process.calls)
    assert any("sha256sum" in call["command"] for call in process.calls)
    assert any("stat --printf" in call["command"] for call in process.calls)
    assert any("find " in call["command"] for call in process.calls)


@pytest.mark.anyio
async def test_只读_git_工具使用固定参数并拒绝非法修订(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "repo/src/app.py", b"print('ok')\n")
    sandbox = current.sandbox_for("thread")
    process = sandbox.process

    def execute_git(command, cwd=None, timeout=None):
        process.calls.append({"command": command, "cwd": cwd, "timeout": timeout})
        return type("Result", (), {"result": "git output", "exit_code": 0})()

    process.exec = execute_git
    toolkit = BaseToolkit(
        WorkspaceService(
            current.secret,
            client=current.client,
            registry=current.registry,
            async_client=AsyncFakeClient(current.client),
            async_registry=AsyncMemoryRegistry(current.registry.values),
        )
    )
    context = RunContext(run_id="run", session_id="thread")

    assert (await toolkit.workspace_git_status("repo", run_context=context))["output"]
    assert (
        await toolkit.workspace_git_diff(
            "repo", staged=True, revision="HEAD~2", file_path="src/app.py", run_context=context
        )
    )["output"]
    assert (
        await toolkit.workspace_git_log(
            "repo", revision="main", max_count=10, file_path="src/app.py", run_context=context
        )
    )["output"]
    assert (
        await toolkit.workspace_git_show(
            "repo", revision="HEAD^", file_path="src/app.py", run_context=context
        )
    )["output"]

    commands = [call["command"] for call in process.calls]
    assert all("git -C" in command and "--no-pager" in command for command in commands)
    assert all("core.fsmonitor=false" in command for command in commands)
    assert all("core.hooksPath=/dev/null" in command for command in commands)
    assert "--short" in commands[0] and "--branch" in commands[0]
    assert "--no-ext-diff" in commands[1] and "--no-textconv" in commands[1]
    assert "--cached" in commands[1] and "HEAD~2" in commands[1]
    assert "--max-count=10" in commands[2] and "main" in commands[2]
    assert "--format=fuller" in commands[3] and "HEAD^" in commands[3]
    assert all(call["cwd"] == WORKSPACE_ROOT for call in process.calls)
    assert sandbox.fs.download_calls == []

    with pytest.raises(WorkspaceError, match="Git 修订"):
        await toolkit.workspace_git_show("repo", revision="--help", run_context=context)
    assert len(process.calls) == 4


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("stderr", "message"),
    [
        ("fatal: not a git repository", "不是 Git 仓库"),
        ("fatal: bad revision 'missing'", "修订不存在"),
        ("error: pathspec 'missing.py' did not match", "文件路径不存在"),
        ("fatal: unexpected internal detail /secret/path", "Git 只读命令执行失败"),
    ],
)
async def test_git_失败只返回分类诊断而不暴露原始_stderr(tmp_path, stderr, message):
    current = service(tmp_path)
    current.create_file("thread", "repo/file.txt", b"content\n")
    process = current.sandbox_for("thread").process

    def fail_git(command, cwd=None, timeout=None):
        process.calls.append({"command": command, "cwd": cwd, "timeout": timeout})
        return type("Result", (), {"result": stderr, "exit_code": 128})()

    process.exec = fail_git
    toolkit = BaseToolkit(
        WorkspaceService(
            current.secret,
            client=current.client,
            registry=current.registry,
            async_client=AsyncFakeClient(current.client),
            async_registry=AsyncMemoryRegistry(current.registry.values),
        )
    )

    with pytest.raises(WorkspaceError, match=message) as error:
        await toolkit.workspace_git_show(
            "repo", revision="missing", run_context=RunContext(run_id="run", session_id="thread")
        )
    assert "/secret/path" not in str(error.value)


@pytest.mark.anyio
async def test_文本搜索在沙箱内使用_rg_并支持_codex_常用模式(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "src/app.py", b"before\nNeedle here\nafter\n")
    sandbox = current.sandbox_for("thread")
    process = sandbox.process

    match_events = [
        {
            "type": "context",
            "data": {
                "path": {"text": "./src/app.py"},
                "lines": {"text": "before\n"},
                "line_number": 1,
                "submatches": [],
            },
        },
        {
            "type": "match",
            "data": {
                "path": {"text": "./src/app.py"},
                "lines": {"text": "Needle here\n"},
                "line_number": 2,
                "submatches": [{"start": 0, "end": 6, "match": {"text": "Needle"}}],
            },
        },
        {
            "type": "context",
            "data": {
                "path": {"text": "./src/app.py"},
                "lines": {"text": "after\n"},
                "line_number": 3,
                "submatches": [],
            },
        },
    ]

    def execute_rg(command, cwd=None, timeout=None):
        process.calls.append({"command": command, "cwd": cwd, "timeout": timeout})
        if "--files-with-matches" in command:
            output = "./docs/readme.md\x00./src/app.py\x00"
        elif "--count" in command:
            output = "./docs/readme.md\x001\n./src/app.py\x002\n"
        else:
            output = "\n".join(json.dumps(event) for event in match_events) + "\n"
        return type("Result", (), {"result": output, "exit_code": 0})()

    process.exec = execute_rg
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    toolkit = BaseToolkit(async_service)
    context = RunContext(run_id="run", session_id="thread")

    matches = await toolkit.workspace_search_text(
        query=r"Need(le)?",
        regex=True,
        case_mode="smart",
        word_match=True,
        include_globs=["*.py", "*.md"],
        exclude_globs=["vendor/**"],
        before_context=1,
        after_context=1,
        run_context=context,
    )
    files = await toolkit.workspace_search_text(
        query="needle", mode="files_with_matches", run_context=context
    )
    counts = await toolkit.workspace_search_text(query="needle", mode="count", run_context=context)

    assert matches == {
        "mode": "matches",
        "matches": [
            {
                "path": "src/app.py",
                "line": 2,
                "column": 1,
                "text": "Needle here",
                "before": [{"line": 1, "text": "before"}],
                "after": [{"line": 3, "text": "after"}],
            }
        ],
        "truncated": False,
    }
    assert files == {
        "mode": "files_with_matches",
        "files": [{"path": "docs/readme.md"}, {"path": "src/app.py"}],
        "truncated": False,
    }
    assert counts == {
        "mode": "count",
        "counts": [
            {"path": "docs/readme.md", "count": 1},
            {"path": "src/app.py", "count": 2},
        ],
        "truncated": False,
    }
    command = process.calls[0]["command"]
    for argument in (
        "--json",
        "--smart-case",
        "--word-regexp",
        "*.py",
        "*.md",
        "!vendor/**",
        "!报表/原始数据/*/分片/*.jsonl",
        "!reports/data/*.jsonl",
    ):
        assert argument in command
    assert process.calls[0]["cwd"] == WORKSPACE_ROOT
    assert sandbox.fs.download_calls == []


@pytest.mark.anyio
async def test_rg_搜索拒绝非法模式_glob_和受控原始数据(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "visible.txt", b"needle\n")
    current.upload(
        "thread",
        "报表/原始数据/11111111-1111-4111-8111-111111111111/分片/数据-0001.jsonl",
        b"needle\n",
    )
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    toolkit = BaseToolkit(async_service)
    context = RunContext(run_id="run", session_id="thread")

    with pytest.raises(WorkspaceError, match="大小写模式"):
        await toolkit.workspace_search_text(query="x", case_mode="invalid", run_context=context)
    with pytest.raises(WorkspaceError, match="输出模式"):
        await toolkit.workspace_search_text(query="x", mode="invalid", run_context=context)
    with pytest.raises(WorkspaceError, match="glob"):
        await toolkit.workspace_search_text(query="x", include_globs=["!*.py"], run_context=context)
    with pytest.raises(WorkspaceError, match="原始报表分片"):
        await toolkit.workspace_search_text(
            query="needle",
            path="报表/原始数据/11111111-1111-4111-8111-111111111111/分片/数据-0001.jsonl",
            run_context=context,
        )


def test_补丁拒绝陈旧和非唯一内容(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "notes.txt", b"same\nsame\n")
    tools = BaseToolkit(current).functions
    context = RunContext(run_id="run", session_id="thread")
    digest = current.hash_file("thread", "notes.txt")

    current.replace_file("thread", "notes.txt", b"changed\n")
    with pytest.raises(WorkspacePathConflict, match="文件内容已变化"):
        tools["workspace_apply_patch"].entrypoint(
            path="notes.txt",
            old_text="same",
            new_text="updated",
            expected_sha256=digest["sha256"],
            run_context=context,
        )

    current.replace_file("thread", "notes.txt", b"same\nsame\n")
    digest = current.hash_file("thread", "notes.txt")
    with pytest.raises(WorkspaceError, match="出现 2 次"):
        tools["workspace_apply_patch"].entrypoint(
            path="notes.txt",
            old_text="same",
            new_text="updated",
            expected_sha256=digest["sha256"],
            run_context=context,
        )

    current.upload("thread", "fake.png", b"not-a-png")
    with pytest.raises(WorkspaceError, match="文件签名不一致"):
        tools["workspace_view_image"].entrypoint(path="fake.png", run_context=context)


def test_批量补丁支持多文件多段编辑(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "a.txt", b"one\ntwo\nthree\n")
    current.create_file("thread", "b.txt", b"alpha\nbeta\n")
    tools = BaseToolkit(current).functions
    context = RunContext(run_id="run", session_id="thread")
    a_hash = current.hash_file("thread", "a.txt")["sha256"]
    b_hash = current.hash_file("thread", "b.txt")["sha256"]

    result = tools["workspace_apply_patch_set"].entrypoint(
        patches=[
            {
                "path": "a.txt",
                "expected_sha256": a_hash,
                "edits": [
                    {"old_text": "one", "new_text": "ONE"},
                    {"old_text": "three", "new_text": "THREE"},
                ],
            },
            {
                "path": "b.txt",
                "expected_sha256": b_hash,
                "edits": [{"old_text": "beta", "new_text": "BETA"}],
            },
        ],
        run_context=context,
    )

    assert [item["path"] for item in result["files"]] == ["a.txt", "b.txt"]
    assert result["replacements"] == 3
    assert current.read_text("thread", "a.txt") == "ONE\ntwo\nTHREE\n"
    assert current.read_text("thread", "b.txt") == "alpha\nBETA\n"


def test_批量补丁预检任一冲突时不写入任何文件(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "a.txt", b"before-a\n")
    current.create_file("thread", "b.txt", b"before-b\n")
    a_hash = current.hash_file("thread", "a.txt")["sha256"]
    tools = BaseToolkit(current).functions

    with pytest.raises(WorkspacePathConflict, match="文件内容已变化"):
        tools["workspace_apply_patch_set"].entrypoint(
            patches=[
                {
                    "path": "a.txt",
                    "expected_sha256": a_hash,
                    "edits": [{"old_text": "before-a", "new_text": "after-a"}],
                },
                {
                    "path": "b.txt",
                    "expected_sha256": "0" * 64,
                    "edits": [{"old_text": "before-b", "new_text": "after-b"}],
                },
            ],
            run_context=RunContext(run_id="run", session_id="thread"),
        )

    assert current.read_text("thread", "a.txt") == "before-a\n"
    assert current.read_text("thread", "b.txt") == "before-b\n"


def test_定位_hunk_支持多文件并拒绝错位或陈旧内容(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "a.txt", b"one\ntwo\nthree\nfour\n")
    current.create_file("thread", "b.txt", b"alpha\nbeta\ngamma\n")
    tool = BaseToolkit(current).functions["workspace_apply_hunks"]
    context = RunContext(run_id="run", session_id="thread")

    result = tool.entrypoint(
        patches=[
            {
                "path": "a.txt",
                "expected_sha256": current.hash_file("thread", "a.txt")["sha256"],
                "hunks": [{"old_start": 2, "old_text": "two\nthree\n", "new_text": "TWO\nTHREE\n"}],
            },
            {
                "path": "b.txt",
                "expected_sha256": current.hash_file("thread", "b.txt")["sha256"],
                "hunks": [{"old_start": 2, "old_text": "beta\n", "new_text": "BETA\n"}],
            },
        ],
        run_context=context,
    )

    assert result["hunks"] == 2
    assert current.read_text("thread", "a.txt") == "one\nTWO\nTHREE\nfour\n"
    assert current.read_text("thread", "b.txt") == "alpha\nBETA\ngamma\n"

    current.replace_file("thread", "a.txt", b"one\ntwo\nthree\nfour\n")
    with pytest.raises(WorkspaceError, match="第 3 行"):
        tool.entrypoint(
            patches=[
                {
                    "path": "a.txt",
                    "expected_sha256": current.hash_file("thread", "a.txt")["sha256"],
                    "hunks": [{"old_start": 3, "old_text": "two\nthree\n", "new_text": "wrong\n"}],
                }
            ],
            run_context=context,
        )
    assert current.read_text("thread", "a.txt") == "one\ntwo\nthree\nfour\n"


def test_基础读取拒绝把超大文本直接注入模型并要求分段读取(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "large.txt", b"x" * (MAX_TOOL_OUTPUT_BYTES + 1))
    tools = BaseToolkit(current).functions
    context = RunContext(run_id="run", session_id="thread")

    with pytest.raises(WorkspaceError, match="workspace_read_lines"):
        tools["workspace_read_file"].entrypoint(path="large.txt", run_context=context)


def test_补丁落盘校验失败时不会报告成功(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.create_file("thread", "notes.txt", b"before\n")
    digest = current.hash_file("thread", "notes.txt")["sha256"]
    original_replace = current.replace_file

    def corrupt_replace(thread, path, _content):
        return original_replace(thread, path, b"corrupted\n")

    monkeypatch.setattr(current, "replace_file", corrupt_replace)

    with pytest.raises(WorkspaceError, match="落盘校验失败"):
        current.apply_patch("thread", "notes.txt", "before", "after", digest)


@pytest.mark.anyio
async def test_sandbox_exec_使用原生异步进程并绑定工作区(tmp_path):
    current = service(tmp_path)
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    toolkit = BaseToolkit(async_service)

    result = await toolkit.sandbox_exec(
        "pwd", cwd="资料", timeout=30, run_context=RunContext(run_id="run", session_id="thread")
    )

    assert result == {"exitCode": 0, "output": "pwd", "truncated": False}
    process = current.sandbox_for("thread").process
    assert process.calls[-1] == {
        "command": "pwd",
        "cwd": f"{WORKSPACE_ROOT}/资料",
        "timeout": 30,
    }


@pytest.mark.anyio
async def test_sandbox_exec_后台模式使用受管会话并支持轮询输入和终止(tmp_path):
    current = service(tmp_path)
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    toolkit = BaseToolkit(async_service)
    context = RunContext(run_id="run", session_id="thread")

    started = await toolkit.sandbox_exec(
        "python server.py",
        cwd="应用",
        timeout=900,
        background=True,
        pty=True,
        pty_rows=40,
        pty_cols=132,
        suppress_input_echo=True,
        run_context=context,
        yield_time_ms=0,
    )

    assert started["status"] == "running"
    assert started["sessionId"].startswith("agui-exec-")
    assert started["commandId"] == "command-1"
    assert started["originalBytes"] == 7
    assert started["wallTimeSeconds"] >= 0
    process = current.sandbox_for("thread").process
    managed = process.sessions[started["sessionId"]].commands[0]
    assert managed.suppress_input_echo is True
    assert f"cd -- {shlex.quote(f'{WORKSPACE_ROOT}/应用')}" in managed.command
    assert "timeout --signal=TERM --kill-after=5s 900s" in managed.command
    assert "script --quiet --return --command" in managed.command
    assert "stty rows 40 cols 132 -echo" in managed.command
    assert "TERM=xterm-256color" in managed.command

    with pytest.raises(WorkspaceError, match="前台命令.*60"):
        await toolkit.sandbox_exec("sleep 61", timeout=61, run_context=context)

    polled = await toolkit.sandbox_process_poll(
        started["sessionId"], started["commandId"], run_context=context
    )
    assert polled == {
        "sessionId": started["sessionId"],
        "commandId": "command-1",
        "status": "running",
        "exitCode": None,
        "output": "started",
        "offset": 0,
        "nextOffset": 7,
        "totalBytes": 7,
        "originalBytes": 7,
        "hasMore": False,
        "truncated": False,
    }

    with pytest.raises(WorkspaceError, match="超过 8 KiB"):
        await toolkit.sandbox_process_write(
            started["sessionId"],
            started["commandId"],
            "x" * (MAX_PROCESS_INPUT_BYTES + 1),
            run_context=context,
        )
    with pytest.raises(WorkspaceError, match="会话标识无效"):
        await toolkit.sandbox_process_poll("other-session", "command-1", run_context=context)

    written = await toolkit.sandbox_process_write(
        started["sessionId"],
        started["commandId"],
        "continue\n",
        offset=7,
        yield_time_ms=0,
        run_context=context,
    )
    assert written["ok"] is True
    assert written["status"] == "running"
    assert written["offset"] == 7
    assert process.input_calls[-1]["data"] == "continue\n"

    interrupted = await toolkit.sandbox_process_interrupt(
        started["sessionId"], started["commandId"], signal="INT", run_context=context
    )
    assert interrupted == {"ok": True, "status": "signal_sent", "signal": "INT"}
    assert process.input_calls[-1]["data"] == "\x03"

    plain = await toolkit.sandbox_exec("sleep 1", background=True, run_context=context)
    with pytest.raises(WorkspaceError, match="未启用 PTY"):
        await toolkit.sandbox_process_interrupt(
            plain["sessionId"], plain["commandId"], run_context=context
        )
    await toolkit.sandbox_process_stop(plain["sessionId"], plain["commandId"], run_context=context)

    stopped = await toolkit.sandbox_process_stop(
        started["sessionId"], started["commandId"], run_context=context
    )
    assert stopped == {"ok": True, "status": "terminated"}
    assert started["sessionId"] not in process.sessions


@pytest.mark.anyio
async def test_后台进程完成后轮询返回最终输出并清理会话(tmp_path):
    current = service(tmp_path)
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    toolkit = BaseToolkit(async_service)
    context = RunContext(run_id="run", session_id="thread")
    started = await toolkit.sandbox_exec("pytest", background=True, run_context=context)
    process = current.sandbox_for("thread").process
    command = process.sessions[started["sessionId"]].commands[0]
    command.exit_code = 0
    command.output = "first\nsecond\n"

    first = await toolkit.sandbox_process_poll(
        started["sessionId"], started["commandId"], offset=0, max_bytes=6, run_context=context
    )
    assert first["output"] == "first\n"
    assert first["nextOffset"] == 6
    assert first["totalBytes"] == 13
    assert first["hasMore"] is True
    assert started["sessionId"] in process.sessions

    other = await toolkit.sandbox_exec("sleep 1", background=True, run_context=context)
    assert started["sessionId"] in process.sessions
    await toolkit.sandbox_process_stop(other["sessionId"], other["commandId"], run_context=context)

    result = await toolkit.sandbox_process_poll(
        started["sessionId"], started["commandId"], offset=6, max_bytes=64, run_context=context
    )

    assert result["status"] == "completed"
    assert result["exitCode"] == 0
    assert result["output"] == "second\n"
    assert result["nextOffset"] == 13
    assert result["hasMore"] is False
    assert started["sessionId"] not in process.sessions


@pytest.mark.anyio
async def test_并发启动后台进程不会突破数量上限(tmp_path, monkeypatch):
    current = service(tmp_path)
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    toolkit = DaytonaToolkit(async_service)
    original_create_session = AsyncFakeProcess.create_session
    original_execute_session_command = AsyncFakeProcess.execute_session_command

    async def delayed_create_session(self, session_id):
        await asyncio.sleep(0)
        return await original_create_session(self, session_id)

    async def delayed_execute_session_command(self, session_id, request, timeout=None):
        await asyncio.sleep(0)
        return await original_execute_session_command(self, session_id, request, timeout=timeout)

    monkeypatch.setattr(AsyncFakeProcess, "create_session", delayed_create_session)
    monkeypatch.setattr(
        AsyncFakeProcess,
        "execute_session_command",
        delayed_execute_session_command,
    )
    results = await asyncio.gather(
        *[
            toolkit.sandbox_exec(
                f"sleep {index}",
                background=True,
                run_context=RunContext(run_id=f"run-{index}", session_id="thread"),
            )
            for index in range(MAX_MANAGED_PROCESSES + 1)
        ],
        return_exceptions=True,
    )

    succeeded = [result for result in results if isinstance(result, dict)]
    failed = [result for result in results if isinstance(result, WorkspaceError)]
    assert len(succeeded) == MAX_MANAGED_PROCESSES
    assert len(failed) == 1
    assert "后台进程" in str(failed[0])
    assert len(current.sandbox_for("thread").process.sessions) == MAX_MANAGED_PROCESSES


@pytest.mark.anyio
async def test_后台日志字节游标不切断_utf8_字符(tmp_path):
    current = service(tmp_path)
    toolkit = BaseToolkit(
        WorkspaceService(
            current.secret,
            client=current.client,
            registry=current.registry,
            async_client=AsyncFakeClient(current.client),
            async_registry=AsyncMemoryRegistry(current.registry.values),
        )
    )
    context = RunContext(run_id="run", session_id="thread")
    started = await toolkit.sandbox_exec("pytest", background=True, run_context=context)
    process = current.sandbox_for("thread").process
    command = process.sessions[started["sessionId"]].commands[0]
    command.exit_code = 0
    command.output = "甲乙\n"

    with pytest.raises(WorkspaceError, match="UTF-8 字符"):
        await toolkit.sandbox_process_poll(
            started["sessionId"], started["commandId"], max_bytes=1, run_context=context
        )

    first = await toolkit.sandbox_process_poll(
        started["sessionId"], started["commandId"], max_bytes=4, run_context=context
    )
    assert first["output"] == "甲"
    assert first["nextOffset"] == 3
    assert first["hasMore"] is True

    second = await toolkit.sandbox_process_poll(
        started["sessionId"],
        started["commandId"],
        offset=first["nextOffset"],
        max_bytes=4,
        run_context=context,
    )
    assert second["output"] == "乙\n"
    assert second["nextOffset"] == 7
    assert second["hasMore"] is False


def test_新建覆盖移动和系统上传保持各自语义(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "报告.md", "初稿".encode())
    with pytest.raises(WorkspacePathConflict, match="已经存在.*覆盖文件工具"):
        current.create_file("thread", "报告.md", "误覆盖".encode())

    current.replace_file("thread", "报告.md", "终稿".encode())
    assert current.read_text("thread", "报告.md") == "终稿"
    with pytest.raises(WorkspaceError, match="不存在.*新建"):
        current.replace_file("thread", "缺失.md", b"content")

    current.upload("thread", "兼容.txt", b"one")
    current.upload("thread", "兼容.txt", b"two")
    assert current.read_text("thread", "兼容.txt") == "two"

    current.create_file("thread", "来源.txt", b"source")
    current.create_file("thread", "目标.txt", b"target")
    with pytest.raises(WorkspaceError, match="目标路径已经存在"):
        current.move_file("thread", "来源.txt", "目标.txt")
    assert current.read_text("thread", "来源.txt") == "source"

    sandbox = current.sandbox_for("thread")
    sandbox.fs.entries[f"{WORKSPACE_ROOT}/管道"] = (
        Info("管道", mode="prw-------"),
        b"",
    )
    with pytest.raises(WorkspaceError, match="不是普通文件"):
        current.replace_file("thread", "管道", b"content")
    sandbox.fs.create_folder(f"{WORKSPACE_ROOT}/目录", "700")
    with pytest.raises(WorkspaceError, match="自身或其子目录"):
        current.move_file("thread", "目录", "目录/子目录")


def test_完整变更集支持新建更新删除移动(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "update.txt", b"before update\n")
    current.create_file("thread", "delete.txt", b"delete me\n")
    current.create_file("thread", "move.txt", b"move me\n")
    context = RunContext(run_id="run", session_id="thread")
    tool = BaseToolkit(current).functions["workspace_apply_changes"]

    result = tool.entrypoint(
        changes=[
            {"operation": "create", "path": "created.txt", "content": "created\n"},
            {
                "operation": "update",
                "path": "update.txt",
                "content": "after update\n",
                "expected_sha256": current.hash_file("thread", "update.txt")["sha256"],
            },
            {
                "operation": "delete",
                "path": "delete.txt",
                "expected_sha256": current.hash_file("thread", "delete.txt")["sha256"],
            },
            {
                "operation": "move",
                "path": "move.txt",
                "destination": "nested/moved.txt",
                "expected_sha256": current.hash_file("thread", "move.txt")["sha256"],
            },
        ],
        run_context=context,
    )

    assert result["operations"] == 4
    assert [item["operation"] for item in result["files"]] == [
        "create",
        "update",
        "delete",
        "move",
    ]
    assert current.read_text("thread", "created.txt") == "created\n"
    assert current.read_text("thread", "update.txt") == "after update\n"
    with pytest.raises(WorkspaceError, match="不存在"):
        current.read_text("thread", "delete.txt")
    with pytest.raises(WorkspaceError, match="不存在"):
        current.read_text("thread", "move.txt")
    assert current.read_text("thread", "nested/moved.txt") == "move me\n"


def test_结构化创建目录和复制文件保持边界(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "source.txt", b"source\n")
    tools = BaseToolkit(current).functions
    context = RunContext(run_id="run", session_id="thread")

    created = tools["workspace_create_directory"].entrypoint(
        path="nested/empty", run_context=context
    )
    copied = tools["workspace_copy_file"].entrypoint(
        source="source.txt", destination="nested/copied.txt", run_context=context
    )

    assert created == {"path": "nested/empty", "status": "created"}
    assert copied["path"] == "nested/copied.txt"
    assert copied["sha256"] == current.hash_file("thread", "source.txt")["sha256"]
    assert current.read_text("thread", "nested/copied.txt") == "source\n"
    with pytest.raises(WorkspacePathConflict, match="已经存在"):
        tools["workspace_copy_file"].entrypoint(
            source="source.txt", destination="nested/copied.txt", run_context=context
        )


def test_完整变更集预检冲突零写入且执行失败会回滚(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.create_file("thread", "a.txt", b"before a\n")
    current.create_file("thread", "b.txt", b"before b\n")
    tool = BaseToolkit(current).functions["workspace_apply_changes"]
    context = RunContext(run_id="run", session_id="thread")
    a_hash = current.hash_file("thread", "a.txt")["sha256"]

    with pytest.raises(WorkspacePathConflict, match="文件内容已变化"):
        tool.entrypoint(
            changes=[
                {
                    "operation": "update",
                    "path": "a.txt",
                    "content": "after a\n",
                    "expected_sha256": a_hash,
                },
                {
                    "operation": "update",
                    "path": "b.txt",
                    "content": "after b\n",
                    "expected_sha256": "0" * 64,
                },
            ],
            run_context=context,
        )
    assert current.read_text("thread", "a.txt") == "before a\n"
    assert current.read_text("thread", "b.txt") == "before b\n"

    b_hash = current.hash_file("thread", "b.txt")["sha256"]
    original_replace = current.replace_file

    def fail_second_update(thread, path, content):
        if path == "b.txt" and content == b"after b\n":
            raise RuntimeError("write failed")
        return original_replace(thread, path, content)

    monkeypatch.setattr(current, "replace_file", fail_second_update)
    with pytest.raises(RuntimeError, match="write failed"):
        tool.entrypoint(
            changes=[
                {
                    "operation": "update",
                    "path": "a.txt",
                    "content": "after a\n",
                    "expected_sha256": a_hash,
                },
                {
                    "operation": "update",
                    "path": "b.txt",
                    "content": "after b\n",
                    "expected_sha256": b_hash,
                },
            ],
            run_context=context,
        )
    assert current.read_text("thread", "a.txt") == "before a\n"
    assert current.read_text("thread", "b.txt") == "before b\n"


def test_create_file_locked_serializes_same_thread_and_path(tmp_path):
    current = service(tmp_path)

    def create(content):
        try:
            return current.create_file_locked("thread", "exports/report.csv", content)
        except WorkspacePathConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, (b"first", b"second")))

    assert results.count("conflict") == 1
    assert sum(isinstance(result, dict) for result in results) == 1
    assert current.file_bytes("thread", "exports/report.csv")[0] in {b"first", b"second"}


def test_智能体新建覆盖和安全移动返回中文提示(tmp_path):
    current = service(tmp_path)
    toolkit = BaseToolkit(current)
    tools = toolkit.functions
    context = RunContext(run_id="run", session_id="thread")

    created = tools["workspace_write_file"].entrypoint(
        path="新建.txt",
        content="内容",
        run_context=context,
    )
    replaced = tools["workspace_replace_file"].entrypoint(
        path="新建.txt",
        content="新内容",
        run_context=context,
    )
    moved = tools["workspace_move_file"].entrypoint(
        source="新建.txt",
        destination="已移动.txt",
        run_context=context,
    )

    assert created["message"] == "文件已新建。"
    assert replaced["message"] == "文件已覆盖。"
    assert moved["message"] == "文件或目录已移动。"


@pytest.mark.parametrize(
    "path",
    [
        "报表/原始数据/11111111-1111-4111-8111-111111111111/分片/数据-0001.jsonl",
        "reports/data/legacy.jsonl",
    ],
)
def test_智能体文本工具禁止读取受控原始报表分片(tmp_path, path):
    current = service(tmp_path)
    current.upload("thread", path, b'{"secret":"raw"}\n')
    current_tools = BaseToolkit(current).functions

    with pytest.raises(WorkspaceError, match="不能进入智能体上下文"):
        current_tools["workspace_read_file"].entrypoint(
            path=path,
            run_context=RunContext(run_id="run", session_id="thread"),
        )
    assert current.file_bytes("thread", path)[0] == b'{"secret":"raw"}\n'


def test_中文路径长度层级控制字符和目录穿越受到限制(tmp_path):
    current = service(tmp_path)
    current.create_file("thread", "资料/报告.md", "内容".encode())
    assert current.read_text("thread", "资料/报告.md") == "内容"

    valid_boundary = "/".join(["a" * 204] * 5)
    assert len(valid_boundary.encode()) == MAX_PATH_BYTES
    assert current.normalize_path(valid_boundary)[0] == valid_boundary

    with pytest.raises(WorkspaceError, match="超过 1024 字节"):
        current.normalize_path("/".join(["a" * 205] + ["a" * 204] * 4))
    with pytest.raises(WorkspaceError, match="名称超过 255 字节"):
        current.normalize_path("a" * (MAX_PATH_COMPONENT_BYTES + 1))
    with pytest.raises(WorkspaceError, match="目录层级超过 32 层"):
        current.normalize_path("/".join(["a"] * (MAX_PATH_DEPTH + 1)))
    with pytest.raises(WorkspaceError, match="控制字符"):
        current.normalize_path("资料/报\n告.md")
    with pytest.raises(WorkspaceError, match="控制字符"):
        current.normalize_path("资料/报\x85告.md")
    with pytest.raises(WorkspaceError, match="目录穿越"):
        current.normalize_path("资料/../报告.md")
    with pytest.raises(WorkspaceError, match="绝对路径"):
        current.normalize_path("C:\\Windows\\system.ini")


def test_中文文件使用流式下载并限制实际返回大小(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.create_file("thread", "资料/报告.md", "内容".encode())
    sandbox = current.sandbox_for("thread")
    remote = f"{WORKSPACE_ROOT}/资料/报告.md"
    sandbox.fs.download_file = lambda _path: (_ for _ in ()).throw(
        AssertionError("中文路径不应使用 bulk 下载")
    )

    assert current.file_bytes("thread", "资料/报告.md")[0] == "内容".encode()
    assert current.read_text("thread", "资料/报告.md") == "内容"
    assert sandbox.fs.stream_download_calls == [remote, remote]

    monkeypatch.setattr(workspace_module, "MAX_DOWNLOAD_BYTES", 4)
    sandbox.fs.entries[remote][0].size = 4
    with pytest.raises(WorkspaceError, match="超过允许大小"):
        current.file_bytes("thread", "资料/报告.md")


def test_文本读取严格区分目录二进制非_utf8_和大小边界(tmp_path):
    current = service(tmp_path)
    sandbox = current.sandbox_for("thread")
    sandbox.fs.create_folder(f"{WORKSPACE_ROOT}/目录", "700")
    current.upload("thread", "二进制.bin", b"a\x00b")
    current.upload("thread", "非编码.txt", b"\xff")
    current.upload("thread", "边界.txt", b"x" * MAX_READ_BYTES)
    current.upload("thread", "过大.txt", b"x" * (MAX_READ_BYTES + 1))

    with pytest.raises(WorkspaceError, match="目录.*文本文件"):
        current.read_text("thread", "目录")
    with pytest.raises(WorkspaceError, match="二进制内容"):
        current.read_text("thread", "二进制.bin")
    with pytest.raises(WorkspaceError, match="不是 UTF-8"):
        current.read_text("thread", "非编码.txt")
    assert len(current.read_text("thread", "边界.txt")) == MAX_READ_BYTES
    with pytest.raises(WorkspaceError, match="超过 1 MB"):
        current.read_text("thread", "过大.txt")


def test_沙箱启动异常多实例与后端故障均明确处理(tmp_path):
    current = service(tmp_path)
    sandbox = current.sandbox_for("thread")
    sandbox.state = "starting"
    with pytest.raises(WorkspaceError, match="正在启动"):
        current.sandbox_for("thread")
    sandbox.state = "error"
    with pytest.raises(WorkspaceError, match="状态异常"):
        current.sandbox_for("thread")
    sandbox.state = "stopped"
    assert current.sandbox_for("thread").state == "started"

    duplicate_client = FakeClient()
    duplicate = service(tmp_path, duplicate_client)
    label = duplicate._hash("duplicate")
    duplicate_client.sandboxes = {
        "one": FakeSandbox("one", {"agui-thread": label}),
        "two": FakeSandbox("two", {"agui-thread": label}),
    }
    with pytest.raises(WorkspaceError, match="多个运行环境"):
        duplicate.sandbox_for("duplicate")

    missing_root = FakeSandbox("missing", {})
    missing_root.fs.entries.pop(WORKSPACE_ROOT)
    current._ensure_directory(missing_root, WORKSPACE_ROOT)
    assert WORKSPACE_ROOT in missing_root.fs.entries

    broken = FakeSandbox("broken", {})
    broken.fs.get_file_info = lambda _path: (_ for _ in ()).throw(RuntimeError("backend failed"))
    with pytest.raises(RuntimeError, match="backend failed"):
        current._ensure_directory(broken, WORKSPACE_ROOT)


@pytest.mark.anyio
async def test_分支工作区使用异步客户端完整复制目录和文件(tmp_path):
    current = service(tmp_path)
    current.create_file("source", "资料/报告.txt", "内容".encode())
    current.create_file("source", "根文件.bin", b"binary")
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )

    result = await async_service.acopy_branch("source", "target")

    assert result == {"files": 2, "bytes": len("内容".encode()) + 6}
    assert current.file_bytes("target", "资料/报告.txt")[0] == "内容".encode()
    assert current.file_bytes("target", "根文件.bin")[0] == b"binary"
    assert current.file_bytes("source", "根文件.bin")[0] == b"binary"


@pytest.mark.anyio
async def test_异步分支工作区先校验限制和符号链接再创建目标(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.create_file("source", "一.txt", b"1")
    current.create_file("source", "二.txt", b"22")
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    monkeypatch.setattr(workspace_module, "MAX_BRANCH_FILES", 1)

    with pytest.raises(WorkspaceError, match="文件数超过"):
        await async_service.acopy_branch("source", "too-many")
    assert current.sandbox_for("too-many", create=False) is None

    monkeypatch.setattr(workspace_module, "MAX_BRANCH_FILES", 2000)
    monkeypatch.setattr(workspace_module, "MAX_BRANCH_TOTAL_BYTES", 2)
    with pytest.raises(WorkspaceError, match="总大小超过"):
        await async_service.acopy_branch("source", "too-large")
    assert current.sandbox_for("too-large", create=False) is None

    monkeypatch.setattr(workspace_module, "MAX_BRANCH_TOTAL_BYTES", 256 * 1024 * 1024)
    source = current.sandbox_for("source")
    source.fs.entries[f"{WORKSPACE_ROOT}/link"] = (
        Info("link", mode="lrwxrwxrwx"),
        b"",
    )
    with pytest.raises(WorkspaceError, match="符号链接"):
        await async_service.acopy_branch("source", "linked")
    assert current.sandbox_for("linked", create=False) is None


@pytest.mark.anyio
async def test_异步分支工作区复制失败会清理目标(tmp_path):
    current = service(tmp_path)
    current.create_file("source", "report.txt", b"content")
    source = current.sandbox_for("source")
    source.fs.download_file = lambda _path: (_ for _ in ()).throw(RuntimeError("offline"))
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )

    with pytest.raises(RuntimeError, match="offline"):
        await async_service.acopy_branch("source", "target")

    assert current.sandbox_for("target", create=False) is None


@pytest.mark.anyio
async def test_异步分支工作区复制被取消也会清理目标(tmp_path, monkeypatch):
    current = service(tmp_path)
    current.create_file("source", "报告.txt", b"content")
    download_started = asyncio.Event()
    never_complete = asyncio.Event()

    async def blocking_download(_self, _path):
        download_started.set()
        await never_complete.wait()

    monkeypatch.setattr(AsyncFakeFs, "download_file_stream", blocking_download)
    async_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )

    copy_task = asyncio.create_task(async_service.acopy_branch("source", "target"))
    await download_started.wait()
    copy_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await copy_task

    assert current.sandbox_for("target", create=False) is None


@pytest.mark.integration
def test_数据库注册表会串行化两个工作区服务():
    client = FakeClient()
    thread = "concurrent-" + uuid.uuid4().hex
    first = WorkspaceService(SECRET, client=client, registry=SandboxRegistry())
    second = WorkspaceService(SECRET, client=client, registry=SandboxRegistry())
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            sandboxes = list(pool.map(lambda service: service.sandbox_for(thread), [first, second]))
        assert sandboxes[0].id == sandboxes[1].id
        assert len(client.created) == 1
    finally:
        first.destroy(thread)
