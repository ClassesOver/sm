import hashlib
from collections import OrderedDict
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from smart_reporting.sandbox import ExecRequest, SandboxNotFound
from smart_reporting.skills import SkillValidator
from smart_reporting.task_execution.execution import TaskExecutionKernel


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
