"""来源校验的请求内复用，避免每个锚点重复解析整篇报告。"""

import hashlib
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.trace import markdown_body
from smart_reporting.reporting.trace.semantic_bindings import statement_fingerprint

from .test_trace_subject_validate import _make_editor_with_subject


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_validation_parses_document_once_for_many_claims(tmp_path, monkeypatch):
    editor, _, context = await _make_editor_with_subject(tmp_path, period_table=True, number_reference=True)
    index = await editor.trace.require_index(context)
    original = next(binding for binding in index.subject_bindings if binding.number_reference)
    statements = [f'10月收入2400万元[[claim:claim-{i}]]。' for i in range(20)]
    markdown = '\n\n'.join(statements)
    bindings = tuple(original.model_copy(update={
        'subject_id': f'sub-{i:016x}', 'claim_id': f'claim-{i}',
        'number_reference': original.number_reference.model_copy(update={
            'claim_id': f'claim-{i}', 'statement_sha256': statement_fingerprint(markdown, f'claim-{i}'),
        }),
    }) for i in range(20))
    monkeypatch.setattr(editor.trace, 'require_index', AsyncMock(return_value=index.model_copy(update={
        'subject_bindings': bindings,
    })))
    # 改值仍应 stale；代码中的伪锚点仍应 unbound。
    markdown = markdown.replace(statements[18], statements[18].replace('2400', '2500'))
    markdown = markdown.replace(statements[19], '```\n' + statements[19] + '\n```')
    calls = 0
    parse = markdown_body.trace_body

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return parse(*args, **kwargs)

    monkeypatch.setattr(markdown_body, 'trace_body', counted)
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result['summary'] == {'valid': 18, 'stale': 1, 'unbound': 1}
    # 正文、表格、图表及复核可各自解析，但调用数不能随引用数增长。
    assert calls < 10


def test_batch_fingerprints_preserve_normalization_and_duplicate_detection(monkeypatch):
    from smart_reporting.reporting.delivery.report_runtime import markdown as render_markdown
    from smart_reporting.reporting.trace.semantic_bindings import statement_fingerprints

    text = '收入 10万元[[claim:a]].\n成本20元[[claim:b]]。\n重复[[claim:b]]。'
    calls = 0
    normalize = render_markdown.normalize_cjk_wording

    def counted(value):
        nonlocal calls
        calls += 1
        return normalize(value)

    monkeypatch.setattr(render_markdown, 'normalize_cjk_wording', counted)
    results = statement_fingerprints(text, ('a', 'b', 'missing'))
    assert results == {'a': hashlib.sha256('收入10万元.'.encode()).hexdigest(), 'b': None, 'missing': None}
    assert calls == 1


def test_batch_number_resolution_expands_source_once_and_rejects_conflicts(monkeypatch):
    import json

    from smart_reporting.reporting.trace import semantic_bindings

    from .test_semantic_bindings import contents

    tokens = ('{{value:fact-aaaaaaaaaaaaaaaa:periodValues.0:元}}',
              '{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:元}}',
              '{{value:fact-aaaaaaaaaaaaaaaa:budgetComparison.fact-bbbbbbbbbbbbbbbb.2025-02.percentage:%}}')
    calls = 0
    expand = semantic_bindings._frozen_number_entries

    def counted(*args):
        nonlocal calls
        calls += 1
        yield from expand(*args)

    monkeypatch.setattr(semantic_bindings, '_frozen_number_entries', counted)
    result = semantic_bindings.resolve_number_references(tokens, contents())
    assert [result[token]['value'] for token in tokens] == [10, 20, 20]
    assert calls == 1
    conflict = json.loads(contents()[0])
    conflict['metrics'][0]['scope'] = {'department': '另一个部门'}
    result = semantic_bindings.resolve_number_references(tokens, [*contents(), json.dumps(conflict)])
    assert all(value is None for value in result.values())
    # 同值异身份及缺操作数不能通过批处理借用其它来源。
    missing = json.loads(contents()[0])
    missing['metrics'] = missing['metrics'][:1]
    result = semantic_bindings.resolve_number_references(tokens, [json.dumps(missing)])
    assert result[tokens[2]] is None


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_editor_validation_softens_derived_rebuild_failure(tmp_path, monkeypatch):
    import json

    from smart_reporting.reporting.trace import semantic_bindings
    from smart_reporting.reporting.trace.index_builder import encode_trace_index

    from .lineage_fixtures.manifest import register_trace_manifest

    editor, _, context = await _make_editor_with_subject(tmp_path, include_table=False)
    index = await editor.trace.require_index(context)
    original = index.subject_bindings[0]
    source_id = original.fact_refs[0].file_resource_id
    source = next(file for file in index.files if file.resource_id == source_id)
    thread_id = context.scope['threadId']
    document = json.loads(await editor.workspace.aread_text(thread_id, source.path))
    metric = document['metrics'][0]
    metric.update(
        field='budget_amount', fieldRef='hospital.budget', displayName='预算支出',
        metricCodes=['budget_amount'], formula='sum(budget_amount)', total=400, unit='元',
        periodValues=[{'period': '2025-09', 'value': 400}],
    )
    document['metrics'].append({
        **metric, 'factId': 'fact-bbbbbbbbbbbbbbbb', 'field': 'actual_amount',
        'fieldRef': 'hospital.actual', 'displayName': '实际支出',
        'metricCodes': ['actual_amount'], 'formula': 'sum(actual_amount)', 'total': 150,
        'periodValues': [{'period': '2025-09', 'value': 150}],
    })
    raw = json.dumps(document, ensure_ascii=False).encode()
    # 先从真实双事实签发派生引用；故障仅在编辑器重新构建目录时注入。
    markdown, references, notices = semantic_bindings.render_bound_numbers(
        '2025年9月预算支出400.00元，实际支出150.00元，预算支出比实际支出多250.00元。\n\n'
        '2025年9月预算支出{{value:fact-aaaaaaaaaaaaaaaa:total:元}}。',
        [raw.decode()], key='editor-derived-failure',
    )
    assert not notices
    assert len(references) == 2
    derived = next(ref for ref in references if ref.token.startswith('{{derived:'))
    ordinary = next(ref for ref in references if ref.token.startswith('{{value:'))
    assert set(semantic_bindings.reference_fact_ids(derived.token)) == {
        'fact-aaaaaaaaaaaaaaaa', 'fact-bbbbbbbbbbbbbbbb',
    }
    markdown = semantic_bindings.anchor_bound_numbers(markdown, references)
    fact_refs = {
        metric['factId']: original.fact_refs[0].model_copy(update={
            'json_pointer': f'/metrics/{position}', 'fact_key': metric['factId'],
        })
        for position, metric in enumerate(document['metrics'])
    }
    bindings = tuple(original.model_copy(update={
        'subject_id': f'sub-{position:016x}', 'claim_id': reference.claim_id,
        'number_reference': reference,
        'fact_refs': tuple(fact_refs[key] for key in semantic_bindings.reference_fact_ids(reference.token)),
    }) for position, reference in enumerate(references))
    markdown_bytes = markdown.encode()
    digest = hashlib.sha256(markdown_bytes).hexdigest()
    files = tuple(file.model_copy(update={
        'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
    }) if file.resource_id == source_id else file.model_copy(update={
        'size': len(markdown_bytes), 'sha256': digest,
    }) if file.resource_id == index.markdown_file_resource_id else file for file in index.files)
    index = index.model_copy(update={'files': files, 'subject_bindings': bindings})
    await editor.workspace.awrite_bytes(thread_id, source.path, raw, overwrite=True)
    await editor.workspace.awrite_bytes(
        thread_id, context.markdown_path, markdown_bytes, overwrite=True,
    )
    await editor.workspace.awrite_bytes(
        thread_id, 'reports/revision-1/trace-index-v1.json', encode_trace_index(index), overwrite=True,
    )
    manifest = await register_trace_manifest(editor.workspace, thread_id, index, overwrite=True)
    context = context.model_copy(update={'artifact_manifest': manifest})
    baseline = await editor.trace.validate(context, markdown, digest)
    assert baseline['summary'] == {'valid': 2, 'stale': 0, 'unbound': 0}
    assert {item['claimId']: item['factValue'] for item in baseline['subjects']} == {
        derived.claim_id: 250, ordinary.claim_id: 400,
    }
    rebuilds = []

    def fail_rebuild(contents):
        rebuilds.append(contents)
        raise RuntimeError('injected derived directory rebuild failure')

    monkeypatch.setattr(semantic_bindings, 'derived_number_values', fail_rebuild)
    result = await editor.trace.validate(context, markdown, digest)
    assert rebuilds
    assert result['summary'] == {'valid': 1, 'stale': 0, 'unbound': 1}
    subjects = {item['claimId']: item for item in result['subjects']}
    assert subjects[ordinary.claim_id]['status'] == 'valid'
    assert subjects[ordinary.claim_id]['factValue'] == 400
    assert subjects[derived.claim_id]['status'] == 'unbound'
    assert subjects[derived.claim_id]['factValue'] is None
    assert subjects[derived.claim_id]['restoreText'] is None
    assert '具体数值引用无法从登记事实重算。' in subjects[derived.claim_id]['warnings']
    # 派生故障降级不能掩盖冻结文件被篡改，即使文件长度没有变化。
    tampered = raw.replace(b'400', b'401')
    assert tampered != raw and len(tampered) == len(raw)
    await editor.workspace.awrite_bytes(thread_id, source.path, tampered, overwrite=True)
    result = await editor.trace.validate(context, markdown, digest)
    assert result['summary']['valid'] == 0
    assert result['sourceIssues'][0]['code'] == 'snapshot_integrity_failed'


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_content_review_does_not_block_other_async_requests(tmp_path, monkeypatch):
    import asyncio
    import threading

    import anyio

    from smart_reporting.reporting.trace import content_review

    editor, _, context = await _make_editor_with_subject(tmp_path)
    started, release = threading.Event(), threading.Event()
    responsive = []
    review = content_review.review_content

    def slow_review(*args, **kwargs):
        started.set()
        responsive.append(release.wait(timeout=2))
        return review(*args, **kwargs)

    monkeypatch.setattr(content_review, 'review_content', slow_review)
    markdown = '收入3600万元[[claim:claim-1]]。'
    task = asyncio.create_task(editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest()))
    try:
        assert await anyio.to_thread.run_sync(started.wait, 5)
        # 代表同一事件循环中的其它请求；必须能在复核计算结束前得到执行。
        release.set()
        result = await task
    finally:
        release.set()
        await task
    assert responsive == [True]
    assert result['summary']['valid'] == 1


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_batch_lookup_keeps_file_identity_and_rechecks_changed_files(tmp_path, monkeypatch):
    import json

    from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id

    editor, _, context = await _make_editor_with_subject(tmp_path, period_table=True, number_reference=True)
    index = await editor.trace.require_index(context)
    first = next(binding for binding in index.subject_bindings if binding.number_reference)
    source = next(file for file in index.files if file.resource_id == first.fact_refs[0].file_resource_id)
    thread_id = context.scope['threadId']
    document = json.loads(await editor.workspace.aread_text(thread_id, source.path))
    document['metrics'][0]['datasetId'] = 'different-dataset'
    document['metrics'][0]['datasetSha256'] = 'd' * 64
    document['metrics'][0]['periodValues'][1]['value'] = 4800
    raw = json.dumps(document).encode()
    path = source.path.replace('.json', '-other.json')
    await editor.workspace.awrite_bytes(thread_id, path, raw)
    file = source.model_copy(update={'path': path, 'resource_id': derive_resource_id(path),
                                    'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    markdown = '10月收入2400万元[[claim:first]]。\n\n10月收入4800万元[[claim:second]]。'
    bindings = tuple(first.model_copy(update={
        'subject_id': f'sub-{i:016x}', 'claim_id': claim,
        'fact_refs': (first.fact_refs[0].model_copy(update={'file_resource_id': resource_id}),),
        'number_reference': first.number_reference.model_copy(update={
            'claim_id': claim, 'statement_sha256': statement_fingerprint(markdown, claim),
        }),
    }) for i, (claim, resource_id) in enumerate((('first', source.resource_id), ('second', file.resource_id))))
    monkeypatch.setattr(editor.trace, 'require_index', AsyncMock(return_value=index.model_copy(update={
        'files': (*index.files, file), 'subject_bindings': bindings,
    })))
    digest = hashlib.sha256(markdown.encode()).hexdigest()
    result = await editor.trace.validate(context, markdown, digest)
    assert [item['factValue'] for item in result['subjects']] == [2400, 4800]
    assert result['summary']['valid'] == 2
    await editor.workspace.awrite_bytes(thread_id, path, raw + b' ', overwrite=True)
    result = await editor.trace.validate(context, markdown, digest)
    assert result['summary'] == {'valid': 1, 'stale': 0, 'unbound': 1}
    assert result['subjects'][0]['factValue'] == 2400
    assert result['subjects'][1]['factValue'] is None
    assert result['sourceIssues'][0]['code'] == 'snapshot_integrity_failed'


def test_year_review_rounds_registered_values_once_per_display_precision(monkeypatch):
    from decimal import Decimal

    from smart_reporting.reporting.trace import review_periods

    from .test_semantic_bindings import contents

    registered = review_periods._registered_value_years(contents())
    calls = 0

    class CountedDecimal(Decimal):
        def quantize(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            return super().quantize(*args, **kwargs)

    monkeypatch.setattr(review_periods, '_registered_value_years', lambda _: [
        (unit, CountedDecimal(value), years) for unit, value, years in registered
    ])
    warnings = review_periods._year_label_warnings('2024年收入10.00元。' * 20, contents())
    assert len(warnings) == 20
    assert all('不是2024年' in warning for warning in warnings)
    assert calls <= len(registered)


def test_period_review_serializes_each_candidate_fact_once(monkeypatch):
    import json

    from smart_reporting.reporting.trace import review_periods

    from .test_semantic_bindings import contents

    documents = [json.loads(content) for content in contents()]
    calls = 0
    dump = json.dumps

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return dump(*args, **kwargs)

    monkeypatch.setattr(review_periods.json, 'dumps', counted)
    matches = list(review_periods._period_claim_facts(
        '2025年全年实际设备30元。' * 20, documents, {'actual_equipment': '实际设备'},
    ))
    assert len(matches) == 20
    assert {fact_id for _, fact_id in matches} == {'fact-aaaaaaaaaaaaaaaa'}
    assert calls == 1
