"""Lossless grouping never turns incomplete proof into a business verdict."""

import hashlib
import sys

import pytest

from smart_reporting.reporting.trace.quality_bundle import QualityBundle, QualityIssue
from smart_reporting.reporting.trace.warning_ledger import build_warning_ledger

from .test_trace_subject_validate import _make_editor_with_subject


@pytest.mark.parametrize("target", ["quality", "index"])
def test_worklist_export_cannot_overwrite_inputs(tmp_path, monkeypatch, target):
    from scripts.assess_report_warnings import main

    quality, index = tmp_path / "quality.json", tmp_path / "index.json"
    quality.write_bytes(b"frozen-quality")
    index.write_bytes(b"frozen-index")
    output = quality if target == "quality" else index
    monkeypatch.setattr(sys, "argv", ["assess", "--quality", str(quality), "--index", str(index), "--output", str(output)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert quality.read_bytes() == b"frozen-quality" and index.read_bytes() == b"frozen-index"


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_ledger_groups_dependencies_without_losing_or_adjudicating_issues(tmp_path):
    editor, _, context = await _make_editor_with_subject(tmp_path, period_table=True, number_reference=True)
    index = await editor.trace.require_index(context)
    subject = next(item for item in index.subject_bindings if item.number_reference is not None)
    copy = subject.model_copy(update={"subject_id": "sub-" + "f" * 16})
    index = index.model_copy(update={"subject_bindings": (*index.subject_bindings, copy)})
    issues = (
        QualityIssue(code="assertion_support_unknown", subjectId=subject.subject_id, reasons=("scope_unknown",)),
        QualityIssue(code="assertion_support_unknown", subjectId=copy.subject_id, reasons=("scope_value_unknown",)),
        QualityIssue(code="chart_support_unknown", subjectId="chart-1", reasons=("interactive_spec_unregistered",)),
        QualityIssue(code="chart_semantic_alignment_unknown", subjectId="chart-1", reasons=("chart_arrays_unverified",)),
        QualityIssue(code="future_check", reasons=("future_reason",)),
        QualityIssue(code="future_check", reasons=()),
    )
    quality = QualityBundle(reportId=index.report_id, revision=index.revision,
                            markdownSha256="a" * 64, inputSha256="b" * 64, issues=issues)
    before = quality.model_dump_json()
    ledger = build_warning_ledger(quality, index)
    assert ledger.original_issue_count == 6 and ledger.group_count == 4
    assert sorted(position for group in ledger.groups for position in group.issue_indices) == list(range(6))
    assert quality.model_dump_json() == before
    assert ledger.business_acceptance_evaluated is False
    fact_group = next(group for group in ledger.groups if group.target_kind == "fact")
    assert fact_group.assessments == ("unresolved",)
    assert set(fact_group.subject_ids) == {subject.subject_id, copy.subject_id}
    assert "R043" in fact_group.review_ids
    assert all(group.adjudication == "not_adjudicated" for group in ledger.groups)
    assert all(group.assessments == ("unclassified",) for group in ledger.groups if "future_check" in group.issue_codes)
    with pytest.raises(ValueError):
        build_warning_ledger(quality.model_copy(update={"report_id": "other-report"}), index)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("ledger_failure", [False, True])
async def test_editor_keeps_diagnostics_even_if_optional_worklist_fails(tmp_path, monkeypatch, ledger_failure):
    editor, _, context = await _make_editor_with_subject(tmp_path, period_table=True, number_reference=True)
    if ledger_failure:
        from smart_reporting.reporting.trace import warning_ledger

        def unavailable(*args):
            raise RuntimeError("worklist unavailable")

        monkeypatch.setattr(warning_ledger, "build_warning_ledger", unavailable)
    index = await editor.trace.require_index(context)
    file = next(file for file in index.files if file.resource_id == index.markdown_file_resource_id)
    markdown = (await editor.trace._read_registered_file(context, file, max_bytes=16 * 1024 * 1024)).decode()
    result = await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    quality = result["quality"]
    assert quality["status"] == "evaluated" and quality["issues"]
    if ledger_failure:
        assert "warningLedger" not in quality
    else:
        ledger = quality["warningLedger"]
        assert ledger["qualityInputSha256"] == quality["inputSha256"]
        assert ledger["originalIssueCount"] == len(quality["issues"])
        assert sorted(position for group in ledger["groups"] for position in group["issueIndices"]) == list(range(len(quality["issues"])))
