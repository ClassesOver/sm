import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.office.repository import Identity, OfficeError, OfficeRepository
from smart_reporting.office.search import OfficeSearch, _query_patterns, _rank
from test_office_knowledge_parsing import make_knowledge_sample


@pytest.mark.asyncio
async def test_search_reads_four_formats_and_rechecks_revision_and_workspace():
    engine = create_async_engine('sqlite+aiosqlite://')
    try:
        office = OfficeRepository(engine)
        await office.create_schema()
        actor = Identity('tenant', 'company', 'owner')
        stranger = Identity('tenant', 'company', 'stranger')
        await office.bootstrap(actor, 'Owner')
        await office.provision(actor, stranger.user, 'Stranger')
        space = (await office.spaces(actor))[0]['id']
        division = await office.create_folder(actor, space, None, '总部')
        period = await office.create_folder(actor, space, division['id'], '季度')
        scope = {'database': actor.database, 'companyId': actor.company}
        originals = {}
        for fmt in ('docx', 'xlsx', 'pptx', 'pdf'):
            entry = await office.register_file(actor, space, period['id'] if fmt == 'docx' else None,
                                               f'sample.{fmt}', fmt, f'doc-{fmt}', 1, scope)
            originals[entry['id']] = make_knowledge_sample(fmt, 'Office alpha revenue 42')

        class Documents:
            async def contents(self, actor, file_id):
                entry = await office.file(actor, file_id)
                content = originals[file_id] if entry['revision'] == 1 else make_knowledge_sample('docx', 'Updated text')
                return entry, content

        search = OfficeSearch(office, Documents())
        result = await search.page(actor, space, 'ALPHA  revenue')
        assert {hit['id'] for hit in result['hits']} == set(originals)
        assert all('alpha revenue' in hit['snippet'] and hit['revision'] == 1 for hit in result['hits'])
        unreadable = SimpleNamespace(contents=AsyncMock(side_effect=AssertionError('source read after indexing')))
        restarted = OfficeSearch(OfficeRepository(engine), unreadable)
        assert await restarted.page(actor, space, 'alpha revenue') == result
        unreadable.contents.assert_not_awaited()
        with pytest.raises(OfficeError):
            await restarted.page(stranger, space, 'alpha revenue')
        word = next(row for row in (await office.library(actor, space))['files'] if row['format'] == 'docx')
        path_hits = await search.page(actor, space, '总部 季度 "alpha revenue"')
        assert [hit['id'] for hit in path_hits['hits'] if hit['complete']] == [word['id']]
        await office.record_revision(actor, word['id'], word['document'], 2)
        assert word['id'] not in {hit['id'] for hit in (await search.page(actor, space, 'alpha revenue'))['hits']}
        assert (await search.page(actor, space, 'updated'))['hits'][0]['revision'] == 2
        word = await office.file(actor, word['id'])
        await office.update_file(actor, word['id'], expected_version=word['version'], deleted=True)
        from sqlalchemy import select
        from smart_reporting.office.schema import file_search_text

        async with engine.connect() as connection:
            assert await connection.scalar(select(file_search_text.c.file).where(file_search_text.c.file == word['id'])) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_search_cursor_advances_even_when_first_batch_has_no_hits():
    entries = [{'id': str(index), 'revision': 1, 'format': 'docx', 'body': None} for index in range(9)]
    search_batch = AsyncMock(side_effect=[entries, entries[-1:]])
    search_revisions = AsyncMock(side_effect=[dict.fromkeys(map(str, range(8)), 1), {'8': 1}])
    search = OfficeSearch(SimpleNamespace(search_batch=search_batch, search_revisions=search_revisions), None)
    search._read = AsyncMock(side_effect=['no match'] * 8 + ['needle'])
    actor = Identity('tenant', 'company', 'owner')
    result = await search.page(actor, 'team', 'needle')
    assert result == {'hits': [], 'after': '7', 'corpus': {'documents': 8, 'totalLength': 16, 'documentFrequencies': [0]}}
    followup = await search.page(actor, 'team', 'needle', result['after'])
    assert followup == {'hits': [{'id': '8', 'revision': 1, 'snippet': 'needle', 'length': 1,
                                  'frequencies': [1], 'exactTerms': 1,
                                  'nameStartsWithQuery': False, 'metadataMatch': False, 'relaxedCoverage': 0,
                                  'matchedTerms': 1, 'complete': True}], 'after': None,
                        'corpus': {'documents': 1, 'totalLength': 1, 'documentFrequencies': [1]}}


def test_chinese_relaxed_search_counts_covered_characters_and_keeps_operators_strict():
    def rank(query, body, name='sample.docx'):
        return _rank({'name': name}, body, *_query_patterns(query))

    exact = rank('季度营收趋势', '本期季度营收趋势')
    relaxed = rank('季度营收趋势', '本季度，营收及预算', '季度营收.docx')
    assert exact['exactTerms'] == 1
    assert relaxed['exactTerms'] == 0
    assert relaxed['metadataMatch'] and relaxed['relaxedCoverage'] > 0.5
    assert '本季度' in relaxed['snippet']
    assert rank('季度营收趋势', '只谈营收') is None
    assert rank('"季度营收趋势"', '季度，营收与趋势') is None
    assert rank('季度营收趋势 -草稿', '季度，营收与趋势', '草稿.docx') is None


def test_search_relevance_weights_name_path_and_body_and_honors_phrases_and_exclusions():
    include, exclude = _query_patterns('季度 "net revenue" -draft')
    def rank(name, path, body):
        return _rank({'name': name, 'folder_path': path}, body, include, exclude)

    title = rank('季度 net revenue.xlsx', '', '')
    path = rank('sample.xlsx', '公司/季度', 'net revenue was 42')
    text = rank('sample.xlsx', '公司', 'net revenue was 42 in 季度 reports')
    assert sum(title['frequencies']) > sum(path['frequencies']) > sum(text['frequencies'])
    assert title['nameStartsWithQuery'] and title['metadataMatch']
    assert path['metadataMatch'] and not path['nameStartsWithQuery']
    assert not text['metadataMatch']
    assert 'net revenue was 42' in text['snippet']
    assert rank('季度.xlsx', 'draft', 'net revenue was 42') is None
    partial = rank('季度.xlsx', '', 'net global revenue')
    assert partial['matchedTerms'] == 1 and not partial['complete']


def test_any_term_fallback_preserves_exclusions_and_counts_matches():
    include, exclude = _query_patterns('quarter renewal evidence -draft')
    two_terms = _rank({'name': 'quarter.docx'}, 'renewal due', include, exclude)
    assert two_terms['matchedTerms'] == 2 and not two_terms['complete']
    assert _rank({'name': 'draft.docx'}, 'renewal due', include, exclude) is None
    assert _rank({'name': 'unrelated.docx'}, 'invoice due', include, exclude) is None


@pytest.mark.asyncio
async def test_background_index_uses_same_search_storage_and_deduplicates_work():
    actor = Identity('tenant', 'company', 'owner')
    entry = {'space': 'team', 'id': 'one', 'revision': 1, 'format': 'docx'}
    contents = AsyncMock(return_value=(entry, make_knowledge_sample('docx', 'background evidence')))
    stored = asyncio.Event()

    async def record(*args):
        stored.set()

    office = SimpleNamespace(record_search_text=AsyncMock(side_effect=record))
    search = OfficeSearch(office, SimpleNamespace(contents=contents))
    try:
        search.schedule(actor, entry)
        search.schedule(actor, entry)
        await asyncio.wait_for(stored.wait(), timeout=5)
        contents.assert_awaited_once_with(actor, 'one')
        office.record_search_text.assert_awaited_once_with(actor, 'team', 'one', 1, 'background evidence')
    finally:
        await search.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['ordered', 'foreign', 'edited', 'invalid', 'provider_error'])
async def test_optional_reranker_validates_scope_and_falls_back(case):
    actor = Identity('tenant', 'company', 'writer')
    rows = [dict(id=key, revision=1, name=f'{key}.docx', body='quarter renewal') for key in ('one', 'two')]
    if case == 'foreign':
        rows.pop()
    office = SimpleNamespace(search_batch=AsyncMock(return_value=rows), search_revisions=AsyncMock(
        return_value={'one': 1, 'two': 2 if case == 'edited' else 1},
    ))
    search = OfficeSearch(office, None, model=object())
    search._judge = AsyncMock(return_value=[1, 1] if case == 'invalid' else [2, 1],
                              side_effect=TimeoutError if case == 'provider_error' else None)
    candidates = {'one': 1, 'two': 1}
    assert await search.rerank(actor, 'team', 'renewal', candidates) == (['two', 'one'] if case == 'ordered' else [])
    office.search_batch.assert_awaited_once_with(actor, 'team', '', 20, file_ids=['one', 'two'])
    if case == 'foreign':
        search._judge.assert_not_awaited()
    else:
        assert search._judge.await_args.args == ('renewal', [
            {'number': 1, 'name': 'one.docx', 'folder': '', 'excerpt': 'quarter renewal'},
            {'number': 2, 'name': 'two.docx', 'folder': '', 'excerpt': 'quarter renewal'},
        ])
