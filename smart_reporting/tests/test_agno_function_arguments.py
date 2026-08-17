from __future__ import annotations

from agno.tools import Function
from agno.models.message import Message
from agno.models.openai import OpenAIChat

from smart_reporting.agno_function_arguments import (
    install_agno_function_argument_decoder,
    repair_function_call_arguments,
)


def _function() -> Function:
    return Function(
        name="create_files",
        parameters={
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["files"],
            "additionalProperties": False,
        },
        strict=True,
        entrypoint=lambda files: files,
    )


def test_function_arguments补齐已完成值后的容器结尾():
    raw = '{"files":[{"path":"report.py","content":"print(1)"}]'

    assert repair_function_call_arguments(raw) == raw + "}"


def test_function_arguments修复字符串中的非法转义和控制字符():
    raw = '{"files":[{"path":"report.py","content":"bad\\q\nline"}]}'

    repaired = repair_function_call_arguments(raw)

    assert repaired == '{"files":[{"path":"report.py","content":"bad\\\\q\\nline"}]}'


def test_function_arguments不修复未闭合字符串():
    raw = '{"files":[{"path":"report.py","content":"print(1)'

    assert repair_function_call_arguments(raw) is None


def test_agno解码器在公共入口恢复容器并保留原有functioncall():
    install_agno_function_argument_decoder()
    from agno.utils.tools import get_function_call

    call = get_function_call(
        name="create_files",
        arguments='{"files":[{"path":"report.py","content":"print(1)"}]',
        call_id="call-1",
        functions={"create_files": _function()},
    )

    assert call is not None
    assert call.error is None
    assert call.arguments == {
        "files": [{"path": "report.py", "content": "print(1)"}]
    }


def test_agno解码器对不可恢复参数保留失败关闭():
    install_agno_function_argument_decoder()
    from agno.utils.tools import get_function_call

    call = get_function_call(
        name="create_files",
        arguments='{"files":[{"path":"report.py","content":"print(1)',
        call_id="call-2",
        functions={"create_files": _function()},
    )

    assert call is not None
    assert call.error is not None
    assert call.arguments is None


def test_agno模型真实转换链恢复参数且不生成decode错误消息():
    install_agno_function_argument_decoder()
    model = OpenAIChat(id="test-model")
    messages = []
    assistant = Message(
        role="assistant",
        tool_calls=[
            {
                "id": "call-model",
                "type": "function",
                "function": {
                    "name": "create_files",
                    "arguments": '{"files":[{"path":"report.py","content":"print(1)"}]',
                },
            }
        ],
    )

    calls = model.get_function_calls_to_run(
        assistant,
        messages,
        functions={"create_files": _function()},
    )

    assert len(calls) == 1
    assert calls[0].arguments == {
        "files": [{"path": "report.py", "content": "print(1)"}]
    }
    assert messages == []
