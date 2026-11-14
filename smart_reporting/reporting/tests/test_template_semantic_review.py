"""语义判断只选择原生安全区域；外部模型在结构化执行器边界替代。"""

import asyncio
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace

import pytest
from agno.run import RunContext
from docx import Document


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def template_bytes(*, declared=False):
    document = Document()
    document.add_paragraph('{{report_title}} · 业务引用：清川分析室在2001-02-03确认收入1234.56，必须保留。')
    document.add_paragraph('{{report_content}}')
    document.add_paragraph('{{report_signature}}' if declared else '清川分析室')
    if not declared:
        document.add_paragraph('2001-02-03')
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def opinion(raw, *, indices=(2, 3)):
    from smart_reporting.reporting.delivery.template_signature_semantics import (
        inspect_signature_candidates,
    )

    blocks = inspect_signature_candidates(raw)['blocks']
    return {'status': 'resolved', 'blocks': [
        {**{key: blocks[index][key] for key in ('blockId', 'text')},
            'role': 'sample_identity' if position == 0 else 'sample_date'}
        for position, index in enumerate(indices)]}


class Executor:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.requests = []

    async def execute(self, instruction, **kwargs):
        self.requests.append((instruction, kwargs))
        answer = next(self.answers)
        if isinstance(answer, BaseException):
            raise answer
        return SimpleNamespace(content=deepcopy(answer))


@pytest.mark.anyio
async def test_agreeing_review_replaces_sample_but_preserves_same_name_business_quote():
    from smart_reporting.reporting.delivery.template_signature_semantics import (
        bind_semantic_signature_slot,
    )
    from smart_reporting.reporting.delivery.templates import fill_report_template
    from smart_reporting.reporting.template_semantic_review import (
        TemplateSignatureReviewer,
        validate_frozen_review,
    )

    raw = template_bytes()
    executor = Executor([opinion(raw), opinion(raw)])
    record = await TemplateSignatureReviewer(executor).review(raw, run_context=RunContext(
        run_id='run', session_id='session', user_id='owner', session_state={}))
    assert record['status'] == 'resolved'
    assert validate_frozen_review(raw, record) == record
    prepared, _ = bind_semantic_signature_slot(raw, {key: record[key]
        for key in ('version', 'templateSha256', 'status', 'blockIds', 'evidence')})
    filled = fill_report_template(prepared, template_format='docx', delivery_format='docx',
        values={'report_content': '冻结数据库正文'},
        signature={'signer': '冻结编制人', 'date': '2026-09-16'})
    output = Document(BytesIO(filled.content))
    text = '\n'.join(output._element.body.xpath('.//w:t/text()'))
    assert text.count('清川分析室') == 1 and text.count('2001-02-03') == 1
    assert '业务引用：清川分析室在2001-02-03确认收入1234.56，必须保留。' in text
    assert '冻结编制人' in text and '2026-09-16' in text
    assert len(executor.requests) == 2
    assert executor.requests[0][1]['session_id'] != executor.requests[1][1]['session_id']
    assert all(request[1]['call_budget'].max_model_calls == 1 for request in executor.requests)
    assert all('业务引用' in request[0] for request in executor.requests)


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['disagree', 'evidence', 'unknown', 'noncontiguous', 'duplicate', 'description_only', 'ambiguous', 'provider'])
async def test_unsafe_or_disagreeing_judgment_never_produces_a_replaceable_record(fault):
    from smart_reporting.reporting.template_semantic_review import TemplateSignatureReviewer

    raw = template_bytes()
    first, second = opinion(raw), opinion(raw)
    if fault == 'disagree':
        second = opinion(raw, indices=(2,))
    elif fault == 'evidence':
        second['blocks'][0]['text'] = '模型编造的原文'
    elif fault == 'unknown':
        second['blocks'][0]['blockId'] = 'foreign-id'
    elif fault == 'noncontiguous':
        second = first = opinion(raw, indices=(0, 3))
    elif fault == 'duplicate':
        second['blocks'].append(deepcopy(second['blocks'][0]))
    elif fault == 'description_only':
        for item in second['blocks']:
            item['role'] = 'sample_description'
        first = deepcopy(second)
    elif fault == 'ambiguous':
        second = {'status': 'ambiguous', 'blocks': []}
    else:
        second = RuntimeError('provider error containing private path')
    record = await TemplateSignatureReviewer(Executor([first, second])).review(raw,
        run_context=RunContext(run_id='run', session_id='session', user_id='owner', session_state={}))
    assert record['status'] in {'ambiguous', 'unavailable'}
    assert record['blockIds'] == [] and record['evidence'] == []
    assert 'private path' not in str(record)


@pytest.mark.anyio
async def test_declared_slot_skips_model_and_cancellation_is_not_softened():
    from smart_reporting.reporting.template_semantic_review import TemplateSignatureReviewer

    run = RunContext(run_id='run', session_id='session', user_id='owner', session_state={})
    executor = Executor([])
    assert (await TemplateSignatureReviewer(executor).review(template_bytes(declared=True), run_context=run))['status'] == 'declared'
    assert not executor.requests
    with pytest.raises(asyncio.CancelledError):
        await TemplateSignatureReviewer(Executor([asyncio.CancelledError()])).review(template_bytes(), run_context=run)


@pytest.mark.anyio
async def test_total_deadline_preserves_template_without_retrying_provider():
    from smart_reporting.reporting.template_semantic_review import TemplateSignatureReviewer

    class Slow:
        async def execute(self, *_args, **_kwargs):
            await asyncio.Event().wait()

    record = await TemplateSignatureReviewer(Slow(), timeout_seconds=0.01).review(template_bytes(),
        run_context=RunContext(run_id='run', session_id='session', user_id='owner', session_state={}))
    assert record['status'] == 'unavailable' and record['blockIds'] == []


@pytest.mark.anyio
async def test_frozen_record_cannot_override_disagreement_or_changed_source():
    from smart_reporting.reporting.template_semantic_review import (
        TemplateSignatureReviewer,
        validate_frozen_review,
    )

    raw = template_bytes()
    record = await TemplateSignatureReviewer(Executor([opinion(raw), opinion(raw)])).review(raw,
        run_context=RunContext(run_id='run', session_id='session', user_id='owner', session_state={}))
    changed = deepcopy(record)
    changed['reviews'][1]['blocks'][0]['role'] = 'sample_description'
    with pytest.raises(ValueError):
        validate_frozen_review(raw, changed)
    with pytest.raises(ValueError):
        validate_frozen_review(template_bytes(declared=True), record)
