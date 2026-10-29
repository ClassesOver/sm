"""来源复核解析复用：线程传播、请求隔离、原文/选项身份及预算边界。"""

import asyncio

import anyio
import pytest

from smart_reporting.reporting.trace import markdown_body


def _count_parses(monkeypatch):
    calls = []
    original = markdown_body._parse_trace_body

    def parse(text, *, mask_inline_code=True):
        calls.append((text, mask_inline_code))
        return original(text, mask_inline_code=mask_inline_code)

    monkeypatch.setattr(markdown_body, '_parse_trace_body', parse)
    return calls


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_cache_binds_exact_text_and_inline_code_option(monkeypatch):
    calls = _count_parses(monkeypatch)
    text = '收入 `10万元`。\n\n```\n隐藏\n```\n<!-- 注释 -->'
    changed = text.replace('10万元', '20万元')
    expected = markdown_body.trace_body(text)
    calls.clear()
    async with markdown_body.trace_body_cache_scope():
        assert markdown_body.trace_body(text) == expected
        assert markdown_body.trace_body(text) == expected
        visible = markdown_body.trace_body(text, mask_inline_code=False)
        assert '`10万元`' in visible
        assert '隐藏' not in visible and '注释' not in visible
        assert markdown_body.trace_body(changed, mask_inline_code=False) != visible
        assert markdown_body.trace_body(text, mask_inline_code=False) == visible
    assert calls == [(text, True), (text, False), (changed, False)]


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_request_cache_is_shared_with_anyio_threads_but_not_other_requests(monkeypatch):
    calls = _count_parses(monkeypatch)
    text = '同一正文 `隐藏`'

    async def request():
        async with markdown_body.trace_body_cache_scope():
            outputs = await asyncio.gather(*(
                anyio.to_thread.run_sync(markdown_body.trace_body, text) for _ in range(5)
            ))
            assert len(set(outputs)) == 1
            assert outputs[0] == markdown_body.trace_body(text)

    await asyncio.gather(request(), request())
    assert calls == [(text, True), (text, True)]
    # 离开校验请求后不存在全局结果复用。
    markdown_body.trace_body(text)
    markdown_body.trace_body(text)
    assert len(calls) == 4


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('error_type', [RuntimeError, asyncio.CancelledError])
async def test_nested_scope_restores_outer_cache_after_error_or_cancellation(monkeypatch, error_type):
    calls = _count_parses(monkeypatch)
    text = '正文'
    async with markdown_body.trace_body_cache_scope():
        markdown_body.trace_body(text)
        with pytest.raises(error_type):
            async with markdown_body.trace_body_cache_scope():
                markdown_body.trace_body(text)
                raise error_type()
        markdown_body.trace_body(text)
    assert len(calls) == 2
    assert markdown_body._TRACE_BODY_CACHE.get() is None


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('limit', ['MAX_TRACE_BODY_CACHE_BYTES', 'MAX_TRACE_BODY_CACHE_ENTRIES'])
async def test_cache_budget_overflow_preserves_parse_results(monkeypatch, limit):
    calls = _count_parses(monkeypatch)
    monkeypatch.setattr(markdown_body, limit, 0)
    text = '`隐藏`正文'
    async with markdown_body.trace_body_cache_scope():
        first = markdown_body.trace_body(text)
        assert markdown_body.trace_body(text) == first
        assert '隐藏' not in first and '正文' in first
    assert len(calls) == 2


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_parse_failure_is_not_cached(monkeypatch):
    original = markdown_body._parse_trace_body
    count = 0

    def parse(text, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            raise ValueError('parse failed')
        return original(text, **kwargs)

    monkeypatch.setattr(markdown_body, '_parse_trace_body', parse)
    async with markdown_body.trace_body_cache_scope():
        with pytest.raises(ValueError, match='parse failed'):
            markdown_body.trace_body('正文')
        assert markdown_body.trace_body('正文') == '正文'
        assert markdown_body.trace_body('正文') == '正文'
    assert count == 2
