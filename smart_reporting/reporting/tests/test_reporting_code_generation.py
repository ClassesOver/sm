from __future__ import annotations

import hashlib

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime.code_generation import (
    CodeGenerationResult,
    ReportingCodeGenerationRunner,
)


class FakeAgent:
    def __init__(self, action):
        self.action = action
        self.tools = []
        self.tool_choice = None

    async def arun(self, _prompt, **_kwargs):
        return await self.action(self)


def identity(path: str, content: str) -> FileIdentity:
    raw = content.encode()
    return FileIdentity(path=path, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.anyio
async def test_generate_exposes_only_patch_and_returns_single_identity():
    calls = []

    async def action(agent):
        assert [tool.name for tool in agent.tools] == ["apply_analysis_patch"]
        assert agent.tool_choice["function"]["name"] == "apply_analysis_patch"
        return await agent.tools[0].entrypoint(patch="diff")

    async def patch(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "artifacts": [identity("analysis/script.py", "print(1)\n")]}

    runner = ReportingCodeGenerationRunner(agent=FakeAgent(action))
    result = await runner.generate("analysis/script.py", {"fact": 1}, patch)

    assert isinstance(result, CodeGenerationResult)
    assert result.script_file.path == "analysis/script.py"
    assert calls == [{"patch": "diff"}]


@pytest.mark.anyio
async def test_generate_rejects_plain_text_without_mutation():
    async def action(_agent):
        return "print('source')"

    mutated = False

    async def patch(**_kwargs):
        nonlocal mutated
        mutated = True
        return {"ok": True, "artifacts": []}

    runner = ReportingCodeGenerationRunner(agent=FakeAgent(action))
    with pytest.raises(ReportingError) as raised:
        await runner.generate("analysis/script.py", {}, patch)

    assert raised.value.code == "report_code_generation_no_patch"
    assert mutated is False


@pytest.mark.anyio
async def test_repair_reads_once_then_uses_fresh_patch_agent():
    script = identity("analysis/script.py", "print(1)\n")
    seen_tools = []
    agents = []

    async def action(agent):
        agents.append(agent)
        tool = agent.tools[0]
        seen_tools.append(tool.name)
        if tool.name == "read_file":
            return await tool.entrypoint(path="analysis/script.py")
        return await tool.entrypoint(patch="diff")

    async def read_file(**kwargs):
        return {
            "ok": True,
            "path": kwargs["path"],
            "content": "print(1)\n",
            "sha256": script.sha256,
            "offset": 0,
            "nextOffset": len("print(1)\n"),
            "totalBytes": len("print(1)\n"),
        }

    async def patch(**_kwargs):
        return {"ok": True, "artifacts": [identity(script.path, "print(2)\n")]}

    runner = ReportingCodeGenerationRunner(agent_factory=lambda: FakeAgent(action))
    result = await runner.repair(script, {"code": "bad"}, read_file, patch)

    assert result.script_file.sha256 == hashlib.sha256(b"print(2)\n").hexdigest()
    assert seen_tools == ["read_file", "apply_analysis_patch"]
    assert agents[0] is not agents[1]
