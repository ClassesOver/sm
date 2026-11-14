"""落款语义判断复用既有工作区不可变文件及artifact登记。"""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest
from agno.run import RunContext

from smart_reporting.reporting.tests.test_template_runtime import TemplateRuntime
from smart_reporting.reporting.tests.test_template_semantic_review import (
    Executor,
    opinion,
    template_bytes,
)


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def frozen_case():
    from smart_reporting.reporting.template_semantic_review import TemplateSignatureReviewer
    from smart_reporting.reporting.workflow.runtime.template_semantics import freeze_template_review

    raw = template_bytes()
    runtime = TemplateRuntime(raw)
    executor = Executor([opinion(raw), opinion(raw)])
    runtime.template_signature_reviewer = TemplateSignatureReviewer(executor)
    run = RunContext(run_id='run', session_id='session', user_id='owner', session_state={})
    args = dict(run_id='run', thread_id='thread', target_context=run, execution_options={}, allow_review=True)
    record, issues = await freeze_template_review(runtime, run, raw,
        durable=await runtime.get('run'), **args)
    return SimpleNamespace(raw=raw, runtime=runtime, run=run, record=record, issues=issues,
        executor=executor, args=args)


@pytest.mark.anyio
async def test_restart_reuses_registered_review_without_calling_model():
    from smart_reporting.reporting.workflow.runtime.template_semantics import (
        freeze_template_review,
        semantic_review_path,
    )

    case = await frozen_case()
    assert case.record['status'] == 'resolved' and not case.issues
    path = semantic_review_path('run', case.raw)
    before = deepcopy(case.runtime.files)
    assert any(item['path'] == path for item in case.runtime.registered)
    del case.runtime.template_signature_reviewer
    record, issues = await freeze_template_review(case.runtime, case.run, case.raw,
        durable=await case.runtime.get('run'), **case.args)
    assert record == case.record and not issues
    assert case.runtime.files == before and len(case.executor.requests) == 2


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['registration', 'write', 'read_drift', 'unregistered'])
async def test_freeze_failure_never_applies_unfrozen_or_drifted_judgment(fault):
    from smart_reporting.reporting.workflow.runtime.template_semantics import (
        freeze_template_review,
        semantic_review_path,
    )

    case = await frozen_case()
    path = semantic_review_path('run', case.raw)
    if fault == 'read_drift':
        case.runtime.files[path] += b' '
    else:
        case.runtime.registered = [item for item in case.runtime.registered if item['path'] != path]
        if fault != 'unregistered':
            case.runtime.files.pop(path)

            async def fail(*_args, **_kwargs):
                raise OSError('private storage path')

            if fault == 'registration':
                case.runtime._apply_durable_command = fail
            else:
                case.runtime._write_immutable_artifact = fail
            case.runtime.template_signature_reviewer.executor = Executor([opinion(case.raw), opinion(case.raw)])
    record, issues = await freeze_template_review(case.runtime, case.run, case.raw,
        durable=await case.runtime.get('run'), **case.args)
    assert record is None and issues
    assert 'private storage path' not in str(issues)


@pytest.mark.anyio
async def test_historical_missing_review_never_reinterprets_or_writes():
    from smart_reporting.reporting.template_semantic_review import TemplateSignatureReviewer
    from smart_reporting.reporting.workflow.runtime.template_semantics import freeze_template_review

    raw = template_bytes()
    runtime = TemplateRuntime(raw)
    executor = Executor([])
    runtime.template_signature_reviewer = TemplateSignatureReviewer(executor)
    before = deepcopy(runtime.files)
    record, issues = await freeze_template_review(runtime, SimpleNamespace(run_id='run'), raw,
        durable=await runtime.get('run'), run_id='run', thread_id='thread', target_context=None,
        execution_options={}, allow_review=False)
    assert record is None and issues and runtime.files == before
    assert not executor.requests


@pytest.mark.anyio
async def test_concurrent_freezes_share_the_registered_winner_from_fresh_state():
    from smart_reporting.reporting.template_semantic_review import TemplateSignatureReviewer
    from smart_reporting.reporting.workflow.runtime.template_semantics import freeze_template_review

    raw = template_bytes()
    runtime = TemplateRuntime(raw)
    lock = asyncio.Lock()

    @asynccontextmanager
    async def lifecycle(_key):
        async with lock:
            yield

    class SlowExecutor(Executor):
        async def execute(self, *args, **kwargs):
            await asyncio.sleep(0.02)
            return await super().execute(*args, **kwargs)

    runtime.workflow_thread_lifecycle_lock = lifecycle
    executor = SlowExecutor([opinion(raw), opinion(raw), opinion(raw, indices=(2,)), opinion(raw, indices=(2,))])
    runtime.template_signature_reviewer = TemplateSignatureReviewer(executor)
    run = RunContext(run_id='run', session_id='session', user_id='owner', session_state={})
    args = dict(durable=await runtime.get('run'), run_id='run', thread_id='thread', target_context=run,
        execution_options={}, allow_review=True)
    first, second = await asyncio.gather(freeze_template_review(runtime, run, raw, **args),
        freeze_template_review(runtime, run, raw, **args))
    assert first[0]['status'] == 'resolved' and second[0] == first[0]
    assert not first[1] and not second[1] and len(executor.requests) == 2
