"""PPTX Agno 原生工具循环的脚本模型测试边界。"""
from dataclasses import dataclass, field
from typing import Any, Iterator, AsyncIterator
from agno.models.base import Model
from agno.models.response import ModelResponse

@dataclass
class ScriptedModel(Model):
    responses: list[ModelResponse] = field(default_factory=list)
    seen: list[list[Any]] = field(default_factory=list)
    expected_tool_text: str | None = None

    def invoke(self, *args, **kwargs):
        self.seen.append(list(kwargs.get("messages", args[0] if args else [])))
        if self.expected_tool_text and len(self.responses) == 1:
            assert any(
                m.role == "tool" and self.expected_tool_text in str(m.content)
                for m in self.seen[-1]
            )
        return self.responses.pop(0)

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response, **kwargs):
        return response
