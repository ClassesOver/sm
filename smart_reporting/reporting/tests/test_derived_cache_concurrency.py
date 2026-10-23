"""Concurrent derived-number lookups must never observe a sorting window."""

import json
import linecache
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from smart_reporting.reporting.trace.numeric_text import (
    DerivedNumbers,
    derived_number_values,
)

ARGS = (Decimal(60), '元', Decimal(1), 'A比B多60元')


def test_lookup_during_sort_keeps_registered_difference_visible():
    derived = DerivedNumbers()
    derived.add('元', Decimal(60), (('A',), ('B',)))
    entered = threading.Event()
    resume = threading.Event()

    def trace(frame, event, arg):
        if (event == 'call' and frame.f_code.co_name == '<lambda>' and not entered.is_set()
                and 'entry.value' in linecache.getline(frame.f_code.co_filename, frame.f_code.co_firstlineno)):
            entered.set()
            assert resume.wait(5), 'sorting reader was not released'
        return trace

    def first_lookup():
        sys.settrace(trace)
        try:
            return derived.supports(*ARGS)
        finally:
            sys.settrace(None)

    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(first_lookup)
        try:
            assert entered.wait(5), 'did not reach sort key'
            assert derived.supports(*ARGS)
        finally:
            resume.set()
        assert first.result(timeout=5)


def test_cached_queries_use_prebuilt_indexes_and_do_not_reorder_entries(monkeypatch):
    source = json.dumps({'columns': ['项目', '金额（元）'], 'rows': [['A', 100], ['B', 40], ['C', 20]]})
    derived = derived_number_values((source,))
    before = tuple(derived.derived_entries())

    def unexpected_sort(*args, **kwargs):
        raise AssertionError('shared cache query attempted to sort')

    monkeypatch.setattr('smart_reporting.reporting.trace.numeric_text.sorted', unexpected_sort, raising=False)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: derived.supports(*ARGS), range(64)))
    assert all(results)
    assert tuple(derived.derived_entries()) == before


def test_builder_add_invalidates_prepared_index():
    derived = DerivedNumbers()
    derived.add('元', Decimal(40), (('A',), ('B',)))
    derived.prepare_indexes()
    assert not derived.supports(*ARGS)
    derived.add('元', Decimal(60), (('A',), ('B',)))
    assert derived.supports(*ARGS)
