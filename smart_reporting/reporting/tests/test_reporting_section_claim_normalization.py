from __future__ import annotations

from types import SimpleNamespace

from smart_reporting.reporting.tools.sections import RuntimeSectionsMixin


def _chart(chart_id: str, *, comparison_type: str = "none") -> SimpleNamespace:
    return SimpleNamespace(
        chart_id=chart_id,
        citation_ids=("citation_001",),
        current_period="2026-08",
        comparison_period=None,
        comparison_type=comparison_type,
        comparability="strict",
    )


def _work_item(*charts: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        metric_definitions=(SimpleNamespace(code="revenue", period_basis="月度"),),
        charts=charts,
        citations=(SimpleNamespace(citation_id="citation_001"),),
        management_question_catalog=(SimpleNamespace(ref="analysis_001", question="收入如何？"),),
    )


def _claim(**overrides: object) -> dict[str, object]:
    return {
        "claimId": "claim_001",
        "metricCode": "revenue",
        "value": 1,
        "managementQuestionRef": "analysis_001",
        "citationIds": ["citation_999"],
        "chartIds": ["chart_001"],
        **overrides,
    }


def test_claim_with_wrong_citation_keeps_chart_frozen_citation_anchor() -> None:
    claims, warnings = RuntimeSectionsMixin._normalize_section_claims(
        section_code="section_001",
        claims=[_claim()],
        work_item=_work_item(_chart("chart_001")),
    )

    assert [claim.citation_ids for claim in claims] == [("citation_001",)]
    codes = [item["code"] for item in warnings]
    assert "report_section_claim_citation_unknown" in codes
    assert "report_section_claim_citation_missing" not in codes


def test_claim_without_any_verifiable_citation_is_still_omitted() -> None:
    claims, warnings = RuntimeSectionsMixin._normalize_section_claims(
        section_code="section_001",
        claims=[_claim(chartIds=[])],
        work_item=_work_item(_chart("chart_001")),
    )

    assert claims == ()
    assert warnings[-1]["code"] == "report_section_claim_citation_missing"


def test_chart_semantics_conflict_only_unbinds_conflicting_charts() -> None:
    claims, warnings = RuntimeSectionsMixin._normalize_section_claims(
        section_code="section_001",
        claims=[
            _claim(citationIds=["citation_001"], chartIds=["chart_001", "chart_002", "chart_003"])
        ],
        work_item=_work_item(
            _chart("chart_001"),
            _chart("chart_002", comparison_type="yoy"),
            _chart("chart_003"),
        ),
    )

    assert claims[0].chart_ids == ("chart_001", "chart_003")
    conflict = next(
        item for item in warnings if item["code"] == "report_section_claim_chart_semantics_conflict"
    )
    assert conflict["details"]["unboundChartIds"] == ["chart_002"]
