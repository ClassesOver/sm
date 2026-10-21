"""Current editor and durable quality checks share finite business evidence."""

import hashlib
import json
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.trace.assertions import assertion_catalog
from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle
from smart_reporting.reporting.trace.semantic_bindings import (
    anchor_bound_numbers,
    render_bound_numbers,
    statement_fingerprint,
)

from .test_calendar_comparison_assertions import calendar_document
from .test_cumulative_assertions import cumulative_document
from .test_group_contribution_assertions import contribution_document
from .test_group_share_assertions import group_bundle
from .test_monthly_trend_assertions import trend_bundle
from .test_registered_ratio_assertions import ratio_document
from .test_trace_subject_validate import _make_editor_with_subject


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize(
    "kind",
    [
        "top",
        "shape",
        "rate",
        "cause",
        "predict",
        "significance",
        "contribution",
        "contribution_denominator",
        "calendar_day",
        "calendar_year",
        "calendar_year_bare",
        "calendar_relation",
        "ratio_numerator",
        "ratio_denominator",
        "ratio_average",
        "ratio_window",
        "ratio_subset",
        "ratio_cumulative",
        "cumulative_reset",
        "cumulative_flow",
        "cumulative_caveat",
        "cumulative_baseline",
        "cumulative_point_flow",
    ],
)
async def test_current_business_statement_is_not_self_signed_by_unchanged_number(
    tmp_path, monkeypatch, kind
):
    editor, _, context = await _make_editor_with_subject(tmp_path, include_table=False)
    index = await editor.trace.require_index(context)
    bundle = (
        group_bundle(weights=(100, 90, 90, 80))
        if kind == "top"
        else trend_bundle((10, 30, 20) if kind == "shape" else (100, 200, 310))
    )
    document = json.loads(bundle.model_dump_json(by_alias=True))
    is_contribution = kind.startswith("contribution")
    if is_contribution:
        document = contribution_document()
    is_calendar = kind.startswith("calendar")
    if is_calendar:
        document = calendar_document("year" if kind.startswith("calendar_year") else "day")
    is_comparison = is_contribution or is_calendar
    is_ratio = kind.startswith("ratio_")
    if is_ratio:
        document = ratio_document()
    is_cumulative = kind.startswith("cumulative_")
    if is_cumulative:
        document = cumulative_document()
    fact_array = "derivedMetrics" if is_ratio else "comparisons" if is_comparison else "metrics"
    fact_id = document[fact_array][0]["factId"]
    selector = "topSet.rank.2" if kind == "top" else "monthlyTrend"
    if is_calendar:
        selector = "changeRate"
    if is_contribution:
        selector = "groupContributions.0"
    if is_ratio:
        selector = "registeredRatio"
    if is_cumulative:
        selector = ("total" if kind == "cumulative_point_flow" else "cumulativeChanges.2"
                    if kind == "cumulative_baseline" else "cumulativeChanges.1")
    display_unit = "元/人次" if is_ratio else "%" if is_comparison else "元"
    token = f"{{{{value:{fact_id}:{selector}:{display_unit}}}}}"
    raw = json.dumps(document, ensure_ascii=False).encode()
    records = assertion_catalog(
        [raw.decode()],
        profile_hash="a" * 64,
        authorization_scope_hash="c" * 64,
        allowed_tokens=[token],
    )
    assert len(records) == 1
    assertion = next(iter(records.values()))
    assert assertion.status == "supported", assertion.reasons
    markdown, refs, notices = render_bound_numbers(
        "{{assert:" + assertion.assertion_id + "}}",
        [raw.decode()],
        key="business",
        assertions=records,
    )
    markdown = anchor_bound_numbers(markdown, refs, notices)
    subject = index.subject_bindings[0]
    resource = index.fact_files[0].file_resource_id
    subject = subject.model_copy(
        update={
            "claim_id": refs[0].claim_id,
            "number_reference": refs[0],
            "fact_refs": (
                subject.fact_refs[0].model_copy(
                    update={
                        "fact_kind": "derived"
                        if is_ratio
                        else "comparison"
                        if is_comparison
                        else "metric",
                        "json_pointer": f"/{fact_array}/0",
                        "fact_key": fact_id,
                    }
                ),
            ),
        }
    )
    index = index.model_copy(
        update={
            "profile_hash": "a" * 64,
            "subject_bindings": (subject,),
            "files": tuple(
                file.model_copy(
                    update={"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                )
                if file.resource_id == resource
                else file
                for file in index.files
            ),
        }
    )
    registered = next(file for file in index.files if file.resource_id == resource)
    await editor.trace._workspace.awrite_bytes(
        context.scope["threadId"], registered.path, raw, overwrite=True
    )
    monkeypatch.setattr(editor.trace, "require_index", AsyncMock(return_value=index))
    original = await editor.trace.validate(
        context, markdown, hashlib.sha256(markdown.encode()).hexdigest()
    )
    assert original["quality"]["issues"] == [], json.dumps(original, ensure_ascii=False)
    if kind == "cumulative_point_flow":
        changed = "当月业务流量为，" + markdown
    elif kind == "cumulative_reset":
        changed = markdown.replace("按自然年重置零基线", "以上年末快照为基线")
    elif kind == "cumulative_baseline":
        changed = markdown.replace("以2025-01月末累计快照为基线", "以2024-12月末累计快照为基线")
    elif kind == "cumulative_flow":
        changed = "当月业务新增为，" + markdown
    elif kind == "cumulative_caveat":
        changed = markdown.replace("不等同当期业务流量", "等同当期业务流量")
    elif kind == "ratio_cumulative":
        changed = "年初至今累计比率，" + markdown
    elif kind == "ratio_numerator":
        changed = markdown.replace("分子（amount）", "分子（visits）")
    elif kind == "ratio_denominator":
        changed = markdown.replace("分母（visits）", "分母（amount）")
    elif kind == "ratio_average":
        changed = markdown.replace("同期分子总量除以同期分母总量", "各期比率求平均")
    elif kind == "ratio_window":
        changed = markdown.replace("2025-01至2025-02", "2025-02至2025-02")
    elif kind == "ratio_subset":
        changed = "占比为，" + markdown
    elif kind == "calendar_day":
        changed = markdown.replace("基期2024-01-01", "基期2024-01-02")
    elif kind == "calendar_year_bare":
        changed = markdown.replace("基期2023年", "基期2022")
    elif kind == "calendar_year":
        changed = markdown.replace("基期2023年", "基期2022年")
    elif kind == "calendar_relation":
        changed = markdown.replace("同比", "环比")
    elif kind == "contribution":
        changed = markdown.replace("科室01", "伪造分组")
    elif kind == "contribution_denominator":
        changed = markdown.replace("有符号净差额", "净差额绝对值")
    elif kind == "top":
        changed = markdown.replace("科室00", "伪造成员")
    elif kind == "shape":
        changed = markdown.replace("唯一峰值月份=2025-02", "唯一峰值月份=2025-01")
    elif kind == "rate":
        changed = markdown.replace("相对变化率严格下降", "相对变化率严格上升")
    else:
        words = {
            "cause": "政策导致增长，",
            "predict": "预计未来继续增长，",
            "significance": "统计显著增长，",
        }
        changed = markdown.replace("期末记录值为", words[kind] + "期末记录值为")
    assert changed != markdown
    # Remove mere edit/fingerprint detection as an explanation: the actual
    # semantic statement must still fail even after a trusted new freeze.
    updated_ref = refs[0].model_copy(
        update={"statement_sha256": statement_fingerprint(changed, refs[0].claim_id)}
    )
    index = index.model_copy(
        update={"subject_bindings": (subject.model_copy(update={"number_reference": updated_ref}),)}
    )
    monkeypatch.setattr(editor.trace, "require_index", AsyncMock(return_value=index))
    quality = evaluate_quality_bundle(
        index, changed, {resource: raw}, authorization_scope_hash="c" * 64
    )
    assert quality.assertions[0].status == "supported"  # Arithmetic alone is insufficient.
    assert any("statement_not_supported" in issue.reasons for issue in quality.issues)
    validation = await editor.trace.validate(
        context, changed, hashlib.sha256(changed.encode()).hexdigest()
    )
    assert validation["quality"]["issues"]
    assert validation["subjects"][0]["warnings"]
