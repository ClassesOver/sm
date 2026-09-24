"""free-form 局部编辑必须精确匹配且原子提交。"""

import hashlib
import json
from unittest.mock import AsyncMock

import pytest
from agno.tools.function import FunctionCall
from lark import Lark, UnexpectedInput

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_code_input import (
    anyio_backend,  # noqa: F401
    binding,  # noqa: F401
    toolkit,  # noqa: F401
    workspace,  # noqa: F401
)
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    _assistant_and_result_messages,
    _batch_response,
    _code_responses_model,
    _custom_response,
    _function_response,
    _receipt,
)
from smart_reporting.workspace import WorkspaceError


def edit_patch(source, old, new):
    return multi_edit_patch(source, [(old, new)])


@pytest.mark.parametrize("case,reason", [
    ("bad_sha", "missing_envelope"),
    ("missing_blocks", "no_valid_blocks"),
    ("trailing", "trailing_text"),
    ("oversized", "oversized_patch"),
    ("wrapped", "missing_envelope"),
])
def test_parse_edit_patch_invalid_reports_bounded_reason(case, reason):
    """candidate-15 观测缺口：edit_script invalid 失败必须带可归因的 reason。"""
    from smart_reporting.reporting.code_agent.edit_patch import parse_edit_patch

    source = "# keep\nvalue = 1\n"
    patch = edit_patch(source, "value = 1", "value = 2")
    if case == "bad_sha":
        patch = patch.replace(hashlib.sha256(source.encode()).hexdigest(), "not-a-sha")
    elif case == "missing_blocks":
        patch = (
            "*** Begin Edit\n*** SHA256: " + hashlib.sha256(source.encode()).hexdigest()
            + "\nrandom text without edit markers\n*** End Edit\n"
        )
    elif case == "trailing":
        patch += "\n解释"
    elif case == "oversized":
        patch = edit_patch(source, "value = 1", "x" * (2 * 64 * 1024 + 512))
    elif case == "wrapped":
        patch = json.dumps({"data": patch})
    with pytest.raises(ReportingError) as caught:
        parse_edit_patch(patch, 64 * 1024)
    assert caught.value.code == "report_code_script_edit_invalid"
    assert caught.value.details.get("reason") == reason
    assert caught.value.details.get("nextTools") == ["read_script", "edit_script"]
    # patch 原文不得进入 details；oversized 分支只报字节数身份。
    assert "value = 2" not in json.dumps(caught.value.details, ensure_ascii=False)
    if case == "oversized":
        assert caught.value.details.get("actualBytes") == len(patch.encode("utf-8"))
        assert caught.value.details.get("limitBytes") == 64 * 1024


def test_parse_edit_patch_invalid_message_contains_copyable_template():
    """candidate-27/28 早停族：失败消息必须附可逐行复制的信封模板。"""
    from smart_reporting.reporting.code_agent.edit_patch import parse_edit_patch

    source = "# keep\nvalue = 1\n"
    digest = hashlib.sha256(source.encode()).hexdigest()
    patch = (
        "*** Begin Edit\n*** SHA256: " + digest
        + "\n*** Update File: charts.py\n- value = 1\n+ value = 2\n*** End Edit\n"
    )
    with pytest.raises(ReportingError) as caught:
        parse_edit_patch(patch, 64 * 1024)
    assert caught.value.details.get("reason") == "no_valid_blocks"
    message = caught.value.message
    assert len(message) <= 512
    for marker in (
        "*** Begin Edit\\n*** SHA256: ",
        "<<<<<<< SEARCH\\n",
        "\\n=======\\n",
        "\\n>>>>>>> REPLACE\\n",
        "*** End Edit",
    ):
        assert marker in message


def multi_edit_patch(source, edits):
    digest = hashlib.sha256(source.encode()).hexdigest()
    return f"*** Begin Edit\n*** SHA256: {digest}\n" + "".join(
        f"<<<<<<< SEARCH\n{old}\n=======\n{new}\n>>>>>>> REPLACE\n"
        for old, new in edits
    ) + "*** End Edit"


@pytest.mark.anyio
@pytest.mark.parametrize("source,edits,expected", [
    ("# keep\na = 1\nb = 2\nprint(a, b)\n",
     [("b = 2", "b = 20"), ("a = 1", "a = 10\nc = 3")],
     "# keep\na = 10\nc = 3\nb = 20\nprint(a, b)\n"),
    ("# keep\na = 1\nb = 2\nprint(a, b)\n",
     [("a = 1", "b = 2"), ("b = 2", "a = 1")],
     "# keep\nb = 2\na = 1\nprint(a, b)\n"),
    ("# keep\ndef helper():\n    return 1\n\nvalue = 2\nprint(value)\n",
     [("def helper():\n    return 1\n\n", ""),
      ("print(value)", "def helper():\n    return 1\n\nprint(value)")],
     "# keep\nvalue = 2\ndef helper():\n    return 1\n\nprint(value)\n"),
    ("# keep\r\na = 1\r\nb = 2", [("a = 1", "a = 10"), ("b = 2", "b = 20")],
     "# keep\r\na = 10\r\nb = 20"),
])
async def test_multi_edit_uses_original_snapshot_and_commits_once(toolkit, script, source, edits, expected):  # noqa: F811
    script["source"] = source
    patch = multi_edit_patch(source, edits)
    spec = next(t for t in _code_responses_model()._format_tool_params(
        [], toolkit.tool_functions,
    ) if t["name"] == "edit_script")
    Lark(spec["format"]["definition"]).parse(patch)
    result = await toolkit.edit_script(patch)
    assert result["ok"] is True
    assert result["replacedOccurrences"] == len(edits)
    assert result["sourceSha256"] == result["sha256"]
    assert result["sourceBytes"] == result["size"]
    assert result["changeSummary"] == {
        "kind": "edit", "replacedOccurrences": len(edits),
    }
    assert script["source"] == expected
    assert script["writes"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize("edits,code", [
    ([("value = 1", "value = 2"), ("missing", "value = 3")], "report_code_script_edit_not_found"),
    ([("value = 1", "value = 2"), ("value = 2", "value = 3")], "report_code_script_edit_not_found"),
    ([("value = 1", "value = 2"), ("value = 1\nprint(value)", "pass")], "report_code_script_edit_overlap"),
    ([("value = 1", "value = 2"), ("value = 1", "value = 3")], "report_code_script_edit_overlap"),
    ([("# 保留中文\nvalue = 1\n", "x = 3\n"), ("print(value)\n", "print(x)\n")], "report_code_script_edit_not_local"),
])
async def test_multi_edit_failure_is_atomic(toolkit, script, edits, code):  # noqa: F811
    source = script["source"]
    receipt = _receipt()
    toolkit.binding.execution_receipt = toolkit.submitted_receipt = receipt
    result = await toolkit.edit_script(multi_edit_patch(source, edits))
    assert result["code"] == code
    assert script["source"] == source
    assert script["writes"] == 0
    assert toolkit.binding.execution_receipt is receipt
    assert toolkit.submitted_receipt is receipt


@pytest.mark.anyio
async def test_overlapping_text_occurrences_are_ambiguous(toolkit, script):  # noqa: F811
    script["source"] = "# keep\nvalue = 'aaa'\n"
    result = await toolkit.edit_script(edit_patch(script["source"], "aa", "bb"))
    assert result["code"] == "report_code_script_edit_ambiguous"
    assert script["writes"] == 0


@pytest.fixture
def script(toolkit, monkeypatch):  # noqa: F811
    # 只替换 Workspace I/O；生产匹配、源码校验、SHA/CAS 和回执失效逻辑照常运行。
    state = {"source": "# 保留中文\nvalue = 1\nprint(value)\n", "writes": 0}

    async def identity(*args, **kwargs):
        return {"sha256": hashlib.sha256(state["source"].encode()).hexdigest(),
                "path": toolkit.context.script_path, "size": len(state["source"].encode())}

    async def read(*args, **kwargs):
        return state["source"].encode()

    async def write(task_id, path, content, *, overwrite, expected_sha256):
        assert path == toolkit.context.script_path
        if expected_sha256 != (await identity())["sha256"]:
            raise WorkspaceError("conflict")
        state["source"] = content
        state["writes"] += 1

    monkeypatch.setattr(toolkit.workspace, "ahash_file", identity)
    monkeypatch.setattr(toolkit.workspace, "read_limited_regular_file", read)
    monkeypatch.setattr(toolkit.workspace, "awrite_text", write)
    return state


def test_edit_wire_grammar_and_replay(toolkit):  # noqa: F811
    model = _code_responses_model()
    params = model.get_request_params(messages=[], tools=toolkit.tool_functions)
    spec = next(t for t in params["tools"] if t["name"] == "edit_script")
    assert spec["type"] == "custom"
    assert "parameters" not in spec
    assert params["tool_choice"] == "auto"
    patch = edit_patch("value = 1\n", "value = 1", "value = 2")
    parser = Lark(spec["format"]["definition"])
    parser.parse(patch)
    for invalid in (json.dumps({"patch": patch}), f"```\n{patch}\n```", patch + "\n解释"):
        with pytest.raises(UnexpectedInput):
            parser.parse(invalid)
    call = model._parse_provider_response(_custom_response("edit_script", patch)).tool_calls[0]
    assert json.loads(call["function"]["arguments"]) == {"patch": patch}
    replay = model._format_messages(_assistant_and_result_messages(call, {"ok": True}))
    assert replay[-2]["type"] == "custom_tool_call"
    assert replay[-2]["input"] == patch
    assert replay[-1]["type"] == "custom_tool_call_output"


def test_edit_mixed_batch_replays_native_custom_and_function_calls(toolkit):  # noqa: F811
    model = _code_responses_model()
    model.get_request_params(messages=[], tools=toolkit.tool_functions)
    patch = edit_patch("value = 1\n", "value = 1", "value = 2")
    response = _batch_response(
        _custom_response("edit_script", patch), _function_response(2, "run_script", {}),
    )
    parsed = model._parse_provider_response(response)
    assert [c["function"]["name"] for c in parsed.tool_calls] == ["edit_script", "run_script"]
    messages = []
    for call in parsed.tool_calls:
        messages.extend(_assistant_and_result_messages(call, {"ok": True}))
    replay = model._format_messages(messages)
    assert [item["type"] for item in replay] == [
        "custom_tool_call", "custom_tool_call_output", "function_call", "function_call_output",
    ]


def test_edit_cannot_downgrade_to_json_function_call(toolkit):  # noqa: F811
    model = _code_responses_model()
    model.get_request_params(messages=[], tools=toolkit.tool_functions)
    with pytest.raises(ReportingError):
        model._parse_provider_response(_function_response(1, "edit_script", {"patch": "ignored"}))


@pytest.mark.anyio
@pytest.mark.parametrize("source,old,new,expected", [
    ("# 保留中文\nvalue = 1\nprint(value)\n", "value = 1", "value = 2",
     "# 保留中文\nvalue = 2\nprint(value)\n"),
    ("# keep\r\na = 1\r\nb = 2\r\n", "a = 1\r\nb = 2", "a = 3\r\nb = 4",
     "# keep\r\na = 3\r\nb = 4\r\n"),
    ("# keep\nvalue = 1", "value = 1", "value = 2", "# keep\nvalue = 2"),
    ("# keep\nvalue = 1\nprint(2)\n", "value = 1\n", "", "# keep\nprint(2)\n"),
])
async def test_edit_changes_only_exact_block(toolkit, script, source, old, new, expected):  # noqa: F811
    script["source"] = source
    patch = edit_patch(source, old, new)
    spec = next(t for t in _code_responses_model()._format_tool_params(
        [], toolkit.tool_functions,
    ) if t["name"] == "edit_script")
    Lark(spec["format"]["definition"]).parse(patch)
    toolkit.binding.execution_receipt = _receipt()
    toolkit.submitted_receipt = _receipt()
    result = await toolkit.edit_script(patch)
    assert result["ok"] is True
    assert script["source"] == expected
    assert script["writes"] == 1
    assert toolkit.binding.execution_receipt is None
    assert toolkit.submitted_receipt is None


@pytest.mark.anyio
@pytest.mark.parametrize("case,code", [
    ("missing", "report_code_script_edit_not_found"),
    ("ambiguous", "report_code_script_edit_ambiguous"),
    ("stale", "report_code_script_edit_conflict"),
    ("whole", "report_code_script_edit_not_local"),
    ("whole_without_newline", "report_code_script_edit_not_local"),
    ("unchanged", "report_code_script_edit_unchanged"),
    ("empty", "report_code_script_edit_invalid"),
    ("wrapped", "report_code_script_edit_invalid"),
    ("two_blocks", "report_code_script_edit_invalid"),
    ("bad_sha", "report_code_script_edit_invalid"),
    ("trailing", "report_code_script_edit_invalid"),
    ("oversized", "report_code_script_edit_invalid"),
    ("path", "report_code_script_edit_invalid"),
])
async def test_rejected_edit_never_writes_or_invalidates_receipts(toolkit, script, case, code):  # noqa: F811
    if case == "ambiguous":
        script["source"] += "value = 1\n"
    source = script["source"]
    old = {"missing": "value=1", "whole": source, "whole_without_newline": source.rstrip(),
           "empty": ""}.get(case, "value = 1")
    patch = edit_patch(source, old, old if case == "unchanged" else "value = 2")
    if case == "stale":
        patch = edit_patch("old revision", old, "value = 2")
    elif case == "wrapped":
        patch = json.dumps({"data": patch})
    elif case == "two_blocks":
        patch += "\n" + patch
    elif case == "bad_sha":
        patch = patch.replace(hashlib.sha256(source.encode()).hexdigest(), "not-a-sha")
    elif case == "trailing":
        patch += "\n解释"
    elif case == "oversized":
        patch = edit_patch(source, old, "x" * (2 * toolkit.context.max_source_bytes + 256))
    elif case == "path":
        patch = patch.replace("<<<<<<< SEARCH", "*** File: other.py\n<<<<<<< SEARCH")
    receipt = _receipt()
    toolkit.binding.execution_receipt = toolkit.submitted_receipt = receipt
    result = await toolkit.edit_script(patch)
    assert result["code"] == code
    assert script["source"] == source
    assert script["writes"] == 0
    assert toolkit.binding.execution_receipt is receipt
    assert toolkit.submitted_receipt is receipt


@pytest.mark.anyio
async def test_edit_cas_conflict_leaves_concurrent_source_intact(toolkit, script, monkeypatch):  # noqa: F811
    async def conflict(*args, **kwargs):
        script["source"] = "# concurrent edit\nvalue = 3\n"
        raise WorkspaceError("conflict")
    monkeypatch.setattr(toolkit.workspace, "awrite_text", conflict)
    result = await toolkit.edit_script(edit_patch(script["source"], "value = 1", "value = 2"))
    assert result["code"] == "report_code_script_edit_conflict"
    assert script["source"] == "# concurrent edit\nvalue = 3\n"


@pytest.mark.anyio
async def test_edit_stale_sha_returns_current_and_expected_identity(toolkit, script):  # noqa: F811
    source = script["source"]
    patch = edit_patch("stale source", "value = 1", "value = 2")
    result = await toolkit.edit_script(patch)
    assert result["code"] == "report_code_script_edit_conflict"
    assert result["details"]["currentSha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert result["details"]["expectedSha256"] == hashlib.sha256(b"stale source").hexdigest()
    assert result["details"]["action"] == "read_script"


@pytest.mark.anyio
async def test_edit_hashes_the_same_snapshot_it_matches(toolkit, script, monkeypatch):  # noqa: F811
    original = script["source"]

    async def changed_read(*args, **kwargs):
        return (original + "# concurrent edit\n").encode()

    monkeypatch.setattr(toolkit.workspace, "read_limited_regular_file", changed_read)
    result = await toolkit.edit_script(edit_patch(original, "value = 1", "value = 2"))
    assert result["code"] == "report_code_script_edit_conflict"
    assert script["writes"] == 0


@pytest.mark.anyio
async def test_edit_first_custom_response_executes_through_agno(toolkit, script, monkeypatch):  # noqa: F811
    monkeypatch.setattr(toolkit, "refresh_delivery_state", AsyncMock())
    patch = edit_patch(script["source"], "value = 1", "value = 2")
    model = _code_responses_model()
    call = model._parse_provider_response(_custom_response("edit_script", patch)).tool_calls[0]
    function = next(t for t in toolkit.tool_functions if t.name == "edit_script")
    function.process_entrypoint()
    fc = FunctionCall(function=function, call_id=call["call_id"],
                      arguments=json.loads(call["function"]["arguments"]))
    assert await fc.aexecute()
    assert fc.result["ok"] is True
    assert script["source"] == "# 保留中文\nvalue = 2\nprint(value)\n"
    assert script["writes"] == 1


@pytest.mark.anyio
async def test_edit_provider_data_envelope_applies_once_and_replays_raw_patch(toolkit, script):  # noqa: F811
    # 真实故障形状：同一合法补丁被单层 data 信封包装，连续三次被拒绝。
    script["source"] = '# 保留\\n字面量\nfor d in dims:\n    print(d["name"])\n'
    patch = edit_patch(script["source"], "for d in dims:", "for d in [x[0] for x in dims]:")
    model = _code_responses_model()
    call = model._parse_provider_response(
        _custom_response("edit_script", json.dumps({"data": patch})),
    ).tool_calls[0]
    function = next(t for t in toolkit.tool_functions if t.name == "edit_script")
    function.process_entrypoint()
    fc = FunctionCall(function=function, call_id=call["call_id"],
                      arguments=json.loads(call["function"]["arguments"]))
    assert await fc.aexecute()
    assert fc.result["ok"] is True
    assert script["source"] == '# 保留\\n字面量\nfor d in [x[0] for x in dims]:\n    print(d["name"])\n'
    assert script["writes"] == 1
    replay = model._format_messages(_assistant_and_result_messages(call, fc.result))
    assert replay[-2]["type"] == "custom_tool_call"
    assert replay[-2]["input"] == patch
    assert replay[-1]["type"] == "custom_tool_call_output"
    assert replay[-1]["call_id"] == call["call_id"]


@pytest.mark.anyio
@pytest.mark.parametrize("case,code", [
    ("nested", "report_code_script_edit_invalid"),
    ("extra_key", "report_code_script_edit_invalid"),
    ("fenced", "report_code_script_edit_invalid"),
    ("literal_newlines", "report_code_script_edit_invalid"),
    ("stale", "report_code_script_edit_conflict"),
    ("ambiguous", "report_code_script_edit_ambiguous"),
    ("missing_second_block", "report_code_script_edit_not_found"),
    ("whole", "report_code_script_edit_not_local"),
])
async def test_edit_provider_envelope_keeps_patch_guards(toolkit, script, case, code):  # noqa: F811
    if case == "ambiguous":
        script["source"] += "value = 1\n"
    source = script["source"]
    edits = [(source if case == "whole" else "value = 1", "value = 2")]
    if case == "missing_second_block":
        edits.append(("missing", "value = 3"))
    patch = multi_edit_patch("stale" if case == "stale" else source, edits)
    if case == "nested":
        patch = json.dumps({"data": patch})
    elif case == "fenced":
        patch = f"```\n{patch}\n```"
    elif case == "literal_newlines":
        patch = patch.replace("\n", "\\n")
    envelope = {"data": patch}
    if case == "extra_key":
        envelope["path"] = "other.py"
    call = _code_responses_model()._parse_provider_response(
        _custom_response("edit_script", json.dumps(envelope)),
    ).tool_calls[0]
    receipt = _receipt()
    toolkit.binding.execution_receipt = toolkit.submitted_receipt = receipt
    result = await toolkit.edit_script(**json.loads(call["function"]["arguments"]))
    assert result["code"] == code
    if case == "missing_second_block":
        assert result["details"]["blockIndex"] == 2
    assert script["source"] == source
    assert script["writes"] == 0
    assert toolkit.binding.execution_receipt is receipt
    assert toolkit.submitted_receipt is receipt


@pytest.mark.anyio
async def test_failed_edit_keeps_repair_tools_available(toolkit, script):  # noqa: F811
    patch = edit_patch(script["source"], "missing text", "value = 2")
    function = next(t for t in toolkit.tool_functions if t.name == "edit_script")
    function.process_entrypoint()
    fc = FunctionCall(function=function, call_id="edit-failed", arguments={"patch": patch})
    assert await fc.aexecute()
    assert fc.result["code"] == "report_code_script_edit_not_found"
    assert toolkit.delivery_state()["nextTools"] == ["read_script", "edit_script", "run_script"]


@pytest.mark.anyio
async def test_edit_not_found_receipt_carries_bounded_anchor_context(toolkit, script):  # noqa: F811
    # 整块 SEARCH 不存在，但首行仍是源码锚点：回执附有界 excerpt，可直接重试。
    source = "# keep\nvalue = 1\nprint(value)\n"
    script["source"] = source
    result = await toolkit.edit_script(
        edit_patch(source, "value = 1\nprint(value)\nmissing", "value = 2")
    )
    assert result["code"] == "report_code_script_edit_not_found"
    details = result["details"]
    assert details["blockIndex"] == 1
    assert details["sourceSha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert details["sourceExcerpt"] == source
    assert details["sourceStartLine"] == 1
    assert details["sourceEndLine"] == 3
    assert details["errorLine"] == 2
    assert details["allowedEditRegion"] == {
        "path": toolkit.context.script_path, "startLine": 1, "endLine": 3,
    }
    assert "readRange" not in details
    assert details["nextTools"] == ["edit_script", "run_script"]
    assert script["writes"] == 0


@pytest.mark.anyio
async def test_edit_ambiguous_receipt_anchors_first_occurrence(toolkit, script):  # noqa: F811
    script["source"] = "# keep\nvalue = 1\nprint(value)\nvalue = 1\n"
    source = script["source"]
    result = await toolkit.edit_script(edit_patch(source, "value = 1", "value = 2"))
    assert result["code"] == "report_code_script_edit_ambiguous"
    details = result["details"]
    assert details["errorLine"] == 2
    assert details["sourceStartLine"] == 1
    assert details["sourceEndLine"] == 4
    assert details["sourceExcerpt"] == source
    assert details["sourceSha256"] == hashlib.sha256(source.encode()).hexdigest()


@pytest.mark.anyio
async def test_edit_failure_without_anchor_falls_back_to_full_read_range(toolkit, script):  # noqa: F811
    source = script["source"]
    result = await toolkit.edit_script(edit_patch(source, "value=1", "value = 2"))
    assert result["code"] == "report_code_script_edit_not_found"
    details = result["details"]
    assert "sourceExcerpt" not in details
    assert "sourceSha256" not in details
    assert details["readRange"] == {
        "path": toolkit.context.script_path, "startLine": 1, "endLine": 3,
    }
    assert details["nextTools"] == ["read_script", "edit_script"]
    assert script["writes"] == 0


@pytest.mark.anyio
async def test_edit_can_retry_directly_from_failure_receipt_without_read(toolkit, script):  # noqa: F811
    # 长修复循环压缩的关键路径：模型仅凭失败回执的 excerpt + sourceSha256
    # 修正 SEARCH 并直接重试，中间不需要再 read_script。
    source = "# keep\nvalue = 1\nprint(value)\n"
    script["source"] = source
    failed = await toolkit.edit_script(
        edit_patch(source, "value = 1\nprint(total)", "value = 2")
    )
    assert failed["code"] == "report_code_script_edit_not_found"
    details = failed["details"]
    assert details["sourceExcerpt"] == source
    assert details["sourceSha256"] == hashlib.sha256(source.encode()).hexdigest()

    retry = await toolkit.edit_script(
        edit_patch(details["sourceExcerpt"], "value = 1", "value = 2")
    )

    assert retry["ok"] is True
    assert script["source"] == "# keep\nvalue = 2\nprint(value)\n"
    assert script["writes"] == 1


@pytest.mark.anyio
async def test_edit_conflict_receipt_completes_read_range_and_keeps_anchor_excerpt(toolkit, script):  # noqa: F811
    source = script["source"]
    result = await toolkit.edit_script(edit_patch("stale source", "value = 1", "value = 2"))
    assert result["code"] == "report_code_script_edit_conflict"
    details = result["details"]
    assert details["currentSha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert details["expectedSha256"] == hashlib.sha256(b"stale source").hexdigest()
    assert details["action"] == "read_script"
    assert details["readRange"] == {
        "path": toolkit.context.script_path, "startLine": 1, "endLine": 3,
    }
    # SEARCH 首行仍命中当前源码：excerpt + sourceSha256 可支撑直接重试。
    assert details["sourceSha256"] == details["currentSha256"]
    assert details["sourceExcerpt"] == source
    assert details["errorLine"] == 2
    assert details["nextTools"] == ["read_script", "edit_script"]
    assert script["writes"] == 0
