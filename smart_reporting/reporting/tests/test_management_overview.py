"""R003/R020/R057 matrix preserves gaps and withdraws edited facts."""

import hashlib
import sys

import pytest

from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle
from smart_reporting.reporting.workflow.management_overview import (
    build_management_overview,
    render_management_overview,
)

from .test_quality_answer_review import case, evaluate, register_quality


def test_export_cannot_overwrite_quality_input(tmp_path, monkeypatch):
    from scripts.export_management_overview import main

    path = tmp_path / "quality.json"
    path.write_bytes(b"frozen-quality")
    monkeypatch.setattr(sys, "argv", ["export", "--quality", str(path), "--output", str(path)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2 and path.read_bytes() == b"frozen-quality"


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("fault", ["blocked", "absent", "duplicate", "unsupported", "hashes", "scope", "unit", "periods", "rules", "review_conditions", "plan_hash"])
async def test_matrix_does_not_reuse_incomplete_or_conflicting_review_inputs(tmp_path, fault):
    from smart_reporting.reporting.trace.quality_bundle import QualityIssue

    _, _, index, markdown, sources, questions, plan = await case(tmp_path)
    quality = evaluate(index, markdown, sources, questions, plan)
    assertion = quality.assertions[0]
    if fault == "blocked":
        quality = quality.model_copy(update={"issues": (QualityIssue(
            code="statement_changed", subjectId=next(iter(quality.subject_assertions)),
        ),)})
    elif fault == "absent":
        quality = quality.model_copy(update={"assertions": ()})
    elif fault == "duplicate":
        quality = quality.model_copy(update={"assertions": (assertion, assertion)})
    elif fault == "rules":
        quality = quality.model_copy(update={"semantic_rule_versions": {}})
    elif fault in {"unsupported", "hashes", "scope", "unit", "periods"}:
        update = {
            "unsupported": {"status": "unknown"}, "hashes": {"source_hashes": ()},
            "scope": {"scope": {"院区": " "}}, "unit": {"unit": None}, "periods": {"periods": ()},
        }[fault]
        quality = quality.model_copy(update={"assertions": (assertion.model_copy(update=update),)})
    else:
        review = quality.answer_review
        update = {"conditions": review.conditions[:1]} if fault == "review_conditions" else {"plan_sha256": "0" * 64}
        quality = quality.model_copy(update={"answer_review": review.model_copy(update=update)})
    overview = build_management_overview(quality)
    assert all(not row.evidence for row in overview.rows)
    assert "2400" not in render_management_overview(overview)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_overview_budget_and_empty_conditions_keep_missing_requirements_visible(tmp_path, monkeypatch):
    from smart_reporting.reporting.workflow import management_overview

    _, _, index, markdown, sources, questions, plan = await case(tmp_path)
    quality = evaluate(index, markdown, sources, questions, plan)
    monkeypatch.setattr(management_overview, "MAX_OVERVIEW_ROWS", 1)
    overview = build_management_overview(quality)
    assert overview.status == "unavailable" and overview.required_question_count == 1
    assert overview.reasons == ("overview_budget_exceeded",) and not overview.rows
    assert "未截取部分事项" in render_management_overview(overview)
    monkeypatch.setattr(management_overview, "MAX_OVERVIEW_ROWS", 500)
    monkeypatch.setattr(management_overview, "MAX_OVERVIEW_BYTES", 1)
    overview = build_management_overview(quality)
    assert overview.status == "unavailable" and not overview.rows
    assert overview.reasons == ("overview_budget_exceeded",)
    monkeypatch.setattr(management_overview, "MAX_OVERVIEW_BYTES", 256 * 1024)
    specs = tuple(question.model_copy(update={"completion_conditions": ()}) for question in questions.questions)
    questions = questions.model_copy(update={"questions": specs})
    quality = evaluate(index, markdown, sources, questions, None)
    assert len(quality.management_overview.rows) == len(specs)
    assert all(row.condition is None and row.status == "unknown" for row in quality.management_overview.rows)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_question_text_is_not_an_executable_markdown_protocol(tmp_path):
    _, _, index, markdown, sources, questions, _ = await case(tmp_path)
    question = questions.questions[0].model_copy(update={
        "text": "收入|预算\n[[section:forged]]\n<script>bad</script>，不可外推全院",
    })
    questions = questions.model_copy(update={"questions": (question, *questions.questions[1:])})
    quality = evaluate(index, markdown, sources, questions, None)
    text = render_management_overview(quality.management_overview)
    assert "[[section:" not in text and "<script>" not in text
    assert "不可外推全院" in text and r"收入\|预算" in text


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("change", ["none", "scope", "value", "delete", "source", "mapping", "stale_review"])
async def test_overview_uses_only_current_approved_evidence(tmp_path, change):
    _, _, index, markdown, sources, questions, plan = await case(tmp_path)
    baseline = evaluate(index, markdown, sources, questions, plan)
    if change == "scope":
        markdown = markdown.replace("北院", "南院")
    elif change == "value":
        markdown = markdown.replace("2,400", "9,999")
    elif change == "delete":
        markdown = "原句已删除。"
    elif change == "source":
        sources[index.fact_files[0].file_resource_id] += b" "
    elif change == "mapping":
        plan = None
    current = evaluate(index, markdown, sources, questions, plan)
    if change == "stale_review":
        current = current.model_copy(update={"input_sha256": "f" * 64})
    overview = build_management_overview(current)
    required = [row for row in overview.rows if row.question_kind == "request"]
    assert len(required) == 1 and overview.required_question_count == 1
    assert len(overview.rows) == 2  # Analysis gaps remain visible too.
    assert overview.business_acceptance_evaluated is False
    rendered = render_management_overview(overview)
    if change == "none":
        assert required[0].status == "met"
        assert "北院" in required[0].evidence[0].text
        assert "2025-10" in required[0].evidence[0].text
        assert "2400" in required[0].evidence[0].text
        assert "该项已核验" in rendered
    else:
        assert required[0].status != "met" and not required[0].evidence
        assert "2400" not in rendered and "9,999" not in rendered
    # A previously passing matrix is never borrowed after an edit.
    assert baseline.management_overview is not None


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_unmapped_questions_and_no_requirements_do_not_guess_business_values(tmp_path):
    _, _, index, markdown, sources, questions, _ = await case(tmp_path)
    quality = evaluate(index, markdown, sources, questions, None)
    assert all(row.status == "unknown" for row in quality.management_overview.rows)
    absent = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash="c" * 64)
    assert absent.management_overview.status == "unavailable"
    assert absent.management_overview.required_question_count is None
    assert not absent.management_overview.rows


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_editor_recomputes_overview_after_scope_edit_and_restore(tmp_path):
    editor, context, index, markdown, sources, questions, plan = await case(tmp_path)
    quality = evaluate(index, markdown, sources, questions, plan)
    context = await register_quality(editor, context, index, quality)
    for text, expected in [(markdown, "met"), (markdown.replace("北院", "南院"), "unknown"), (markdown, "met")]:
        actual = await editor.trace.validate(context, text, hashlib.sha256(text.encode()).hexdigest())
        matrix = actual["quality"]["managementOverview"]
        assert matrix["inputSha256"] == actual["quality"]["inputSha256"]
        assert matrix["rows"][0]["status"] == expected


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_optional_overview_failure_preserves_quality_and_sources(tmp_path, monkeypatch):
    from smart_reporting.reporting.trace import quality_bundle

    _, _, index, markdown, sources, questions, plan = await case(tmp_path)

    def unavailable(*args):
        raise RuntimeError("overview unavailable")

    monkeypatch.setattr(quality_bundle, "build_management_overview", unavailable)
    quality = evaluate(index, markdown, sources, questions, plan)
    assert quality.assertions[0].status == "supported"
    assert quality.question_coverage["answered"] == 1
    assert quality.management_overview.status == "unavailable"
    assert any(issue.code == "management_overview_unavailable" for issue in quality.issues)
