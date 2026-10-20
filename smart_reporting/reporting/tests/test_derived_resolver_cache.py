from types import SimpleNamespace

import pytest
from loguru import logger

from smart_reporting.reporting.tests.test_numeric_text import _metric_pair_document
from smart_reporting.reporting.trace import semantic_bindings
from smart_reporting.reporting.trace.numeric_text import derived_reference_token


def _entries(contents):
    derived = semantic_bindings.derived_number_values(contents)
    return [
        (unit, entry)
        for unit, entry in derived.derived_entries()
        if derived_reference_token(entry, unit) is not None
    ]


def test_current_and_legacy_catalogs_enumerate_once_for_multiple_tokens(monkeypatch):
    contents = [_metric_pair_document(fact_suffix="b", other_suffix="a")]
    tokens = list(
        dict.fromkeys(
            derived_reference_token(entry, unit, legacy=legacy)
            for unit, entry in _entries(contents)
            for legacy in (False, True)
        )
    )
    assert len(tokens) >= 4
    calls = {"factory": 0, "enumeration": 0}
    original_factory = semantic_bindings.derived_number_values

    def counted_factory(values):
        calls["factory"] += 1
        wrapped = original_factory(values)

        def counted_entries():
            calls["enumeration"] += 1
            yield from wrapped.derived_entries()

        return SimpleNamespace(derived_entries=counted_entries)

    monkeypatch.setattr(semantic_bindings, "derived_number_values", counted_factory)
    resolver = semantic_bindings.NumberReferenceResolver(contents)
    ordinary = "{{value:fact-aaaaaaaaaaaaaaab:total:元}}"
    assert resolver.resolve(ordinary)["value"] == 400
    assert calls == {"factory": 0, "enumeration": 0}
    results = [resolver.resolve(token) for token in tokens]
    assert all(result is not None for result in results)
    assert [resolver.resolve(token) for token in reversed(tokens)] == results[::-1]
    assert calls == {"factory": 1, "enumeration": 1}


@pytest.mark.parametrize("partial_enumeration", [False, True])
def test_derived_catalog_failure_is_cached_and_ordinary_resolution_survives(
    monkeypatch, partial_enumeration
):
    contents = [_metric_pair_document(fact_suffix="b", other_suffix="a")]
    entries = _entries(contents)
    tokens = list(
        dict.fromkeys(
            derived_reference_token(entry, unit, legacy=legacy)
            for unit, entry in entries
            for legacy in (False, True)
        )
    )
    assert len(tokens) >= 4
    calls = 0

    def interrupted_entries():
        yield entries[0]
        raise RuntimeError("injected enumeration failure")

    def fail(_contents):
        nonlocal calls
        calls += 1
        if partial_enumeration:
            return SimpleNamespace(derived_entries=interrupted_entries)
        raise RuntimeError("injected factory failure")

    monkeypatch.setattr(semantic_bindings, "derived_number_values", fail)
    warnings = []
    sink_id = logger.add(lambda message: warnings.append(message.record), level="WARNING")
    try:
        resolver = semantic_bindings.NumberReferenceResolver(contents)
        ordinary = "{{value:fact-aaaaaaaaaaaaaaab:total:元}}"
        assert resolver.resolve(ordinary)["value"] == 400
        assert calls == 0
        for token in tokens + tokens[::-1]:
            assert resolver.resolve(token) is None
        assert resolver._derived_entries() == {}
        assert resolver._derived_entries(legacy=True) == {}
        assert resolver.resolve(ordinary)["value"] == 400
    finally:
        logger.remove(sink_id)

    assert calls == 1
    assert len(warnings) == 1
    assert "number_reference_derived_catalog_failed" in warnings[0]["message"]
    assert "injected" in warnings[0]["message"]


def test_true_reverse_fact_id_legacy_token_remains_compatible():
    contents = [_metric_pair_document(fact_suffix="b", other_suffix="a")]
    unit, entry = next(
        (unit, entry)
        for unit, entry in _entries(contents)
        if entry.difference is not None and entry.value == 250
    )
    assert entry.fact_ids != tuple(sorted(entry.fact_ids))
    current_token = derived_reference_token(entry, unit)
    legacy_token = derived_reference_token(entry, unit, legacy=True)
    assert current_token != legacy_token
    assert semantic_bindings.reference_fact_ids(current_token) == entry.fact_ids
    assert semantic_bindings.reference_fact_ids(legacy_token) == tuple(sorted(entry.fact_ids))

    resolver = semantic_bindings.NumberReferenceResolver(contents)
    selected = resolver.resolve(legacy_token)
    assert selected is not None
    assert selected == resolver.resolve(current_token)
    assert selected["selector"] == "derivedDifference"
    assert selected["formula"] == "(400) - (150)"
    assert selected["value"] == 250


@pytest.mark.parametrize("formats", [(False, False), (True, True), (False, True)])
@pytest.mark.parametrize("reverse_entries", [False, True])
def test_injected_token_collision_with_different_resolved_view_is_rejected(
    monkeypatch, formats, reverse_entries
):
    contents = [_metric_pair_document(fact_suffix="b", other_suffix="a")]
    entries = _entries(contents)
    difference_unit, difference_entry = next(
        (unit, entry)
        for unit, entry in entries
        if entry.difference is not None and entry.value == 250
    )
    ratio_unit, ratio_entry = next((unit, entry) for unit, entry in entries if entry.ratio)
    resolver = semantic_bindings.NumberReferenceResolver(contents)
    difference_view = semantic_bindings.derived_reference_resolution(
        difference_entry, difference_unit, resolver.entries
    )
    ratio_view = semantic_bindings.derived_reference_resolution(
        ratio_entry, ratio_unit, resolver.entries
    )
    assert difference_view is not None and ratio_view is not None
    assert difference_view != ratio_view
    token = derived_reference_token(difference_entry, difference_unit, legacy=formats[0])
    original_token = semantic_bindings.derived_reference_token
    prepared = [(difference_unit, difference_entry), (ratio_unit, ratio_entry)]
    if reverse_entries:
        prepared.reverse()
    monkeypatch.setattr(
        semantic_bindings,
        "derived_number_values",
        lambda _: SimpleNamespace(derived_entries=lambda: iter(prepared)),
    )

    def collide(entry, unit, *, legacy=False):
        if (entry is difference_entry and legacy == formats[0]) or (
            entry is ratio_entry and legacy == formats[1]
        ):
            return token
        return original_token(entry, unit, legacy=legacy)

    monkeypatch.setattr(semantic_bindings, "derived_reference_token", collide)
    assert resolver.resolve(token) is None
    assert token not in resolver._derived_entries()
    assert token not in resolver._derived_entries(legacy=True)
    assert resolver.resolve(token) is None
    assert resolver.resolve("{{value:fact-aaaaaaaaaaaaaaab:total:元}}")["value"] == 400
