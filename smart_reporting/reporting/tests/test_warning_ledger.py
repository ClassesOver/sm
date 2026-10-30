"""Lossless grouping never turns incomplete proof into a business verdict."""

import hashlib
import json
import os
import sys

import pytest

from smart_reporting.reporting.trace.quality_bundle import QualityBundle, QualityIssue
from smart_reporting.reporting.trace.warning_ledger import build_warning_ledger

from .test_trace_subject_validate import _make_editor_with_subject


@pytest.mark.parametrize("target", ["quality", "index"])
@pytest.mark.parametrize("link", ["direct", "symlink", "hardlink"])
def test_worklist_export_cannot_overwrite_inputs(tmp_path, monkeypatch, target, link):
    from scripts.assess_report_warnings import main

    quality, index = tmp_path / "quality.json", tmp_path / "index.json"
    quality.write_bytes(b"frozen-quality")
    index.write_bytes(b"frozen-index")
    output = quality if target == "quality" else index
    if link != "direct":
        source = output
        output = tmp_path / "output.json"
        if link == "symlink":
            output.symlink_to(source)
        else:
            os.link(source, output)
    monkeypatch.setattr(sys, "argv", ["assess", "--quality", str(quality), "--index", str(index), "--output", str(output)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert quality.read_bytes() == b"frozen-quality" and index.read_bytes() == b"frozen-index"


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_review_packet_preserves_individual_evidence_and_binds_versions(tmp_path, monkeypatch):
    from scripts.assess_report_warnings import main
    from smart_reporting.reporting.trace.warning_ledger import build_warning_review_packet

    editor, _, context = await _make_editor_with_subject(tmp_path, period_table=True, number_reference=True)
    index = await editor.trace.require_index(context)
    subject = next(item for item in index.subject_bindings if item.number_reference is not None)
    markdown = next(file for file in index.files if file.resource_id == index.markdown_file_resource_id)
    quality = QualityBundle(reportId=index.report_id, revision=index.revision,
                            markdownSha256=markdown.sha256, inputSha256="b" * 64, issues=(
        QualityIssue(code="assertion_support_unknown", subjectId=subject.subject_id, reasons=("scope_unknown",)),
        QualityIssue(code="assertion_support_unknown", subjectId=subject.subject_id, reasons=("statement_not_supported",)),
        QualityIssue(code="future_check", reasons=("future_reason", "markdown_line:362")),
    ))
    before = quality.model_dump_json(), index.model_dump_json()
    packet = build_warning_review_packet(quality, index)
    assert packet.ledger.group_count == 2 and len(packet.cases) == 3
    assert tuple(case.issue for case in packet.cases) == quality.issues
    assert packet.cases[0].group_id == packet.cases[1].group_id
    assert packet.cases[0].review_ids != packet.cases[1].review_ids
    assert packet.cases[0].subject == subject
    assert packet.cases[2].subject is None and packet.cases[2].required_actions
    assert all(case.adjudication == "not_adjudicated" for case in packet.cases)
    assert packet.business_acceptance_evaluated is False
    assert packet == build_warning_review_packet(quality, index)
    changed = build_warning_review_packet(quality.model_copy(update={"issues": tuple(reversed(quality.issues))}), index)
    assert not {case.case_id for case in packet.cases} & {case.case_id for case in changed.cases}
    changed = build_warning_review_packet(quality, index.model_copy(update={"workflow_run_id": "other-run"}))
    assert changed.index_sha256 != packet.index_sha256
    assert changed.cases[0].case_id != packet.cases[0].case_id
    with pytest.raises(ValueError, match="Markdown"):
        build_warning_review_packet(quality.model_copy(update={"markdown_sha256": "c" * 64}), index)
    with pytest.raises(ValueError, match="identities"):
        build_warning_review_packet(quality.model_copy(update={"revision": quality.revision + 1}), index)
    assert before == (quality.model_dump_json(), index.model_dump_json())
    quality_path, index_path, output = (tmp_path / name for name in ("quality.json", "index.json", "packet.json"))
    quality_path.write_text(quality.model_dump_json())
    index_path.write_text(index.model_dump_json())
    monkeypatch.setattr(sys, "argv", ["assess", "--quality", str(quality_path), "--index", str(index_path),
                                    "--output", str(output), "--review-packet"])
    assert main() == 0
    result = json.loads(output.read_text())
    assert len(result["cases"]) == 3 and result["ledger"]["originalIssueCount"] == 3
    assert result["inputFileHashes"]["index"] == hashlib.sha256(index_path.read_bytes()).hexdigest()


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
        QualityIssue(code="chart_support_unknown", subjectId="chart-1", reasons=("chart_unregistered",)),
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
@pytest.mark.parametrize("change", ["analysis", "file", "pointer", "kind", "extra_unkeyed", "unkeyed"])
async def test_same_fact_key_cannot_merge_distinct_frozen_references(tmp_path, change):
    editor, _, context = await _make_editor_with_subject(tmp_path, period_table=True, number_reference=True)
    index = await editor.trace.require_index(context)
    subject = next(item for item in index.subject_bindings if item.number_reference is not None)
    original = subject.fact_refs[0]
    changes = {
        "analysis": {"analysis_id": "analysis_999999"},
        "file": {"file_resource_id": "trf-" + "a" * 20},
        "pointer": {"json_pointer": "/other/0"},
        "kind": {"fact_kind": "comparison"},
        "unkeyed": {"fact_key": None},
        "extra_unkeyed": {"fact_key": None, "json_pointer": "/other/0"},
    }
    other_ref = type(original).model_validate({**original.model_dump(), **changes[change]})
    refs = (*subject.fact_refs, other_ref) if change == "extra_unkeyed" else (other_ref,)
    other = subject.model_copy(update={"subject_id": "sub-" + "f" * 16, "fact_refs": refs})
    index = index.model_copy(update={"subject_bindings": (subject, other)})
    quality = QualityBundle(reportId=index.report_id, revision=index.revision,
                            markdownSha256="a" * 64, inputSha256="b" * 64, issues=tuple(
        QualityIssue(code="assertion_support_unknown", subjectId=item.subject_id, reasons=("scope_unknown",))
        for item in (subject, other)
    ))
    ledger = build_warning_ledger(quality, index)
    assert ledger.group_count == 2
    assert all(group.target_kind == "fact" for group in ledger.groups)
    assert all(len(group.subject_ids) == 1 for group in ledger.groups)
    assert ledger.groups[0].fact_refs == subject.fact_refs
    assert set(ledger.groups[1].fact_refs) == set(refs)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_group_identity_tracks_frozen_bytes_and_ignores_reference_order(tmp_path):
    editor, _, context = await _make_editor_with_subject(tmp_path, period_table=True, number_reference=True)
    index = await editor.trace.require_index(context)
    subject = next(item for item in index.subject_bindings if item.number_reference is not None)
    first = subject.fact_refs[0]
    second = first.model_copy(update={"json_pointer": "/metrics/99", "fact_key": None})
    subject = subject.model_copy(update={"fact_refs": (first, second)})
    copy = subject.model_copy(update={"subject_id": "sub-" + "f" * 16, "fact_refs": (second, first, first)})
    index = index.model_copy(update={"subject_bindings": (subject, copy)})
    quality = QualityBundle(reportId=index.report_id, revision=index.revision,
                            markdownSha256="a" * 64, inputSha256="b" * 64, issues=tuple(
        QualityIssue(code="assertion_support_unknown", subjectId=item.subject_id, reasons=("scope_unknown",))
        for item in (subject, copy)
    ))
    ledger = build_warning_ledger(quality, index)
    assert ledger.group_count == 1 and ledger.grouping_version == "fact-reference/2"
    assert set(ledger.groups[0].fact_refs) == {first, second}
    assert ledger.groups[0].fact_ids == (first.fact_key,)
    changed_index = index.model_copy(update={"files": tuple(
        file.model_copy(update={"sha256": "f" * 64}) if file.resource_id == first.file_resource_id else file
        for file in index.files
    )})
    changed = build_warning_ledger(quality, changed_index)
    assert changed.groups[0].group_id != ledger.groups[0].group_id
    assert sorted(position for group in changed.groups for position in group.issue_indices) == [0, 1]


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
