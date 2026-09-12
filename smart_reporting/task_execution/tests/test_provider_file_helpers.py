import hashlib
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.sandbox import ExecRequest, SandboxNotFound
from smart_reporting.skills import SkillValidator
from smart_reporting.task_execution.execution import TaskExecutionKernel, TaskExecutionRuntime
from smart_reporting.task_execution.repository_impl import TaskExecution


class _ProviderFileSystem:
    def __init__(self) -> None:
        self.entries = {}

    async def get_file_info(self, path):
        try:
            return self.entries[path][0]
        except KeyError as error:
            raise SandboxNotFound("missing") from error

    async def create_folder(self, path, _mode):
        self.entries[path] = (SimpleNamespace(is_dir=True, mode="drwxr-xr-x"), b"")

    async def upload_file(self, content, path):
        self.entries[path] = (SimpleNamespace(is_dir=False, mode="-rw-r--r--"), bytes(content))

    async def download_file(self, path):
        return self.entries[path][1]


class _ProviderProcess:
    def __init__(self) -> None:
        self.requests = []

    async def exec(self, request):
        self.requests.append(request)
        return SimpleNamespace(exit_code=0)


class _Registry:
    @asynccontextmanager
    async def locked(self, _key):
        yield self


class _Service:
    def __init__(self) -> None:
        self.async_registry = _Registry()

    @staticmethod
    def _is_symlink(info):
        return str(getattr(info, "mode", "")).startswith("l")

    @staticmethod
    def _is_regular_file(info):
        return not info.is_dir and not str(getattr(info, "mode", "")).startswith("l")

    @staticmethod
    async def _adownload_file(sandbox, path, _max_bytes, *, timeout):
        del timeout
        return await sandbox.fs.download_file(path)


def _provider_kernel():
    service = _Service()
    process = _ProviderProcess()
    sandbox = SimpleNamespace(
        ref=SimpleNamespace(resource_id="provider-1"),
        fs=_ProviderFileSystem(),
        process=process,
    )
    kernel = TaskExecutionKernel(service, repository=SimpleNamespace())
    kernel._terminal_runtimes = OrderedDict()

    async def use_sandbox(_scope):
        yield sandbox

    kernel._sandbox = use_sandbox
    return kernel, sandbox, process


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("exit_code", "output", "failure_code", "summary", "output_truncated"),
    [
        (
            0,
            "Traceback (most recent call last):\n"
            '  File "analysis.py", line 1, in <module>\n'
            "NameError: name 'pd' is not defined\n",
            "python_traceback",
            "NameError: name 'pd' is not defined",
            True,
        ),
        (
            0,
            "[FAIL] chart.png: image is blank",
            "deterministic_failure",
            "[FAIL] chart.png: image is blank",
            False,
        ),
        (2, "render command failed", "nonzero_exit", "render command failed", False),
        (
            None,
            "runner stopped",
            "runner_exception",
            "Python runner did not return a valid exit code",
            False,
        ),
    ],
)
async def test_python_runner_archives_failures_in_execution_receipt(
    exit_code: int | None,
    output: str,
    failure_code: str,
    summary: str,
    output_truncated: bool,
):
    service = SimpleNamespace(
        arun_python_script=AsyncMock(
            return_value={
                "ok": True,
                "status": "completed",
                "exitCode": exit_code,
                "output": output,
                "scriptPath": "analysis.py",
                "scriptSize": 128,
                "scriptSha256": "a" * 64,
                "dependencyBundleDigest": "sha256:" + "b" * 64,
                "outputTruncated": output_truncated,
            }
        )
    )
    execution = TaskExecution(
        execution_id="execution-1",
        external_run_id="external-1",
        internal_run_id="internal-1",
        owner_user_id="user-1",
        thread_id="thread-1",
        sandbox_id="sandbox-1",
        daytona_session_id="python-execution-1",
        command_id=None,
        status="running",
        output_cursor=0,
        terminal_output="",
        exit_code=None,
        mutation_sequence=1,
        is_verification=False,
        retained_service=False,
        operation_receipt={"runner": "python", "scriptPath": "analysis.py"},
    )
    repository = SimpleNamespace(
        increment_mutation=AsyncMock(return_value=1),
        reserve_execution=AsyncMock(return_value=execution),
        update_execution=AsyncMock(
            side_effect=lambda execution_id, **values: replace(
                execution,
                execution_id=execution_id,
                status=values["status"],
                terminal_output=values["output"],
                output_cursor=len(values["output"]),
                exit_code=values["exit_code"],
                operation_receipt=values["operation_receipt"],
            )
        ),
        record_execution_mutation=AsyncMock(),
    )
    kernel = TaskExecutionKernel(service, repository)
    scope = TaskExecutionRuntime(
        task=SimpleNamespace(mutation_sequence=0),
        external_run_id="external-1",
        internal_run_id="internal-1",
        owner_user_id="user-1",
        thread_id="thread-1",
        sandbox_id="sandbox-1",
        lease_owner="lease-1",
        lease_epoch=1,
        attempt_no=0,
    )

    result = await kernel.run_python_script("analysis.py", _scope=scope)

    assert result["ok"] is False
    assert result["code"] == "execution_output_error"
    assert result["details"]["failureCode"] == failure_code
    assert result["status"] == "failed"
    receipt = repository.update_execution.await_args.kwargs["operation_receipt"]
    assert receipt == {
        "version": "1",
        "runner": "python",
        "scriptPath": "analysis.py",
        "script": {"size": 128, "sha256": "a" * 64},
        "failure": {
            "code": failure_code,
            "summary": summary,
            "outputTruncated": output_truncated,
        },
    }
    assert "output" not in receipt
    assert "exitCode" not in receipt


@pytest.mark.anyio
async def test_python_runner_archives_runner_exception() -> None:
    service = SimpleNamespace(
        arun_python_script=AsyncMock(side_effect=RuntimeError("sandbox transport failed"))
    )
    execution = TaskExecution(
        execution_id="execution-1",
        external_run_id="external-1",
        internal_run_id="internal-1",
        owner_user_id="user-1",
        thread_id="thread-1",
        sandbox_id="sandbox-1",
        daytona_session_id="python-execution-1",
        command_id=None,
        status="running",
        output_cursor=0,
        terminal_output="",
        exit_code=None,
        mutation_sequence=1,
        is_verification=False,
        retained_service=False,
        operation_receipt={"runner": "python", "scriptPath": "analysis.py"},
    )
    repository = SimpleNamespace(
        increment_mutation=AsyncMock(return_value=1),
        reserve_execution=AsyncMock(return_value=execution),
        update_execution=AsyncMock(
            side_effect=lambda execution_id, **values: replace(
                execution,
                execution_id=execution_id,
                status=values["status"],
                terminal_output=values["output"],
                exit_code=values["exit_code"],
                operation_receipt=values["operation_receipt"],
            )
        ),
    )
    kernel = TaskExecutionKernel(service, repository)
    scope = TaskExecutionRuntime(
        task=SimpleNamespace(mutation_sequence=0),
        external_run_id="external-1",
        internal_run_id="internal-1",
        owner_user_id="user-1",
        thread_id="thread-1",
        sandbox_id="sandbox-1",
        lease_owner="lease-1",
        lease_epoch=1,
        attempt_no=0,
    )

    result = await kernel.run_python_script("analysis.py", _scope=scope)

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert repository.update_execution.await_args.kwargs["operation_receipt"] == {
        "version": "1",
        "runner": "python",
        "scriptPath": "analysis.py",
        "failure": {
            "code": "runner_exception",
            "summary": "sandbox transport failed",
            "outputTruncated": False,
        },
    }


@pytest.mark.anyio
async def test_python_runner_does_not_overwrite_receipt_when_mutation_recording_fails() -> None:
    service = SimpleNamespace(
        arun_python_script=AsyncMock(
            return_value={
                "ok": False,
                "status": "completed",
                "exitCode": 1,
                "output": "ValueError: invalid data",
                "scriptPath": "analysis.py",
                "scriptSize": 128,
                "scriptSha256": "a" * 64,
            }
        )
    )
    execution = TaskExecution(
        execution_id="execution-1",
        external_run_id="external-1",
        internal_run_id="internal-1",
        owner_user_id="user-1",
        thread_id="thread-1",
        sandbox_id="sandbox-1",
        daytona_session_id="python-execution-1",
        command_id=None,
        status="running",
        output_cursor=0,
        terminal_output="",
        exit_code=None,
        mutation_sequence=1,
        is_verification=False,
        retained_service=False,
        operation_receipt={"runner": "python", "scriptPath": "analysis.py"},
    )
    repository = SimpleNamespace(
        increment_mutation=AsyncMock(return_value=1),
        reserve_execution=AsyncMock(return_value=execution),
        update_execution=AsyncMock(
            side_effect=lambda execution_id, **values: replace(
                execution,
                execution_id=execution_id,
                status=values["status"],
                terminal_output=values["output"],
                output_cursor=len(values["output"]),
                exit_code=values["exit_code"],
                operation_receipt=values["operation_receipt"],
            )
        ),
        record_execution_mutation=AsyncMock(side_effect=RuntimeError("repository unavailable")),
    )
    kernel = TaskExecutionKernel(service, repository)
    scope = TaskExecutionRuntime(
        task=SimpleNamespace(mutation_sequence=0),
        external_run_id="external-1",
        internal_run_id="internal-1",
        owner_user_id="user-1",
        thread_id="thread-1",
        sandbox_id="sandbox-1",
        lease_owner="lease-1",
        lease_epoch=1,
        attempt_no=0,
    )

    with pytest.raises(RuntimeError, match="repository unavailable"):
        await kernel.run_python_script("analysis.py", _scope=scope)

    repository.update_execution.assert_awaited_once()
    receipt = repository.update_execution.await_args.kwargs["operation_receipt"]
    assert receipt["failure"]["code"] == "nonzero_exit"
    assert receipt["failure"]["summary"] == "ValueError: invalid data"


@pytest.mark.anyio
async def test_terminal_runtime_install_accepts_provider_not_found_and_exec_contract():
    kernel, sandbox, process = _provider_kernel()

    runtime_path = await kernel._install_terminal_runtime(SimpleNamespace(sandbox_id="provider-1"))

    assert runtime_path in sandbox.fs.entries
    assert len(process.requests) == 1
    assert isinstance(process.requests[0], ExecRequest)


@pytest.mark.anyio
async def test_validator_install_accepts_provider_not_found_and_exec_contract():
    kernel, sandbox, process = _provider_kernel()
    script = b"print('ok')\n"
    validator = SkillValidator(
        validator_id="review:report",
        skill_name="review",
        name="report",
        script_name="check.py",
        script_content=script,
        script_sha256=hashlib.sha256(script).hexdigest(),
        timeout=30,
        artifact_patterns=("reports/*.json",),
    )

    installed = await kernel._install_validator(
        SimpleNamespace(sandbox_id="provider-1"), validator, b"{}"
    )

    assert installed.script_path in sandbox.fs.entries
    assert len(process.requests) == 1
    assert isinstance(process.requests[0], ExecRequest)
