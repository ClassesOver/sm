import hashlib
import json
import os
import shlex
import uuid
from contextlib import asynccontextmanager

import pytest
from agno.run import RunContext
from daytona import AsyncDaytona, CreateSandboxFromSnapshotParams
from daytona.common.errors import DaytonaNotFoundError

from smart_reporting.database import create_agent_database
from smart_reporting.skills import skill_script_receipt_hook
from smart_reporting.task_execution.execution import CODING_TASK_DEPENDENCY, CodingExecutionKernel
from smart_reporting.task_execution.models import CodingScope, Lease
from smart_reporting.task_execution.repository import CodingTaskRepository
from smart_reporting.workspace import (
    WORKSPACE_ROOT,
    WORKSPACE_SNAPSHOT,
    WorkspaceError,
    WorkspaceService,
)


class _AsyncLockRegistry:
    @asynccontextmanager
    async def locked(self, _key):
        yield self


class _BoundWorkspaceService(WorkspaceService):
    def __init__(self, client, sandbox):
        super().__init__(
            "0123456789abcdef0123456789abcdef",
            async_client=client,
            async_registry=_AsyncLockRegistry(),
        )
        self.sandbox = sandbox

    async def _asandbox_for(self, _client, _thread):
        return self.sandbox


@pytest.mark.integration
@pytest.mark.anyio
async def test_coding_model_cannot_modify_installed_skill_script_in_daytona(tmp_path):
    if not os.getenv("DAYTONA_API_KEY"):
        pytest.skip("需要 Daytona API Key")

    body = (
        "from pathlib import Path\n"
        f"Path({f'{WORKSPACE_ROOT}/skill-executed.txt'!r}).write_text('executed')\n"
        "print('skill-ok')\n"
    )
    expected_sha256 = hashlib.sha256(body.encode()).hexdigest()
    sandbox = None
    database = None
    async with AsyncDaytona() as client:
        try:
            sandbox = await client.create(
                CreateSandboxFromSnapshotParams(
                    name=f"agent-skill-readonly-{uuid.uuid4().hex[:8]}",
                    snapshot=os.getenv("DAYTONA_DEFAULT_SNAPSHOT", WORKSPACE_SNAPSHOT),
                    public=False,
                    ephemeral=True,
                    auto_stop_interval=60,
                    auto_archive_interval=0,
                    network_block_all=True,
                ),
                timeout=180,
            )
            service = _BoundWorkspaceService(client, sandbox)
            try:
                await sandbox.fs.get_file_info(WORKSPACE_ROOT)
            except DaytonaNotFoundError:
                await sandbox.fs.create_folder(WORKSPACE_ROOT, "700")
            database = create_agent_database(f"sqlite:///{tmp_path / 'agent.db'}")
            repository = CodingTaskRepository(database.async_db)
            scope = CodingScope(
                "skill-readonly-integration",
                "user",
                "thread",
                str(sandbox.id),
                "coding-agent",
            )
            task = await repository.create_task_with_initial_attempt(scope, "验证 Skill 脚本只读")
            lease = await repository.claim_lease(scope.external_run_id, "integration-request")
            assert isinstance(lease, Lease)
            _task, attempt = await repository.open_initial(
                scope.external_run_id, lease, task.state_version
            )
            context = RunContext(
                run_id=attempt.internal_run_id,
                session_id="thread",
                user_id="user",
                session_state={},
                dependencies={
                    CODING_TASK_DEPENDENCY: {
                        "externalRunId": scope.external_run_id,
                        "leaseOwner": "integration-request",
                        "leaseEpoch": lease.epoch,
                        "sandboxId": scope.sandbox_id,
                    }
                },
            )
            kernel = CodingExecutionKernel(service, repository)

            async def read_script(**_kwargs):
                return json.dumps(
                    {
                        "skill_name": "integration-skill",
                        "script_path": "validate.py",
                        "content": body,
                    }
                )

            raw = await skill_script_receipt_hook(
                context,
                "get_skill_script",
                read_script,
                {
                    "skill_name": "integration-skill",
                    "script_path": "validate.py",
                    "execute": False,
                },
                workspace_service=service,
            )
            readonly_path = json.loads(raw)["readonly_path"]

            identity = await kernel.terminal(
                f"id -un && stat -c '%U:%G %a' -- {shlex.quote(readonly_path)}",
                run_context=context,
            )
            assert identity["exit_code"] == 0, identity["output"]
            assert "daytona\nroot:root 555" in identity["output"]

            executed = await kernel.terminal(
                f"python3 -I -B {shlex.quote(readonly_path)}",
                run_context=context,
            )
            assert executed["exit_code"] == 0, executed["output"]
            assert executed["output"].strip().endswith("skill-ok")
            assert (
                await sandbox.fs.download_file(f"{WORKSPACE_ROOT}/skill-executed.txt")
                == b"executed"
            )

            mutation_program = "\n".join(
                [
                    "import json",
                    "import subprocess",
                    "from pathlib import Path",
                    f"path = Path({readonly_path!r})",
                    "operations = {",
                    "    'overwrite': lambda: path.write_text('changed'),",
                    "    'move': lambda: path.rename(path.with_suffix('.moved')),",
                    "    'delete': lambda: path.unlink(),",
                    "    'chmod': lambda: path.chmod(0o755),",
                    "    'move_root': lambda: path.parents[2].rename(",
                    "        path.parents[2].with_name('.agentos-moved')",
                    "    ),",
                    "    'sudo': lambda: subprocess.run(",
                    "        ['sudo', 'python3', '-c',",
                    "         f\"from pathlib import Path; Path({str(path)!r}).write_text('sudo')\"],",
                    "        check=True, capture_output=True, text=True,",
                    "    ),",
                    "}",
                    "blocked = {}",
                    "for name, operation in operations.items():",
                    "    try:",
                    "        operation()",
                    "    except Exception:",
                    "        blocked[name] = True",
                    "    else:",
                    "        blocked[name] = False",
                    "print(json.dumps(blocked, sort_keys=True))",
                ]
            )
            mutation = await kernel.terminal(
                f"python3 -I -B -c {shlex.quote(mutation_program)}",
                run_context=context,
            )
            assert mutation["exit_code"] == 0, mutation["output"]
            mutation_result = next(
                line for line in reversed(mutation["output"].splitlines()) if line.strip()
            )
            assert json.loads(mutation_result) == {
                "chmod": True,
                "delete": True,
                "move": True,
                "move_root": True,
                "overwrite": True,
                "sudo": True,
            }
            installed = await sandbox.fs.download_file(readonly_path)
            assert hashlib.sha256(installed).hexdigest() == expected_sha256
            with pytest.raises(WorkspaceError):
                WorkspaceService.normalize_path(readonly_path, allow_root=False)
        finally:
            if database is not None:
                await database.async_engine.dispose()
                database.sync_engine.dispose()
            if sandbox is not None:
                await client.delete(sandbox)
