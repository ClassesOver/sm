# Native Free-Form Code Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore `write_script` and `execute_code` as native Responses API free-form custom tools, preserve JSON function tools for all structured operations, and prove the mixed protocol through unit tests and one traced Reporting CLI run.

**Architecture:** Keep Agno's `Agent.arun` tool loop and translate only at the `ReportingCodeOpenAIResponses` wire boundary. Provider `custom_tool_call` items become synthetic Agno function calls for execution, while their immutable provider metadata drives replay as `custom_tool_call` and `custom_tool_call_output`; function calls continue through Agno unchanged. Any request containing a custom tool uses `tool_choice="auto"`, and assistant-text pseudo calls remain non-executable protocol errors.

**Tech Stack:** Python 3.12, Agno 3.0.9 `OpenAIResponses`, OpenAI Responses API, Pydantic, Loguru, pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-coding-agent-codemode-enhance-design.md`

## Global Constraints

- `write_script` and `execute_code` are native Responses API custom tools with Lark grammar exactly `start: SOURCE\nSOURCE: /[\\s\\S]+/`; they never fall back to JSON function tools.
- `run_script`, `submit_script`, `view_image`, Knowledge, and LSP remain JSON function tools.
- If the formatted request contains any custom tool, force `tool_choice="auto"`; only function-only requests may preserve a provider-supported explicit function choice.
- Always set `parallel_tool_calls=false`; accept at most one actionable structured call per provider response.
- Execute only structured provider calls. ASCII DSML, full-width DSML, and `execute_code`/`write_script` Markdown fences in assistant text return `report_code_custom_tool_protocol_error` with `details={"retryable": false}`.
- The first version is non-streaming. A request containing either free-form tool must fail before provider invocation if a streaming path is selected.
- Do not add JSON compatibility, assistant-text parsing, temporary Workspaces, recovery state, a custom model loop, or provider fallback.
- Keep the existing task-bound formal Workspace and Agno `Function` execution path; application logging continues through Loguru.
- Preserve unrelated dirty-worktree edits. In particular, patch `protocol.py` and its tests surgically; do not restore either file wholesale from `HEAD`.
- Semantic business validation remains a soft warning. Protocol identity, source shape, execution, and file identity failures remain technical failures.
- Do not repeat the full test suite. Run each task's focused tests, then one affected-test set and one real CLI E2E.
- DashScope Token Plan is enabled because `deepseek-v4-flash-0731` and `qwen3.8-flash` passed the real custom-tool round trip. vLLM remains disabled until an equivalent endpoint-specific probe passes.

## File Map

- Modify `smart_reporting/reporting/code_agent/protocol.py`: declare the two grammar custom tools, enforce request selection rules, bridge custom calls into Agno, and replay custom outputs with strict identity validation.
- Modify `smart_reporting/reporting/code_agent/__init__.py`: export the immutable free-form tool-to-argument mapping used by tests and callers.
- Modify `smart_reporting/reporting/agent.py`: describe `write_script` and `execute_code` as raw custom input, without JSON argument wording.
- Modify `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py`: cover request wire shape, response/replay validation, mixed custom/function execution, formal Workspace persistence, and visual repair.
- Verify `smart_reporting/reporting/tests/test_reporting_v1_workflows.py`: retain the already implemented no-submission and protocol-failure retry boundaries as regression coverage.
- Verify `AGENTS.md`: retain the committed DashScope/vLLM capability facts; no implementation-time edit is expected.

---

### Task 1: Native Custom Tool Request Contract

**Files:**
- Modify: `smart_reporting/reporting/code_agent/protocol.py:1-330`
- Modify: `smart_reporting/reporting/code_agent/__init__.py:1-20`
- Modify: `smart_reporting/reporting/agent.py:2890-2945`
- Test: `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py:380-520`

**Interfaces:**
- Consumes: Agno `Function` definitions named `write_script`, `execute_code`, and the existing structured tools.
- Produces: `FREEFORM_TOOL_ARGUMENTS: Mapping[str, str]`, grammar custom tool dictionaries, `parallel_tool_calls=False`, and provider-safe `tool_choice`.

- [ ] **Step 1: Replace the function-only request assertions with failing native-custom tests**

Restore request tests without reverting the later textual-marker cases. The core assertions are:

```python
def test_mixed_protocol_formats_only_large_text_tools_as_custom() -> None:
    model = _code_responses_model()
    tools = model._format_tool_params(
        [],
        [_function("read_script"), _function("write_script"), _function("execute_code")],
    )

    assert tools[0]["type"] == "function"
    assert tools[1] == {
        "type": "custom",
        "name": "write_script",
        "description": "write_script",
        "format": {
            "type": "grammar",
            "syntax": "lark",
            "definition": "start: SOURCE\nSOURCE: /[\\s\\S]+/",
        },
    }
    assert tools[2]["type"] == "custom"


def test_request_with_custom_tool_forces_auto_choice() -> None:
    params = _code_responses_model().get_request_params(
        messages=[Message(role="user", content="write")],
        tools=[_function("write_script"), _function("run_script")],
        tool_choice={"type": "custom", "name": "write_script"},
    )

    assert params["parallel_tool_calls"] is False
    assert params["tool_choice"] == "auto"


def test_function_only_request_preserves_explicit_choice() -> None:
    choice = {"type": "function", "name": "run_script"}
    params = _code_responses_model().get_request_params(
        messages=[Message(role="user", content="run")],
        tools=[_function("run_script"), _function("submit_script")],
        tool_choice=choice,
    )

    assert params["tool_choice"] == choice
```

Update the visualization single-visible-tool case to assert `"auto"` when that tool is `write_script`, and add a function-only case asserting the named Responses function choice remains permitted. Add a factory assertion that `_INTERACTIVE_CODE_INSTRUCTIONS` says custom input is raw source/cell text and does not describe `source`/`code` JSON parameters.

- [ ] **Step 2: Run the request-contract tests and verify RED**

Run:

```bash
.venv/bin/pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py \
  -k 'mixed_protocol_formats or request_with_custom or function_only_request or visualization_single_tool_choice or creates_fresh_agent'
```

Expected: custom wire-shape assertions fail because both tools are currently formatted as functions; the custom request retains an invalid named choice; the interactive instructions still describe JSON arguments.

- [ ] **Step 3: Implement the immutable custom-tool declaration and export**

Restore the required imports and constants in `protocol.py`:

```python
from collections.abc import AsyncIterator, Iterator, Mapping
from types import MappingProxyType

FREEFORM_TOOL_ARGUMENTS: Mapping[str, str] = MappingProxyType(
    {"write_script": "source", "execute_code": "code"}
)
_FREEFORM_TOOL_GRAMMAR = "start: SOURCE\nSOURCE: /[\\s\\S]+/"
_STREAMING_UNSUPPORTED = "report_code_streaming_unsupported"
```

Add the thin Agno formatting override:

```python
def _format_tool_params(self, messages: list[Message], tools: Any = None) -> list[dict[str, Any]]:
    formatted = super()._format_tool_params(messages, tools)
    result: list[dict[str, Any]] = []
    for tool in formatted:
        name = str(tool.get("name") or "")
        if name not in FREEFORM_TOOL_ARGUMENTS:
            result.append(tool)
            continue
        result.append(
            {
                "type": "custom",
                "name": name,
                "description": str(tool.get("description") or name),
                "format": {
                    "type": "grammar",
                    "syntax": "lark",
                    "definition": _FREEFORM_TOOL_GRAMMAR,
                },
            }
        )
    return result
```

After `super().get_request_params(...)`, inspect `params["tools"]`, not the unformatted input list:

```python
params["parallel_tool_calls"] = False
formatted_tools = params.get("tools") or ()
if any(tool.get("type") == "custom" for tool in formatted_tools):
    params["tool_choice"] = "auto"
elif tools and tool_choice is None:
    params["tool_choice"] = "auto"
```

In `phase_filtered_model_call`, set a named choice only for a sole non-free-form function tool. Use `"auto"` for a sole `write_script` or `execute_code`, because DashScope rejects named custom choices. Re-export the mapping from `code_agent/__init__.py`. Restore the instruction text exactly to:

```python
"write_script 与 execute_code 的 custom input 只包含原始源码或 cell 文本，不得添加 JSON 包装或说明。"
```

- [ ] **Step 4: Reject streaming before provider invocation**

Restore these adapter methods and keep ordinary function-only streaming delegated to Agno:

```python
@staticmethod
def _freeform_tool_requested(tools: Any) -> bool:
    return bool(tools) and any(
        report_model_tool_name(tool) in FREEFORM_TOOL_ARGUMENTS for tool in tools
    )

def _reject_streaming_freeform_tool(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    tools = kwargs.get("tools", args[2] if len(args) > 2 else None)
    if self._freeform_tool_requested(tools):
        raise ReportingError(
            _STREAMING_UNSUPPORTED,
            "Coding Agent free-form custom 工具仅支持非流式响应。",
        )
```

`invoke_stream` and `ainvoke_stream` call this guard, then delegate to `super()` only when it passes.

- [ ] **Step 5: Run the request-contract tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py \
  -k 'streaming or mixed_protocol_formats or request_with_custom or function_only_request or visualization_single_tool_choice or creates_fresh_agent'
```

Expected: all selected tests pass; no provider client is called by the free-form streaming rejection case.

- [ ] **Step 6: Commit the request contract**

```bash
git add smart_reporting/reporting/code_agent/protocol.py \
  smart_reporting/reporting/code_agent/__init__.py \
  smart_reporting/reporting/agent.py \
  smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py
git commit -m "fix: restore native free-form code tools"
```

### Task 2: Strict Custom Call and Output Bridge

**Files:**
- Modify: `smart_reporting/reporting/code_agent/protocol.py:205-520`
- Test: `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py:390-560`

**Interfaces:**
- Consumes: provider `custom_tool_call{id, call_id, name, input}` and Agno assistant/tool `Message` objects.
- Produces: synthetic Agno function calls with `provider_data={"reporting_wire_type": "custom", "raw_input": str}`, then wire-level `custom_tool_call` and `custom_tool_call_output` replay.

- [ ] **Step 1: Restore and extend failing custom round-trip tests**

Add tests for both complete replay modes:

```python
def test_custom_call_round_trip_uses_custom_output() -> None:
    model = _code_responses_model()
    parsed = model._parse_provider_response(_custom_response("execute_code", "print('ok')"))
    call = parsed.tool_calls[0]

    assert json.loads(call["function"]["arguments"]) == {"code": "print('ok')"}
    assert call["provider_data"] == {
        "reporting_wire_type": "custom",
        "raw_input": "print('ok')",
    }
    replay = model._format_messages(_assistant_and_result_messages(call, {"ok": True}))
    assert [item["type"] for item in replay[-2:]] == [
        "custom_tool_call",
        "custom_tool_call_output",
    ]


def test_custom_output_stays_custom_with_previous_response_id() -> None:
    model = ReportingCodeOpenAIResponses(
        id="gpt-5-test",
        api_key="test-key",
        base_url="http://localhost",
        store=True,
    )
    call = model._parse_provider_response(
        _custom_response("execute_code", "print('ok')")
    ).tool_calls[0]
    messages = _assistant_and_result_messages(call, {"ok": True})
    messages[0].provider_data = {"response_id": "resp-previous"}

    assert model._format_messages(messages) == [
        {
            "type": "custom_tool_call_output",
            "call_id": "call-1",
            "output": '{"ok":true}',
        }
    ]
```

Parameterize stable rejection tests for unknown names, empty input, missing `id`, missing `call_id`, duplicate call identity across history, forged custom metadata, decoded argument mismatch, wrong result call ID, wrong tool name, a free-form-named result attached to a function call, duplicate result, missing result, and more than one actionable custom/function item. Each case must assert `report_code_custom_tool_protocol_error` and `details == {"retryable": False}`. Keep and run the existing ASCII DSML, full-width DSML, Markdown fence, and plain assistant text tests unchanged.

- [ ] **Step 2: Run bridge tests and verify RED**

Run:

```bash
.venv/bin/pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py \
  -k 'custom_call_round_trip or custom_output_stays_custom or custom_replay or custom_protocol or textual_tool_call or multiple_actionable'
```

Expected: structured custom calls are currently rejected before Agno execution, replay is emitted as `function_call_output`, and strict replay cases do not reach the intended validation branches.

- [ ] **Step 3: Translate structured custom calls into Agno calls**

Restore `normalize_tool_messages` and `reformat_tool_call_ids` imports. Add the identity and translation helpers while retaining `_contains_textual_tool_marker` and its expanded marker set:

```python
def _required_id(value: Any, field: str) -> str:
    identity = _field(value, field)
    if not isinstance(identity, str) or not identity:
        raise _custom_protocol_error("Coding Agent custom 工具调用缺少身份。")
    return identity


def _synthetic_custom_call(item: Any) -> dict[str, Any]:
    name = _field(item, "name")
    raw_input = _field(item, "input")
    if name not in FREEFORM_TOOL_ARGUMENTS or not isinstance(raw_input, str) or not raw_input:
        raise _custom_protocol_error("Coding Agent custom 工具调用无效。")
    item_id = _required_id(item, "id")
    call_id = _required_id(item, "call_id")
    return {
        "id": item_id,
        "call_id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(
                {FREEFORM_TOOL_ARGUMENTS[name]: raw_input},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
        "provider_data": {"reporting_wire_type": "custom", "raw_input": raw_input},
    }
```

In `_parse_provider_response`, collect both `custom_tool_call` and `function_call` as actionable. Reject more than one. Only run textual-marker detection when there is no actionable structured call. Delegate ordinary responses to Agno; for one custom call replace `parsed.tool_calls` with the synthetic call and set `parsed.extra["tool_call_ids"]` to its `call_id`.

- [ ] **Step 4: Validate metadata and replay the original wire type**

Implement `_validated_custom_replay_call(call) -> dict[str, Any] | None` with these exact checks: metadata marker equals `custom`; name belongs to `FREEFORM_TOOL_ARGUMENTS`; `raw_input` is non-empty text; `id` and `call_id` are present; JSON-decoded Agno arguments equal `{FREEFORM_TOOL_ARGUMENTS[name]: raw_input}`.

Override `_format_messages` around Agno's formatter:

```python
normalized_messages = reformat_tool_call_ids(
    normalize_tool_messages(messages), provider="openai_responses"
)
original_calls = [call for message in messages for call in message.tool_calls or ()]
normalized_calls = [call for message in normalized_messages for call in message.tool_calls or ()]
if len(original_calls) != len(normalized_calls):
    raise _custom_protocol_error("Coding Agent 工具重放调用数量不一致。")
```

Build a map from every normalized `id`/`call_id` to validated custom metadata, rejecting an identity already owned by another call. Before formatting, require every tool result to match a known call, every custom result's name to match, every function result named `write_script`/`execute_code` to be rejected as a type mismatch, and every custom call to have exactly one result. Then call `super()._format_messages(messages, compress_tool_results, tools)` and replace only matched items:

```python
if item["type"] == "function_call":
    formatted[index] = {
        "type": "custom_tool_call",
        "id": custom["id"],
        "call_id": custom["call_id"],
        "name": custom["name"],
        "input": custom["raw_input"],
        "status": "completed",
    }
else:
    formatted[index] = {
        "type": "custom_tool_call_output",
        "call_id": custom["call_id"],
        "output": item["output"],
    }
```

Leave unrelated function calls and `function_call_output` items unchanged. The same metadata map must work when Agno resends full history and when reasoning/store mode sends only output after `previous_response_id`.

- [ ] **Step 5: Run bridge tests and verify GREEN**

Run the Step 2 command.

Expected: all selected tests pass; plain assistant text remains text, while all textual pseudo-call variants fail without invoking a tool.

- [ ] **Step 6: Commit the bidirectional bridge**

```bash
git add smart_reporting/reporting/code_agent/protocol.py \
  smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py
git commit -m "fix: bridge responses custom tool calls"
```

### Task 3: Mixed-Protocol Regression and Real CLI Acceptance

**Files:**
- Modify: `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py:1180-1390`
- Verify: `smart_reporting/reporting/tests/test_reporting_v1_workflows.py`
- Verify: `smart_reporting/reporting/tests/test_reporting_host_workspace.py`
- Verify: `smart_reporting/reporting/host_workspace.py`
- Verify: `smart_reporting/reporting/tools/workspace_adapter.py`

**Interfaces:**
- Consumes: Tasks 1-2 wire adapter, task-bound `ReportingCodeModeToolkit`, existing no-retry Workflow classification, and the formal session Workspace.
- Produces: one deterministic mocked mixed-protocol loop and one real traced DashScope CLI run that writes, runs, and submits a script from the formal Workspace.

- [ ] **Step 1: Make the mocked end-to-end loop require both wire types**

Allow `_custom_response` to receive an index so each item and call identity is unique:

```python
def _custom_response(name: str, raw_input: str, index: int = 1) -> Response:
    return Response.model_validate(
        {
            "id": f"resp-{index}",
            "created_at": 0,
            "model": "test-model",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "id": f"item-{index}",
                    "call_id": f"call-{index}",
                    "name": name,
                    "input": raw_input,
                    "type": "custom_tool_call",
                }
            ],
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": [],
        }
    )
```

Change the analysis loop to the following sequence:

```python
responses = [
    _custom_response("write_script", "if True print('broken')\n", 1),
    _function_response(2, "run_script", {}),
    _custom_response("execute_code", "print('probe')", 3),
    _custom_response("write_script", SOURCE, 4),
    _function_response(5, "lsp_diagnostics", {}),
    _function_response(6, "search_knowledge", {"query": "脚本规范"}),
    _function_response(7, "run_script", {}),
    _function_response(8, "submit_script", {}),
]
```

Assert the final Workspace script equals `SOURCE`; request tools include both `custom` and `function`; `write_script` and `execute_code` never appear as functions; replay types include both `custom_tool_call_output` and `function_call_output`; and the task kernel shuts down once. Convert both `write_script` responses in the visual repair loop back to custom responses and keep `view_image`, `run_script`, and `submit_script` as functions.

- [ ] **Step 2: Run the mixed-loop tests and verify RED**

Run:

```bash
.venv/bin/pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py \
  -k 'end_to_end_responses_loop or visual_repair_end_to_end'
```

Expected: FAIL when the new `execute_code` custom call reaches the fake runtime, because the fixture does not yet implement `Runtime.execute`; the request/replay assertions may also expose any incomplete Task 1-2 bridge behavior.

- [ ] **Step 3: Complete the mocked mixed loop and verify GREEN**

Finish only the fixture/assertion changes from Step 1; do not add a second model loop or call toolkit entrypoints directly from the fake client. Add the minimal interactive-cell method to the analysis test runtime:

```python
async def execute(self, session_id, received, code, **kwargs):
    assert session_id == "code-task-1"
    assert received is workspace
    assert code == "print('probe')"
    assert kwargs == {"matplotlib_agg": False}
    return SimpleNamespace(status="ok", stdout="probe\n", stderr="", traceback=None)
```

Update the request count from seven to eight.

Run the Step 2 command.

Expected: both tests pass and prove that Agno executed raw custom input against the formal Workspace before structured run/view/submit calls.

- [ ] **Step 4: Commit the mixed-protocol regression**

```bash
git add smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py
git commit -m "test: cover mixed code tool protocol"
```

- [ ] **Step 5: Run the affected test set once**

```bash
.venv/bin/pytest -q \
  smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py \
  smart_reporting/reporting/tests/test_reporting_v1_workflows.py \
  smart_reporting/reporting/tests/test_reporting_host_workspace.py
```

Expected: all tests pass. This is the only combined test run; do not run the repository-wide suite afterward.

- [ ] **Step 6: Run static checks on touched Python files**

```bash
.venv/bin/ruff check \
  smart_reporting/reporting/agent.py \
  smart_reporting/reporting/code_agent/__init__.py \
  smart_reporting/reporting/code_agent/protocol.py \
  smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py
git diff --check HEAD~3..HEAD
```

Expected: both commands exit zero.

- [ ] **Step 7: Run one real traced Reporting CLI E2E**

Confirm without printing credentials that `.env` resolves the host PostgreSQL endpoint on port `15432`. Then execute exactly one CLI run and capture logs outside the repository:

```bash
AGENT_ENV_FILE=.env AGENT_TRACING_ENABLED=true timeout 1800 \
  .venv/bin/python -m smart_reporting.reporting.cli \
  > /tmp/reporting-cli-freeform-e2e.log 2>&1 <<'EOF'
2025年医院收入趋势分析报告，仅生成一个章节。
/run
a
EOF
```

Do not retry the whole CLI run automatically. On failure, inspect this run's log, trace ID, and retained session Workspace first; fix a proven implementation defect and rerun only with an explicit note that the first acceptance attempt failed.

- [ ] **Step 8: Verify the real run's protocol, Workspace, and trace evidence**

Inspect `/tmp/reporting-cli-freeform-e2e.log` with secret-safe searches. Record the run ID, session ID, trace ID, and formal Workspace path, then verify:

```text
write_script (custom_tool_call)
-> target script exists in the session's formal Workspace
-> run_script (function_call) succeeds
-> submit_script (function_call) returns the signed source/output receipt
```

The provider request must show `type=custom` with grammar for `write_script`/`execute_code`, `tool_choice=auto`, and `parallel_tool_calls=false`. The continuation must contain `custom_tool_call_output`. Tracing must contain real Coding Agent/model/tool spans, not only outer Workflow spans. The final CLI result must be `completed`, and no log or summary may expose API keys, database passwords, or full authorization headers.

- [ ] **Step 9: Inspect final scope**

```bash
git status --short
git log --oneline -5
git show --stat --oneline HEAD~3..HEAD
```

Expected: the three implementation commits touch only the files listed in Tasks 1-3. Pre-existing `host_workspace.py`, `workspace_adapter.py`, their tests, and `debug_trace_plugin.py` changes remain present and unmodified unless they were already committed by their owner.
