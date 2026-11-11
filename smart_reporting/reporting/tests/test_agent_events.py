"""Agno 原生事件传递保持最终 RunOutput，观察者不能改变执行协议。"""

import pytest
from agno.run.agent import RunContentEvent, RunOutput, ToolCallCompletedEvent, ToolCallStartedEvent

from smart_reporting.reporting.agent_events import observe_agent_events, run_agent_with_events


@pytest.fixture
def anyio_backend():
    return 'asyncio'


class AgentFixture:
    def __init__(self):
        self.calls = []
        self.output = RunOutput(run_id='actual-final', content={'summary': '校验后的最终结构'})

    def arun(self, value, **kwargs):
        self.calls.append((value, kwargs))
        if kwargs['stream']:
            async def events():
                yield RunContentEvent(run_id='actual-final', content='逐字生成')
                yield ToolCallStartedEvent(tool=None)
                yield ToolCallCompletedEvent(tool=None)
                yield self.output
            return events()
        async def result():
            return self.output
        return result()


@pytest.mark.anyio
async def test_no_observer_preserves_original_nonstream_call():
    agent = AgentFixture()
    assert await run_agent_with_events(agent, 'input', session_id='session') is agent.output
    assert agent.calls == [('input', {'stream': False, 'session_id': 'session'})]


@pytest.mark.anyio
async def test_observer_receives_real_events_and_final_runoutput_is_preserved():
    agent, events = AgentFixture(), []
    with observe_agent_events(events.append):
        result = await run_agent_with_events(agent, 'input', user_id='user')
    assert result is agent.output
    assert len(events) == 3 and isinstance(events[0], RunContentEvent)
    assert events[0].content == '逐字生成'
    assert isinstance(events[1], ToolCallStartedEvent) and isinstance(events[2], ToolCallCompletedEvent)
    assert agent.calls[0][1] == {'stream': True, 'stream_events': True, 'yield_run_output': True, 'user_id': 'user'}
    await run_agent_with_events(agent, 'outside')
    assert agent.calls[-1][1] == {'stream': False}


@pytest.mark.anyio
async def test_missing_final_output_cannot_be_faked_from_content_event():
    class IncompleteAgent:
        def arun(self, *args, **kwargs):
            async def events():
                yield RunContentEvent(content='未完成')
            return events()
    with observe_agent_events(lambda _: None), pytest.raises(ValueError, match='agent_stream_output_missing'):
        await run_agent_with_events(IncompleteAgent(), 'input')


@pytest.mark.anyio
async def test_structured_executor_stream_observer_only_changes_requested_native_run(monkeypatch):
    from agno.run.agent import RunContentEvent

    from smart_reporting.reporting.structured_output import execution

    output = RunOutput(run_id='structured-final', content={'summary': 'ok'})
    calls = []

    class StructuredAgent:
        id = 'fixture'
        model = type('Model', (), {'id': 'fixture-model', 'base_url': None})()

        def arun(self, instruction, **kwargs):
            calls.append(kwargs)
            async def events():
                yield RunContentEvent(content='candidate')
                yield output
            return events() if kwargs['stream'] else output

    fake_mode = execution.StructuredOutputMode.JSON_OBJECT
    contract = type('Contract', (), {'dialect': type('D', (), {'value': 'json_object'})(), 'wire_fingerprint': 'fixture', 'decode': staticmethod(lambda value: value)})()
    monkeypatch.setattr(execution, '_agent_for_mode', lambda *args: StructuredAgent())
    monkeypatch.setattr(execution, '_runtime_verified_mode', lambda *args: fake_mode)
    monkeypatch.setattr(execution, '_runtime_capability_key', lambda *args: 'fixture')
    monkeypatch.setattr(execution, '_selected_model_route', lambda *args: ('standard', 'fixture-model'))
    monkeypatch.setattr(execution, '_schema_name', lambda value: 'Proposal')
    monkeypatch.setattr(execution, '_remember_runtime_verified_mode', lambda *args: None)
    class Resolver:
        def resolve(self, *args, **kwargs):
            return type('Capabilities', (), {'primary': fake_mode, 'fallback': None, 'source': 'verified'})()
    executor = execution.ReportingStructuredOutputExecutor(StructuredAgent(), capability_resolver=Resolver())
    executor.wire_schema_resolver.resolve = lambda *args, **kwargs: contract
    events = []
    def observe(event):
        events.append(event)
    with observe_agent_events(observe):
        result = await executor.execute('go', routing_context=None, session_id='s', user_id='u',
                                        call_budget=execution.StructuredOutputCallBudget(max_model_calls=1))
    assert result.run_output is output
    assert calls[0]['stream'] is True and calls[0]['stream_events'] is True and calls[0]['yield_run_output'] is True
    assert [event.content for event in events] == ['candidate']


@pytest.mark.anyio
async def test_event_log_bounds_replays_and_emits_reset_after_overflow():
    from smart_reporting.report_editor.agent_event_streams import AgentEventLog, stream_agent_events
    log = AgentEventLog(capacity=2)
    for index in range(3):
        await log.emit('phase', label=str(index))
    await log.emit('terminal', status='succeeded')
    events, latest, reset = await log.after(0, timeout=0)
    assert reset and latest == 4 and [event['sequence'] for event in events] == [3, 4]
    stream = [event async for event in stream_agent_events(log, 0)]
    assert b''.join(event.encode() for event in stream).count(b'event: progress') == 3
    assert b'\\\\\\\\ndata:' not in b''.join(event.encode() for event in stream)


@pytest.mark.anyio
async def test_agent_progress_omits_reasoning_and_tool_arguments():
    from agno.run.agent import (
        ToolCallCompletedEvent,
        ToolCallErrorEvent,
        ToolCallStartedEvent,
        ToolExecution,
    )

    from smart_reporting.report_editor.agent_event_streams import (
        AgentEventLog,
        bind_agent_event_log,
    )
    from smart_reporting.reporting.agent_events import agent_event_callback

    log = AgentEventLog()
    tool = ToolExecution(tool_call_id='call-17', tool_name='read_sheet', tool_args={'secret': 'private workbook value'})
    event = ToolCallStartedEvent(tool=tool)
    async with bind_agent_event_log(log):
        agent_event_callback(event)
        agent_event_callback(ToolCallCompletedEvent(tool=ToolExecution(
            tool_call_id='call-17', tool_name='read_sheet', result='private result value')))
        agent_event_callback(ToolCallErrorEvent(tool=ToolExecution(
            tool_call_id='call-18', tool_name='propose_edits', tool_args={'secret': 'private'}),
            error='private error detail'))
    await log.finish('succeeded')
    records, _, _ = await log.after(0, timeout=0)
    assert records[0] == {'sequence': 1, 'kind': 'toolStarted', 'toolName': 'read_sheet', 'toolCallId': 'call-17'}
    assert records[1] == {'sequence': 2, 'kind': 'toolCompleted', 'toolName': 'read_sheet', 'toolCallId': 'call-17', 'outcome': 'success'}
    assert records[2] == {'sequence': 3, 'kind': 'toolCompleted', 'toolName': 'propose_edits', 'toolCallId': 'call-18', 'outcome': 'error'}
    assert records[-1] == {'sequence': 4, 'kind': 'terminal', 'status': 'succeeded'}
    assert 'secret' not in repr(records) and 'private' not in repr(records)
