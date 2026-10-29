"""源码静态证明只在当前实例及完整上下文内复用，实际文件身份始终重读。"""

import hashlib
from dataclasses import replace

import pytest

from smart_reporting.reporting.code_agent import toolkit as module
from smart_reporting.reporting.code_agent.context import (
    ExecutionReceipt,
    ReportingCodingTaskBinding,
    ReportingCodingTaskContext,
)
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.host_workspace import (
    HostReportingWorkspace,
    ReportingWorkspaceRegistry,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.scope import ReportingWorkflowScope
from smart_reporting.workspace import WorkspaceError

pytestmark = [pytest.mark.anyio, pytest.mark.parametrize("anyio_backend", ["asyncio"])]

SOURCE = "from pathlib import Path\nPath('analysis/out.json').write_text('{}')\n"


@pytest.fixture
def workspace(tmp_path):
    scope = ReportingWorkflowScope(
        run_id="run-1", external_run_id="external-1", session_id="session-1",
        caller_thread_id="thread-1", user_id="user-1", database="database-1",
        company_id="company-1", thread_lease_key="lease-1", workspace_key="workspace-1",
    )
    return HostReportingWorkspace(ReportingWorkspaceRegistry(tmp_path, secret="0" * 32).resolve(scope))


@pytest.fixture
def toolkit(workspace):
    context = ReportingCodingTaskContext(
        task_id="task-1", task_kind="analysis", code_mode_session_id="code-task-1",
        workspace_key=workspace.identity.workspace_key, workspace_root=workspace.identity.root,
        script_path="analysis/a.py", authorized_read_paths=(),
        authorized_write_paths=("analysis/a.py", "analysis/out.json"),
        declared_output_paths=("analysis/out.json",), max_source_bytes=128 * 1024,
    )
    return module.ReportingCodeModeToolkit(
        ReportingCodingTaskBinding(context, workspace), object(), ReportingLspProcessManager()
    )


@pytest.fixture
def validations(monkeypatch):
    original = module.validate_script_source
    calls = []

    def validate(context, source):
        calls.append((context, source))
        return original(context, source)

    monkeypatch.setattr(module, "validate_script_source", validate)
    return calls


async def test_identical_source_validates_once_but_reads_actual_file_every_time(
    toolkit, workspace, validations, monkeypatch
):
    await workspace.awrite_text("fixture", toolkit.context.script_path, SOURCE)
    original = workspace.read_limited_regular_file
    reads = []

    async def read(task_id, path, *, max_bytes):
        reads.append((task_id, path, max_bytes))
        return await original(task_id, path, max_bytes=max_bytes)

    monkeypatch.setattr(workspace, "read_limited_regular_file", read)

    identities = [await toolkit._validated_source_identity() for _ in range(3)]

    assert [identity.model_dump() for identity in identities] == [dict(
        path="analysis/a.py", size=len(SOURCE.encode()),
        sha256=hashlib.sha256(SOURCE.encode()).hexdigest(),
    )] * 3
    assert len({id(identity) for identity in identities}) == 3
    assert len(validations) == 1
    assert reads == [("task-1", "analysis/a.py", 128 * 1024)] * 3


async def test_changed_bytes_revalidate_and_only_latest_success_is_reused(
    toolkit, workspace, validations
):
    first = "print('a')\n"
    changed = "print('b')\n"
    identities = []
    for source in (first, first, changed, changed, first):
        await workspace.awrite_text("fixture", toolkit.context.script_path, source, overwrite=True)
        identities.append(await toolkit._validated_source_identity())

    assert [source for _context, source in validations] == [first, changed, first]
    assert identities[0] == identities[1] == identities[4]
    assert identities[2] == identities[3]
    assert identities[0].sha256 != identities[2].sha256


@pytest.mark.parametrize("invalid,code", [
    (b"if :\n", "report_code_source_invalid"),
    (b"from pathlib import Path\nPath('foreign.csv').read_text()\n", "report_python_source_path_invalid"),
    (b"\xff", "report_code_source_invalid"),
])
async def test_rejected_source_is_never_cached_and_invalidates_previous_success(
    toolkit, workspace, validations, invalid, code
):
    await workspace.awrite_text("fixture", toolkit.context.script_path, SOURCE)
    await toolkit._validated_source_identity()
    await workspace.awrite_bytes("fixture", toolkit.context.script_path, invalid, overwrite=True)

    for _ in range(2):
        with pytest.raises(ReportingError) as caught:
            await toolkit._validated_source_identity()
        assert caught.value.code == code

    await workspace.awrite_text("fixture", toolkit.context.script_path, SOURCE, overwrite=True)
    await toolkit._validated_source_identity()
    assert [source for _context, source in validations].count(SOURCE) == 2
    assert len(validations) == (2 if invalid == b"\xff" else 4)


async def test_missing_source_is_not_hidden_by_previous_success(toolkit, workspace, validations):
    await workspace.awrite_text("fixture", toolkit.context.script_path, SOURCE)
    await toolkit._validated_source_identity()
    await workspace.adelete_file("fixture", toolkit.context.script_path)

    with pytest.raises(WorkspaceError):
        await toolkit._validated_source_identity()

    await workspace.awrite_text("fixture", toolkit.context.script_path, SOURCE)
    await toolkit._validated_source_identity()
    assert len(validations) == 2


@pytest.mark.parametrize("field,value", [
    ("task_id", "task-2"),
    ("task_kind", "visualization"),
    ("code_mode_session_id", "code-task-2"),
    ("workspace_key", "workspace-2"),
    ("workspace_root", "another-root"),
    ("script_path", "analysis/b.py"),
    ("authorized_read_paths", ("data.csv",)),
    ("authorized_write_paths", ("analysis/a.py", "analysis/out.json", "analysis/extra.json")),
    ("declared_output_paths", ()),
    ("max_source_bytes", 64 * 1024),
])
async def test_every_context_field_change_requires_new_validation(
    toolkit, workspace, validations, field, value
):
    await workspace.awrite_text("fixture", toolkit.context.script_path, SOURCE)
    await toolkit._validated_source_identity()
    updates = {field: value}
    if field == "script_path":
        await workspace.awrite_text("fixture", value, SOURCE)
        updates["authorized_write_paths"] = (*toolkit.context.authorized_write_paths, value)
    elif field == "workspace_root":
        updates[field] = workspace.identity.root / value
    toolkit.binding.context = replace(toolkit.context, **updates)

    await toolkit._validated_source_identity()
    await toolkit._validated_source_identity()

    assert len(validations) == 2
    assert validations[0][0] != validations[1][0]


async def test_changed_workspace_scope_requires_new_validation(toolkit, workspace, validations):
    await workspace.awrite_text("fixture", toolkit.context.script_path, SOURCE)
    await toolkit._validated_source_identity()
    workspace.identity = replace(workspace.identity, scope_fingerprint="another-scope")

    await toolkit._validated_source_identity()
    await toolkit._validated_source_identity()

    assert len(validations) == 2


async def test_narrowed_read_authorization_rejects_previously_valid_source(
    toolkit, workspace, validations
):
    source = "from pathlib import Path\nPath('data.csv').read_text()\n"
    toolkit.binding.context = replace(toolkit.context, authorized_read_paths=("data.csv",))
    await workspace.awrite_text("fixture", toolkit.context.script_path, source)
    await toolkit._validated_source_identity()
    toolkit.binding.context = replace(toolkit.context, authorized_read_paths=())

    for _ in range(2):
        with pytest.raises(ReportingError) as caught:
            await toolkit._validated_source_identity()
        assert caught.value.code == "report_python_source_path_invalid"
    assert len(validations) == 3


async def test_new_toolkit_never_inherits_previous_instance_validation(
    toolkit, workspace, validations
):
    await workspace.awrite_text("fixture", toolkit.context.script_path, SOURCE)
    await toolkit._validated_source_identity()
    other = module.ReportingCodeModeToolkit(
        ReportingCodingTaskBinding(toolkit.context, workspace), object(), ReportingLspProcessManager()
    )

    await other._validated_source_identity()
    await other._validated_source_identity()

    assert len(validations) == 2


@pytest.mark.parametrize("changed_path,changed", [
    ("analysis/a.py", b"print('changed')\n"),
    ("analysis/out.json", b"{\"changed\":true}"),
])
async def test_current_receipt_still_rejects_changed_source_or_output(
    toolkit, workspace, validations, changed_path, changed
):
    await workspace.awrite_text("fixture", toolkit.context.script_path, SOURCE)
    await workspace.awrite_bytes("fixture", "analysis/out.json", b"{}")
    receipt = ExecutionReceipt(
        runId="run-1", sourceFile=await toolkit._validated_source_identity(),
        outputFiles=(FileIdentity.model_validate(
            await workspace.ahash_file("fixture", "analysis/out.json")
        ),),
    )
    await toolkit.require_current_receipt(receipt)
    await toolkit.require_current_receipt(receipt)
    assert len(validations) == 1
    await workspace.awrite_bytes("fixture", changed_path, changed, overwrite=True)

    with pytest.raises(ReportingError) as caught:
        await toolkit.require_current_receipt(receipt)

    assert caught.value.code == "report_phase_artifact_changed"
    assert len(validations) == (2 if changed_path.endswith(".py") else 1)
