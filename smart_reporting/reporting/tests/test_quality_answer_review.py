"""Current report proofs drive approved answer criteria, including editor rechecks."""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath

import pytest

from smart_reporting.reporting.trace.contracts_v1 import (
    TraceFileRefV1,
    canonical_json_bytes,
    derive_resource_id,
)
from smart_reporting.reporting.trace.quality_bundle import QUALITY_FILENAME, evaluate_quality_bundle
from smart_reporting.reporting.workflow.answer_review import (
    AnswerCriterion,
    AnswerReviewPlan,
    questions_sha256,
)
from smart_reporting.reporting.workflow.questions import (
    freeze_analysis_questions,
    request_questions,
)
from smart_reporting.reporting.workflow.state import apply

from .lineage_fixtures.manifest import register_trace_manifest
from .test_reporting_state import initial_state
from .test_trace_subject_validate import _make_editor_with_subject


async def case(tmp_path, scope_wording="北院"):
    editor, _, context = await _make_editor_with_subject(
        tmp_path,
        period_table=True,
        include_table=False,
        number_reference=True,
        metric_scope={"院区": "北院"},
        number_statement="2025年10月" + scope_wording + "收入{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:万元}}。",
    )
    index = await editor.trace.require_index(context)
    sources = {
        file.resource_id: await editor.trace._read_registered_file(
            context, file, max_bytes=16 * 1024 * 1024
        )
        for file in index.files
    }
    markdown = sources[index.markdown_file_resource_id].decode()
    questions = freeze_analysis_questions(
        request_questions("2025年10月北院收入多少"),
        [
            {
                "analysisId": index.fact_files[0].analysis_id,
                "managementQuestion": "本期收入多少",
                "completionConditions": ["收入已核验"],
            }
        ],
    )
    observed = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash="c" * 64)
    assert len(observed.assertions) == 1 and observed.assertions[0].status == "supported"
    # This test is the trusted approval integration. Production does not derive
    # natural-language requirement mappings automatically from observed proofs.
    plan = AnswerReviewPlan(
        questionSetSha256=questions_sha256(questions),
        criteria=(
            AnswerCriterion(
                questionId=questions.required_question_ids[0],
                condition=questions.questions[0].completion_conditions[0],
                request=observed.assertions[0].request,
                subjectIds=(next(iter(observed.subject_assertions)),),
            ),
        ),
    )
    return editor, context, index, markdown, sources, questions, plan


def evaluate(index, markdown, sources, questions, plan):
    return evaluate_quality_bundle(
        index,
        markdown,
        sources,
        authorization_scope_hash="c" * 64,
        questions=questions,
        answer_review_plan=plan,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("wording", ["非北院", "不含北院的", "北院之外"])
async def test_registered_mapping_cannot_approve_a_statement_excluding_its_scope(tmp_path, wording):
    _, _, index, markdown, sources, questions, plan = await case(tmp_path, wording)
    current = evaluate(index, markdown, sources, questions, plan)
    # The source and arithmetic remain usable; the frozen prose contradicts scope.
    assert current.assertions[0].status == "supported"
    issue = next(issue for issue in current.issues if "statement_not_supported" in issue.reasons)
    assert issue.statement_review.numeric_status == "valid"
    assert any("登记范围 院区=北院" in warning for warning in issue.statement_review.warnings)
    assert current.question_coverage["answered"] == 0
    assert current.answer_review.conditions[0].status == "unknown"
    assert current.management_overview.rows[0].status == "unknown"
    assert current.semantic_rule_versions["scopeWording"] == "1"


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("change", ["none", "scope", "delete", "value", "source", "wrong_selector"])
async def test_quality_answer_review_only_accepts_current_exact_statement_and_selector(
    tmp_path, change
):
    _, _, index, markdown, sources, questions, plan = await case(tmp_path)
    first = evaluate(index, markdown, sources, questions, plan)
    assert first.question_coverage["effectiveAnswerRate"] == 1
    assert first.answer_review.conditions[0].status == "met"
    assert first.answer_review.input_sha256 == first.input_sha256
    if change == "scope":
        markdown = markdown.replace("北院", "南院")
    elif change == "delete":
        markdown = "# 报告\n\n原句已删除。"
    elif change == "value":
        assert "2,400" in markdown
        markdown = markdown.replace("2,400", "9,999")
    elif change == "source":
        sources[index.fact_files[0].file_resource_id] += b" "
    elif change == "wrong_selector":
        request = plan.criteria[0].request.model_copy(
            update={"operands": ("{{value:fact-aaaaaaaaaaaaaaaa:periodValues.0:万元}}",)}
        )
        plan = plan.model_copy(
            update={"criteria": (plan.criteria[0].model_copy(update={"request": request}),)}
        )
    current = evaluate(index, markdown, sources, questions, plan)
    if change == "none":
        assert current.question_coverage["effectiveAnswerRate"] == 1
    else:
        assert current.question_coverage["answered"] == 0
        assert current.answer_review.conditions[0].status in {"not_met", "unknown"}
        assert first.input_sha256 != current.input_sha256
        assert any(issue.code == "answer_condition_unverified" for issue in current.issues)
    if change == "wrong_selector":
        # Arithmetic support for another field is not evidence for this criterion.
        assert current.assertions[0].status == "supported"
        assert current.question_coverage["effectiveAnswerRate"] == 0


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_bad_review_plan_does_not_erase_independent_factual_proofs(tmp_path):
    _, _, index, markdown, sources, questions, plan = await case(tmp_path)
    bad = plan.model_copy(update={"question_set_sha256": "f" * 64})
    current = evaluate(index, markdown, sources, questions, bad)
    assert current.answer_review is None
    assert current.question_coverage["effectiveAnswerRate"] is None
    assert current.assertions[0].status == "supported"
    assert current.subject_assertions
    assert any(issue.code == "answer_review_unavailable" for issue in current.issues)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_bad_review_plan_does_not_erase_independent_chart_checks(tmp_path):
    from .test_chart_quality_bundle import chart_case

    _, _, _, index, markdown, sources, _ = await chart_case(tmp_path)
    questions = request_questions("核验图表数据")
    bad = AnswerReviewPlan(questionSetSha256="f" * 64)
    independent = evaluate_quality_bundle(
        index, markdown, sources, authorization_scope_hash="c" * 64,
    ).chart_checks
    current = evaluate_quality_bundle(
        index,
        markdown,
        sources,
        authorization_scope_hash="c" * 64,
        questions=questions,
        answer_review_plan=bad,
    )
    assert current.answer_review is None
    assert independent and current.chart_checks == independent


async def register_quality(editor, context, index, quality):
    path = PurePosixPath(context.markdown_path).with_name(QUALITY_FILENAME).as_posix()
    raw = canonical_json_bytes(quality.model_dump(mode="json", by_alias=True))
    workspace = editor.trace._workspace
    await workspace.awrite_bytes(context.scope["threadId"], path, raw, overwrite=True)
    entry = TraceFileRefV1(
        resourceId=derive_resource_id(path),
        path=path,
        mediaType="application/json",
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    index = index.model_copy(update={"files": (*index.files, entry)})
    index_path = PurePosixPath(context.markdown_path).with_name("trace-index-v1.json").as_posix()
    await workspace.awrite_bytes(
        context.scope["threadId"],
        index_path,
        canonical_json_bytes(index.model_dump(mode="json", by_alias=True)),
        overwrite=True,
    )
    manifest = await register_trace_manifest(
        workspace, context.scope["threadId"], index, overwrite=True
    )
    return context.model_copy(update={"artifact_manifest": manifest})


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_editor_carries_approved_plan_but_never_historical_passing_review(tmp_path):
    editor, context, index, markdown, sources, questions, plan = await case(tmp_path)
    historical = evaluate(index, markdown, sources, questions, plan)
    assert historical.question_coverage["answered"] == 1
    context = await register_quality(editor, context, index, historical)
    actual_index = await editor.trace.require_index(context)
    assert any(file.path.endswith(QUALITY_FILENAME) for file in actual_index.files)
    first = await editor.trace.validate(
        context, markdown, hashlib.sha256(markdown.encode()).hexdigest()
    )
    assert first["quality"]["questionCoverage"]["answered"] == 1
    changed = markdown.replace("北院", "南院")
    current = await editor.trace.validate(
        context, changed, hashlib.sha256(changed.encode()).hexdigest()
    )
    assert current["quality"]["status"] == "evaluated"
    assert current["quality"]["questionCoverage"]["answered"] == 0
    assert current["quality"]["questionCoverage"]["effectiveAnswerRate"] is None
    assert current["quality"]["inputSha256"] != first["quality"]["inputSha256"]
    assert current["quality"]["answerReview"]["conditions"][0]["status"] == "unknown"


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_actual_quality_review_can_be_frozen_and_recorded_through_state_cas(tmp_path):
    _, _, index, markdown, sources, questions, plan = await case(tmp_path)
    state = initial_state()
    analysis_ids = list(questions.analysis_to_question)
    for name, payload in (
        (
            "set_analysis_plan",
            {
                "analysisIds": analysis_ids,
                "analysisPlans": {
                    aid: {"questionId": questions.analysis_to_question[aid]} for aid in analysis_ids
                },
                "questionSpecs": questions.model_dump(mode="json", by_alias=True),
            },
        ),
        ("freeze_answer_review_plan", {"plan": plan.model_dump(mode="json", by_alias=True)}),
    ):
        state = apply(
            state, {"name": name, "commandId": name, "payload": payload}, state.state_version
        ).state
    restored = type(state).model_validate_json(state.model_dump_json(by_alias=True))
    registered_plan = AnswerReviewPlan.model_validate(restored.payload["answerReviewPlan"])
    current = evaluate(index, markdown, sources, questions, registered_plan)
    recorded = apply(
        restored,
        {
            "name": "record_answer_review",
            "commandId": "record-review",
            "payload": {
                "revision": restored.revision,
                "review": current.answer_review.model_dump(mode="json", by_alias=True),
            },
        },
        restored.state_version,
    )
    key = f"{restored.revision}:{current.input_sha256}"
    assert recorded.state.payload["answerReviews"][key]["conditions"][0]["status"] == "met"
    replay = apply(
        recorded.state,
        {"name": "record_answer_review", "commandId": "record-review", "payload": {}},
        recorded.state.state_version,
    )
    assert replay.idempotent
    assert replay.state.state_version == recorded.state.state_version


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("fault", ["review", "coverage"])
async def test_answer_checker_fault_preserves_frozen_denominator_and_independent_proofs(
    tmp_path, monkeypatch, fault
):
    from smart_reporting.reporting.trace import quality_bundle
    from smart_reporting.reporting.workflow.answer_review import AnswerReviewResult

    _, _, index, markdown, sources, questions, plan = await case(tmp_path)

    def unavailable(*_args, **_kwargs):
        raise OSError("injected checker failure")

    if fault == "review":
        monkeypatch.setattr(quality_bundle, "evaluate_answer_review", unavailable)
    else:
        monkeypatch.setattr(AnswerReviewResult, "coverage", unavailable)
    result = evaluate(index, markdown, sources, questions, plan)
    assert result.assertions[0].status == "supported"
    assert result.question_coverage["required"] == len(questions.required_question_ids)
    assert result.question_coverage["effectiveAnswerRate"] is None
    assert result.question_coverage["evaluationStatus"] == "review_unavailable"
    assert result.answer_review is None
    assert any(issue.code == "answer_review_unavailable" for issue in result.issues)
