"""Token cache dispatch must respect per-instance counting policies without network IO."""

from types import MethodType

import pytest
from agno.models.base import Model
from agno.models.message import Message
from agno.models.openai import OpenAIResponses

from smart_reporting import context_management as context


class LocalCountingModel(OpenAIResponses):
    count_tokens = Model.count_tokens


@pytest.mark.parametrize("bound", [False, True])
def test_instance_counter_override_bypasses_additive_cache(monkeypatch, bound):
    model = LocalCountingModel(id="offline-test", api_key="test")
    messages = [Message(role="user", content="payload")]
    tools = [{"type": "function", "name": "inspect"}]
    response_format = {"type": "json_object"}
    seen = []

    def count(messages_arg, tools_arg, format_arg):
        seen.append((messages_arg, tools_arg, format_arg))
        return 37

    if bound:
        model.count_tokens = MethodType(lambda self, *args: count(*args), model)
    else:
        model.count_tokens = count

    def forbidden_cache(*args, **kwargs):
        pytest.fail("Instance counter override must not invoke Agno's tokenizer/cache")

    monkeypatch.setattr(context, "_additive_token_count", forbidden_cache)
    assert context.TaskExecutionContextProjector._token_count(
        messages, model, tools, response_format
    ) == 37
    assert seen == [(messages, tools, response_format)]


def test_unmodified_base_counter_keeps_additive_cache(monkeypatch):
    model = LocalCountingModel(id="offline-test", api_key="test")
    messages = [Message(role="user", content="payload")]
    seen = []

    def cached(messages_arg, model_arg, tools_arg, format_arg):
        seen.append((messages_arg, model_arg, tools_arg, format_arg))
        return 17

    monkeypatch.setattr(context, "_additive_token_count", cached)
    assert context.TaskExecutionContextProjector._token_count(messages, model) == 17
    assert seen == [(messages, model, None, None)]
