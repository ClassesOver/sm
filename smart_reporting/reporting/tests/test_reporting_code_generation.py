from __future__ import annotations

import hashlib
import json

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
        self.prompt = _prompt
        return await self.action(self)


def identity(path: str, content: str) -> FileIdentity:
    raw = content.encode()
    return FileIdentity(path=path, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def read_receipt(script: FileIdentity, content: str = "print(1)\n") -> dict[str, object]:
    size = len(content.encode())
    return {
        "ok": True,
        "path": script.path,
        "content": content,
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
        "offset": 0,
        "nextOffset": size,
        "totalBytes": size,
    }


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
async def test_generate_rejects_zero_tool_calls_without_mutation():
    async def action(_agent):
        return None

    async def patch(**_kwargs):
        pytest.fail("zero tool calls must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
            "analysis/script.py", {}, patch
        )

    assert raised.value.code == "report_code_generation_no_patch"


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
        receipt = read_receipt(script)
        receipt["path"] = kwargs["path"]
        return receipt

    async def patch(**_kwargs):
        return {"ok": True, "artifacts": [identity(script.path, "print(2)\n")]}

    runner = ReportingCodeGenerationRunner(agent_factory=lambda: FakeAgent(action))
    result = await runner.repair(script, {"code": "bad"}, read_file, patch)

    assert result.script_file.sha256 == hashlib.sha256(b"print(2)\n").hexdigest()
    assert seen_tools == ["read_file", "apply_analysis_patch"]
    assert agents[0] is not agents[1]


@pytest.mark.anyio
async def test_repair_rejects_reading_a_path_other_than_issued_script():
    script = identity("analysis/script.py", "print(1)\n")

    async def action(agent):
        return await agent.tools[0].entrypoint(path="analysis/other.py")

    async def read_file(**_kwargs):
        pytest.fail("wrong read path must not reach callback")

    async def patch(**_kwargs):
        pytest.fail("wrong read path must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "report_code_generation_read_invalid"
    assert raised.value.details == {"path": script.path}


@pytest.mark.anyio
async def test_repair_rejects_a_second_read_before_write_stage():
    script = identity("analysis/script.py", "print(1)\n")
    reads = 0

    async def action(agent):
        await agent.tools[0].entrypoint(path=script.path)
        await agent.tools[0].entrypoint(path=script.path)

    async def read_file(**_kwargs):
        nonlocal reads
        reads += 1
        return read_receipt(script)

    async def patch(**_kwargs):
        pytest.fail("second read must not reach write stage")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "report_code_generation_read_invalid"
    assert reads == 1


@pytest.mark.anyio
@pytest.mark.parametrize("output", [None, "print('direct source')"])
async def test_repair_rejects_read_stage_without_a_read_tool_call(output):
    script = identity("analysis/script.py", "print(1)\n")

    async def action(_agent):
        return output

    async def read_file(**_kwargs):
        pytest.fail("zero read tool calls must not reach callback")

    async def patch(**_kwargs):
        pytest.fail("zero read tool calls must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "report_code_generation_read_invalid"
    assert raised.value.details == {"path": script.path}


@pytest.mark.anyio
@pytest.mark.parametrize("output", [None, "print('direct source')"])
async def test_repair_rejects_write_stage_without_a_patch(output):
    script = identity("analysis/script.py", "print(1)\n")
    agents = []

    async def action(agent):
        agents.append(agent)
        if agent.tools[0].name == "read_file":
            return await agent.tools[0].entrypoint(path=script.path)
        return output

    async def read_file(**_kwargs):
        return read_receipt(script)

    async def patch(**_kwargs):
        pytest.fail("write stage without patch must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent_factory=lambda: FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "report_code_generation_no_patch"
    assert [agent.tools[0].name for agent in agents] == ["read_file", "apply_analysis_patch"]


@pytest.mark.anyio
async def test_repair_malformed_read_call_fails_before_a_fresh_retry_succeeds():
    script = identity("analysis/script.py", "print(1)\n")
    patch_calls = 0

    async def malformed(agent):
        await agent.tools[0].entrypoint()

    async def read(agent):
        return await agent.tools[0].entrypoint(path=script.path)

    async def write(agent):
        return await agent.tools[0].entrypoint(patch="diff")

    actions = iter([malformed, read, write])
    runner = ReportingCodeGenerationRunner(agent_factory=lambda: FakeAgent(next(actions)))

    async def read_file(**_kwargs):
        return read_receipt(script)

    async def patch(**_kwargs):
        nonlocal patch_calls
        patch_calls += 1
        return {"ok": True, "artifacts": [identity(script.path, "print(2)\n")]}

    with pytest.raises(ReportingError) as raised:
        await runner.repair(script, {}, read_file, patch)

    assert raised.value.code == "report_code_generation_read_invalid"
    assert patch_calls == 0

    result = await runner.repair(script, {}, read_file, patch)

    assert result.script_file.path == script.path
    assert patch_calls == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("offset", True),
        ("nextOffset", True),
        ("totalBytes", True),
        ("offset", -1),
        ("nextOffset", -1),
        ("totalBytes", -1),
    ],
)
async def test_repair_rejects_invalid_pagination_values(field, value):
    script = identity("analysis/script.py", "print(1)\n")

    async def action(agent):
        return await agent.tools[0].entrypoint(path=script.path)

    async def read_file(**_kwargs):
        receipt = read_receipt(script)
        receipt[field] = value
        return receipt

    async def patch(**_kwargs):
        pytest.fail("invalid read receipt must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "report_code_generation_read_invalid"
    assert raised.value.details == {"path": script.path}


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["offset", "nextOffset", "totalBytes"])
async def test_repair_requires_all_pagination_fields(field):
    script = identity("analysis/script.py", "print(1)\n")

    async def action(agent):
        return await agent.tools[0].entrypoint(path=script.path)

    async def read_file(**_kwargs):
        receipt = read_receipt(script)
        receipt.pop(field)
        return receipt

    async def patch(**_kwargs):
        pytest.fail("incomplete read receipt must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "report_code_generation_read_invalid"
    assert raised.value.details == {"path": script.path}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "update",
    [
        {"nextOffset": 1},
        {"totalBytes": 1},
        {"sha256": "0" * 64},
        {"content": "print(2)\n"},
    ],
)
async def test_repair_rejects_incomplete_or_identity_mismatched_read_receipt(update):
    script = identity("analysis/script.py", "print(1)\n")

    async def action(agent):
        return await agent.tools[0].entrypoint(path=script.path)

    async def read_file(**_kwargs):
        return {**read_receipt(script), **update}

    async def patch(**_kwargs):
        pytest.fail("invalid read receipt must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code in {
        "report_code_generation_read_incomplete",
        "report_code_generation_read_invalid",
    }
    assert raised.value.details == {"path": script.path}


@pytest.mark.anyio
async def test_repair_requires_read_byte_count_to_match_script_identity():
    original = identity("analysis/script.py", "print(1)\n")
    script = FileIdentity(path=original.path, size=original.size + 1, sha256=original.sha256)

    async def action(agent):
        return await agent.tools[0].entrypoint(path=script.path)

    async def read_file(**_kwargs):
        return read_receipt(original)

    async def patch(**_kwargs):
        pytest.fail("identity byte mismatch must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "report_code_generation_read_invalid"
    assert raised.value.details == {"path": script.path}


@pytest.mark.anyio
async def test_repair_rejects_oversized_read_receipt_before_patch_prompt():
    content = "#" * (128 * 1024 + 1)
    script = identity("analysis/script.py", content)
    prompts = []

    async def action(agent):
        prompts.append(agent.prompt)
        return await agent.tools[0].entrypoint(path=script.path)

    async def read_file(**_kwargs):
        return read_receipt(script, content)

    async def patch(**_kwargs):
        pytest.fail("oversized read receipt must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "report_code_generation_read_too_large"
    assert raised.value.details == {"path": script.path}
    assert len(prompts) == 1


@pytest.mark.anyio
async def test_repair_normalizes_diagnostic_and_read_receipt_before_patch_prompt():
    script = identity("analysis/script.py", "print(1)\n")
    prompts = []

    async def action(agent):
        tool = agent.tools[0]
        if tool.name == "read_file":
            return await tool.entrypoint(path=script.path)
        prompts.append(json.loads(agent.prompt))
        return await tool.entrypoint(patch="diff")

    async def read_file(**_kwargs):
        return {**read_receipt(script), "untrusted": "x" * 10_000}

    async def patch(**_kwargs):
        return {"ok": True, "artifacts": [identity(script.path, "print(2)\n")]}

    diagnostic = {
        "code": "repair_failed",
        "message": "m" * 10_000,
        "details": {"path": script.path, "line": 4, "source": "SECRET_SOURCE"},
        "receipt": "SECRET_RECEIPT",
    }
    await ReportingCodeGenerationRunner(agent_factory=lambda: FakeAgent(action)).repair(
        script, diagnostic, read_file, patch
    )

    facts = prompts[0]["facts"]
    assert set(facts["diagnostic"]) <= {"code", "message", "details"}
    assert facts["diagnostic"]["code"] == "repair_failed"
    assert len(facts["diagnostic"]["message"]) <= 512
    assert facts["diagnostic"]["details"] == {"path": script.path, "line": 4}
    assert "SECRET_SOURCE" not in agent_prompt_text(facts)
    assert "SECRET_RECEIPT" not in agent_prompt_text(facts)
    assert set(facts["readReceipt"]) == {"path", "sha256", "content", "totalBytes"}


def agent_prompt_text(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.anyio
async def test_repair_redacts_read_callback_errors():
    script = identity("analysis/script.py", "print(1)\n")

    async def action(agent):
        return await agent.tools[0].entrypoint(path=script.path)

    async def read_file(**_kwargs):
        raise ReportingError("workspace_read_failed", "SECRET_SOURCE", details={"content": "secret"})

    async def patch(**_kwargs):
        pytest.fail("read errors must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "workspace_read_failed"
    assert raised.value.details == {"path": script.path}
    assert "SECRET_SOURCE" not in str(raised.value.details)


@pytest.mark.anyio
async def test_repair_redacts_non_reporting_read_errors():
    script = identity("analysis/script.py", "print(1)\n")

    async def action(agent):
        return await agent.tools[0].entrypoint(path=script.path)

    async def read_file(**_kwargs):
        raise RuntimeError("SECRET_TOOL_RECEIPT")

    async def patch(**_kwargs):
        pytest.fail("read errors must not mutate")

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).repair(
            script, {}, read_file, patch
        )

    assert raised.value.code == "report_code_generation_read_failed"
    assert raised.value.details == {"path": script.path}
    assert "SECRET_TOOL_RECEIPT" not in str(raised.value.details)


@pytest.mark.anyio
async def test_generate_rejects_second_patch_after_one_mutation():
    calls = 0

    async def action(agent):
        await agent.tools[0].entrypoint(patch="first")
        await agent.tools[0].entrypoint(patch="second")

    async def patch(**_kwargs):
        nonlocal calls
        calls += 1
        return {"ok": True, "artifacts": [identity("analysis/script.py", "print(1)\n")]}

    with pytest.raises(ReportingError, match="multiple_patches"):
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
            "analysis/script.py", {}, patch
        )

    assert calls == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "receipt",
    [
        {"ok": False, "code": "patch_rejected", "message": "SECRET_SOURCE"},
        {"ok": True, "artifacts": []},
        {
            "ok": True,
            "artifacts": [
                identity("analysis/script.py", "print(1)\n"),
                identity("analysis/other.py", "print(2)\n"),
            ],
        },
        {"ok": True, "artifacts": [identity("analysis/other.py", "print(1)\n")]},
    ],
)
async def test_generate_rejects_failed_or_ambiguous_patch_receipts(receipt):
    async def action(agent):
        return await agent.tools[0].entrypoint(patch="diff")

    async def patch(**_kwargs):
        return receipt

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
            "analysis/script.py", {}, patch
        )

    assert raised.value.code in {
        "patch_rejected",
        "report_code_generation_artifact_invalid",
        "report_code_generation_path_mismatch",
    }
    assert "SECRET_SOURCE" not in str(raised.value.details)


@pytest.mark.anyio
async def test_generate_rejects_malformed_tool_arguments_without_mutation():
    mutated = False

    async def action(agent):
        await agent.tools[0].entrypoint()  # truncated/malformed tool JSON has no patch field

    async def patch(**_kwargs):
        nonlocal mutated
        mutated = True
        return {"ok": True, "artifacts": [identity("analysis/script.py", "print(1)\n")]}

    with pytest.raises(ReportingError) as raised:
        await ReportingCodeGenerationRunner(agent=FakeAgent(action)).generate(
            "analysis/script.py", {}, patch
        )

    assert raised.value.code == "report_code_generation_tool_arguments_invalid"
    assert mutated is False
    assert raised.value.details == {"path": "analysis/script.py"}
