import hashlib

import pytest

from smart_reporting.reporting.tests.test_trace_subject_validate import _make_editor_with_subject
from smart_reporting.reporting.trace.quality_bundle import (
    evaluate_quality_bundle,
    quality_bundle_is_current,
)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize(
    "fault", ["none", "missing", "tampered", "wrong_pointer", "wrong_scope", "wrong_period", "draft"]
)
async def test_shadow_quality_does_not_borrow_other_sources_or_self_sign_a_statement(
    tmp_path, fault
):
    statement = {
        "wrong_scope": "2025年10月南院收入", "wrong_period": "2025年9月北院收入",
    }.get(fault, "2025年10月北院收入")
    editor, _, context = await _make_editor_with_subject(
        tmp_path,
        period_table=True,
        include_table=False,
        number_reference=True,
        metric_scope={"院区": "北院"},
        number_statement=statement + "{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:万元}}。",
    )
    index = await editor.trace.require_index(context)
    markdown = (
        await editor.trace._read_registered_file(
            context,
            next(
                file for file in index.files if file.resource_id == index.markdown_file_resource_id
            ),
            max_bytes=16 * 1024 * 1024,
        )
    ).decode()
    sources = {
        file.resource_id: await editor.trace._read_registered_file(
            context, file, max_bytes=16 * 1024 * 1024
        )
        for file in index.files
        if file.media_type == "application/json"
    }
    if fault == "missing":
        sources.clear()
    elif fault == "tampered":
        sources = {key: raw + b" " for key, raw in sources.items()}
    elif fault == "draft":
        markdown = markdown.replace("北院", "南院")
    elif fault == "wrong_pointer":
        subject = index.subject_bindings[0]
        index = index.model_copy(
            update={
                "subject_bindings": (
                    subject.model_copy(
                        update={
                            "fact_refs": (
                                subject.fact_refs[0].model_copy(
                                    update={"json_pointer": "/metrics/99"}
                                ),
                            ),
                        }
                    ),
                )
            }
        )
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash="c" * 64)
    assert quality.all_key_facts_evaluated is False
    assert quality.markdown_sha256 == hashlib.sha256(markdown.encode()).hexdigest()
    assert quality_bundle_is_current(quality, index, markdown, input_sha256=quality.input_sha256)
    assert not quality_bundle_is_current(quality, index, markdown, input_sha256="f" * 64)
    if fault == "none":
        assert quality.assertions[0].status == "supported"
        assert not quality.issues
    else:
        assert quality.issues
    if fault in {"missing", "tampered", "wrong_pointer", "draft"}:
        assert not quality.assertions
    if fault in {"wrong_scope", "wrong_period"}:
        issue = next(issue for issue in quality.issues if "statement_not_supported" in issue.reasons)
        assert issue.statement_review is not None
        assert issue.statement_review.numeric_status == "valid"
        expected = "登记范围 院区=北院" if fault == "wrong_scope" else "期间"
        assert any(expected in warning for warning in issue.statement_review.warnings)
        assert quality.semantic_rule_versions["statementReview"] == "1"


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_chapter_count_has_no_fixed_quality_limit(tmp_path):
    editor, _, context = await _make_editor_with_subject(tmp_path, include_table=False)
    index = await editor.trace.require_index(context)
    markdown = "# 封面\n\n" + "\n\n".join(f"## 未编号主题{i}" for i in range(11))
    quality = evaluate_quality_bundle(index, markdown, {}, authorization_scope_hash="c" * 64)
    assert not any(issue.code == "report_chapter_limit_exceeded" for issue in quality.issues)
    markdown = "# 封面\n\n## 目录\n\n" + "\n\n".join(f"## 主题{i}" for i in range(10))
    quality = evaluate_quality_bundle(index, markdown, {}, authorization_scope_hash="c" * 64)
    assert not any(issue.code == "report_chapter_limit_exceeded" for issue in quality.issues)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_question_evidence_allocation_never_counts_as_reviewed_answer(tmp_path):
    from smart_reporting.reporting.workflow.questions import (
        freeze_analysis_questions,
        request_questions,
    )

    editor, _, context = await _make_editor_with_subject(
        tmp_path,
        period_table=True,
        include_table=False,
        number_reference=True,
        metric_scope={"院区": "北院"},
        number_statement="2025年10月北院收入{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:万元}}。",
    )
    index = await editor.trace.require_index(context)
    raw = {
        file.resource_id: await editor.trace._read_registered_file(
            context, file, max_bytes=16 * 1024 * 1024
        )
        for file in index.files
    }
    markdown = raw[index.markdown_file_resource_id].decode()
    analysis_id = index.fact_files[0].analysis_id
    questions = freeze_analysis_questions(
        request_questions("收入是多少，为什么变化"),
        [
            {
                "analysisId": analysis_id,
                "managementQuestion": "本期收入多少",
                "completionConditions": ["本期收入"],
            }
        ],
    )
    bundle = evaluate_quality_bundle(
        index, markdown, raw, authorization_scope_hash="c" * 64, questions=questions
    )
    assert bundle.question_assertions[questions.analysis_to_question[analysis_id]]
    assert bundle.question_coverage["answered"] == 0
    assert bundle.question_coverage["effectiveAnswerRate"] is None
    assert bundle.question_coverage["evaluated"] == 0
    changed = freeze_analysis_questions(
        request_questions("收入变化的业务原因"),
        [
            {
                "analysisId": analysis_id,
                "managementQuestion": "本期收入多少",
                "completionConditions": ["本期收入"],
            }
        ],
    )
    new_bundle = evaluate_quality_bundle(
        index, markdown, raw, authorization_scope_hash="c" * 64, questions=changed
    )
    assert new_bundle.input_sha256 != bundle.input_sha256
    assert not quality_bundle_is_current(
        bundle, index, markdown, input_sha256=new_bundle.input_sha256
    )


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize(
    "kind",
    [
        "single_comparison",
        "multi_comparison",
        "monthly_average",
        "group_share",
        "stock_share",
        "collision_share",
        "group_rank",
        "stock_rank",
        "collision_rank",
        "flow_trend",
        "stock_trend",
        "mixed_trend",
    ],
)
async def test_shadow_comparison_recomputes_dependencies_for_current_statement(
    tmp_path, monkeypatch, kind
):
    import json

    from smart_reporting.reporting.tests.test_assertion_compiler import comparison_document, token
    from smart_reporting.reporting.trace.assertions import assertion_catalog
    from smart_reporting.reporting.trace.semantic_bindings import (
        anchor_bound_numbers,
        render_bound_numbers,
    )

    editor, _, context = await _make_editor_with_subject(tmp_path, include_table=False)
    index = await editor.trace.require_index(context)
    if kind == "single_comparison":
        document = comparison_document()
        selected_token = token("c", selector="change")
        fact_kind, pointer, fact_id, operation = (
            "comparison",
            "/comparisons/0",
            "fact-" + "c" * 16,
            "difference",
        )
        original_scope, edited_scope = "北院", "南院"
    elif kind in {
        "group_share",
        "stock_share",
        "collision_share",
        "group_rank",
        "stock_rank",
        "collision_rank",
    }:
        from smart_reporting.reporting.tests.test_group_share_assertions import (
            group_bundle,
            share_token,
        )

        document = json.loads(
            group_bundle(
                stock=kind in {"stock_share", "stock_rank"},
                collision=kind in {"collision_share", "collision_rank"},
            ).model_dump_json(by_alias=True)
        )
        fact_kind, pointer, fact_id, operation = (
            "metric",
            "/metrics/0",
            document["metrics"][0]["factId"],
            "group_rank" if kind.endswith("rank") else "share",
        )
        selected_token = (
            f"{{{{value:{fact_id}:topGroups.0:元}}}}"
            if kind.endswith("rank")
            else share_token(fact_id)
        )
        original_scope, edited_scope = (
            ("department=内 / 科", "department=外")
            if kind in {"collision_share", "collision_rank"}
            else ("department=内科", "department=外科")
        )
    elif kind.endswith("trend"):
        from smart_reporting.reporting.tests.test_monthly_trend_assertions import trend_bundle

        document = json.loads(
            trend_bundle(
                (10, 40, 30) if kind == "mixed_trend" else (10, 20, 30),
                stock=kind == "stock_trend",
            ).model_dump_json(by_alias=True)
        )
        fact_kind, pointer, fact_id, operation = (
            "metric",
            "/metrics/0",
            document["metrics"][0]["factId"],
            "monthly_trend",
        )
        selected_token = f"{{{{value:{fact_id}:monthlyTrend:元}}}}"
        original_scope, edited_scope = "department=A", "department=B"
    else:
        from smart_reporting.reporting.tests.test_frozen_time_aggregation import frozen_bundle

        document = json.loads(
            frozen_bundle(comparison=kind == "multi_comparison").model_dump_json(by_alias=True)
        )
        monthly_average = kind == "monthly_average"
        fact_kind, pointer = (
            ("metric", "/metrics/0") if monthly_average else ("comparison", "/comparisons/0")
        )
        fact_id = document["metrics" if monthly_average else "comparisons"][0]["factId"]
        operation = "monthly_average" if monthly_average else "difference"
        selector = "monthlyAverage" if monthly_average else "change"
        selected_token = f"{{{{value:{fact_id}:{selector}:元}}}}"
        original_scope, edited_scope = "department=A", "department=B"
    raw = json.dumps(document, ensure_ascii=False).encode()
    records = assertion_catalog(
        [raw.decode()],
        profile_hash="a" * 64,
        authorization_scope_hash="c" * 64,
        allowed_tokens=[selected_token],
    )
    (assertion,) = records.values()
    markdown, references, notices = render_bound_numbers(
        "{{assert:" + assertion.assertion_id + "}}",
        [raw.decode()],
        key="quality",
        assertions=records,
    )
    markdown = anchor_bound_numbers(markdown, references, notices)
    subject = index.subject_bindings[0]
    subject = subject.model_copy(
        update={
            "claim_id": references[0].claim_id,
            "number_reference": references[0],
            "fact_refs": (
                subject.fact_refs[0].model_copy(
                    update={
                        "fact_kind": fact_kind,
                        "json_pointer": pointer,
                        "fact_key": fact_id,
                    }
                ),
            ),
        }
    )
    resource = index.fact_files[0].file_resource_id
    files = tuple(
        file.model_copy(update={"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        if file.resource_id == resource
        else file
        for file in index.files
    )
    index = index.model_copy(
        update={"files": files, "subject_bindings": (subject,), "profile_hash": "a" * 64}
    )
    bundle = evaluate_quality_bundle(
        index, markdown, {resource: raw}, authorization_scope_hash="c" * 64
    )
    assert bundle.assertions[0].status == "supported"
    assert bundle.assertions[0].request.operation == operation
    assert bundle.assertions[0].assertion_id == assertion.assertion_id
    assert not bundle.issues
    # The live editor reads the same hash-checked frozen bytes and recomputes;
    # no capability or prior pass record is supplied by the browser.
    from unittest.mock import AsyncMock

    registered = next(file for file in files if file.resource_id == resource)
    await editor.trace._workspace.awrite_bytes(
        context.scope["threadId"], registered.path, raw, overwrite=True
    )
    monkeypatch.setattr(editor.trace, "require_index", AsyncMock(return_value=index))
    validation = await editor.trace.validate(
        context, markdown, hashlib.sha256(markdown.encode()).hexdigest()
    )
    assert validation["quality"]["status"] == "evaluated"
    assert validation["quality"]["issues"] == []
    assert validation["sourceIssues"] == []
    edited = evaluate_quality_bundle(
        index,
        markdown.replace(original_scope, edited_scope),
        {resource: raw},
        authorization_scope_hash="c" * 64,
    )
    assert edited.issues and not edited.assertions
    if kind.endswith("rank") or kind.endswith("trend"):
        from smart_reporting.reporting.trace.semantic_bindings import statement_fingerprint

        # Re-freezing a changed statement cannot turn a wrong rank into a
        # supported sentence merely because its amount still matches.
        wrong_rank = (
            markdown.replace("属于混合变化", "逐月严格上升")
            if kind == "mixed_trend"
            else markdown.replace("逐月严格上升", "逐月严格下降")
            if kind.endswith("trend")
            else markdown.replace("第1名", "第2名")
        )
        refreshed_number = references[0].model_copy(
            update={
                "statement_sha256": statement_fingerprint(wrong_rank, references[0].claim_id),
            }
        )
        refreshed_subject = subject.model_copy(update={"number_reference": refreshed_number})
        refreshed_index = index.model_copy(update={"subject_bindings": (refreshed_subject,)})
        changed = evaluate_quality_bundle(
            refreshed_index,
            wrong_rank,
            {resource: raw},
            authorization_scope_hash="c" * 64,
        )
        assert changed.issues and "statement_not_supported" in changed.issues[0].reasons
        assert "statement_changed" not in changed.issues[0].reasons
        monkeypatch.setattr(editor.trace, "require_index", AsyncMock(return_value=refreshed_index))
        validation = await editor.trace.validate(
            context, wrong_rank, hashlib.sha256(wrong_rank.encode()).hexdigest()
        )
        assert validation["quality"]["issues"]


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('fault', ['none', 'missing', 'tampered'])
async def test_registered_table_calculation_is_reviewed_without_blanket_unknown(tmp_path, fault):
    from smart_reporting.reporting.tests.test_trace_subject_validate import (
        _make_editor_with_table_derivation,
    )
    editor, context, _, _ = await _make_editor_with_table_derivation(tmp_path)
    index = await editor.trace.require_index(context)
    raw = {file.resource_id: await editor.trace._read_registered_file(context, file, max_bytes=16*1024*1024)
           for file in index.files}
    markdown = raw[index.markdown_file_resource_id].decode()
    source_id = index.subject_bindings[0].number_reference.table_derivation.operands[0].file_resource_id
    if fault == 'missing':
        raw.pop(source_id)
    elif fault == 'tampered':
        raw[source_id] += b' '
    quality = evaluate_quality_bundle(index, markdown, raw, authorization_scope_hash='c'*64)
    issues = [issue for issue in quality.issues if issue.subject_id == index.subject_bindings[0].subject_id]
    if fault == 'none':
        assert not issues
    else:
        assert issues and 'source_unavailable' in issues[0].reasons
