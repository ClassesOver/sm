"""发现身份、范围及章节覆盖契约。"""

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.hospital_operation.narrative_outline import (
    NarrativeOutlineCandidate,
    freeze_narrative_outline,
)
from smart_reporting.reporting.tests.narrative_helpers import finding, graph


def candidate(*groups, **changes):
    return NarrativeOutlineCandidate(title="医院运营分析", snapshotHash="b" * 64,
        sections=[{"title": f"经营变化{index}", "findingIds": ids,
                   "objective": "解释经营变化", "groupingReason": "共同管理问题"}
                  for index, ids in enumerate(groups)], **changes)


def freeze(value, cards):
    return freeze_narrative_outline(value, graph=graph(*cards),
        analyses=[{"analysisId": aid} for card in cards for aid in card.analysis_ids])


def test_sections_derive_analysis_identity_and_number_from_findings():
    cards = [finding(1), finding(2)]
    result = freeze(candidate([card.finding_id for card in cards]), cards)
    assert result.sections[0].code == "section_001"
    assert result.sections[0].section_number == "1"
    assert result.sections[0].analysis_ids == ("analysis_001", "analysis_002")


@pytest.mark.parametrize("groups", [(["finding_0000000000000001"], ["finding_0000000000000001"]),
                                     (["finding_ffffffffffffffff"],)])
def test_unknown_or_repeated_finding_is_rejected(groups):
    with pytest.raises(ValueError):
        freeze(candidate(*groups), [finding()])


def test_high_priority_finding_cannot_be_silently_omitted():
    with pytest.raises(ValueError, match="遗漏"):
        freeze(candidate([finding().finding_id]), [finding(), finding(2)])


def test_low_priority_appendix_has_explicit_destination():
    cards = [finding(), finding(2, priority="low")]
    result = freeze(candidate([cards[0].finding_id], appendixFindingIds=[cards[1].finding_id]), cards)
    assert result.appendix_finding_ids == (cards[1].finding_id,)


def test_low_priority_appendix_is_materialized_as_visible_appendix_section():
    cards = [finding(), finding(2, priority="low")]
    result = freeze(candidate([cards[0].finding_id], appendixFindingIds=[cards[1].finding_id]), cards)
    appendix = result.sections[-1]
    assert appendix.narrative_role == "appendix"
    assert appendix.finding_ids == (cards[1].finding_id,)
    assert appendix.title.startswith("附录")


@pytest.mark.parametrize("changes", [
    {"periodEnd": "2025-10-31"}, {"grain": ["科室"]}, {"scope": {"income_nature": "开单"}},
])
def test_incompatible_fact_scopes_cannot_be_merged(changes):
    cards = [finding(), finding(2, **changes)]
    with pytest.raises(ValueError, match="口径"):
        freeze(candidate([card.finding_id for card in cards]), cards)


def test_graph_rejects_unregistered_relationship():
    with pytest.raises(ValueError):
        graph(finding(relatedFindingIds=["finding_ffffffffffffffff"]))


def test_identity_requires_source_and_rejects_nonfinite_value():
    with pytest.raises(ValidationError):
        finding(sourceRefs=[])
    with pytest.raises(ValidationError):
        finding(impactValue=float("nan"))


def test_outline_cannot_change_snapshot():
    value = candidate([finding().finding_id]).model_copy(update={"snapshot_hash": "c" * 64})
    with pytest.raises(ValueError, match="快照"):
        freeze(value, [finding()])


@pytest.mark.parametrize("omitted", [
    [{"findingId": "finding_ffffffffffffffff", "reason": "影响较小"}],
    [{"findingId": "finding_0000000000000001", "reason": "影响较小"}],
    [{"findingId": "finding_0000000000000002"}],
    [{"findingId": "finding_0000000000000002", "reason": "   "}],
    [{"reason": "影响较小"}],
    [{"findingId": "finding_0000000000000002", "reason": "影响较小"}] * 2,
])
def test_omissions_require_unique_known_findings_and_explicit_reason(omitted):
    cards = [finding(), finding(2, priority="low")]
    with pytest.raises(ValueError, match="忽略"):
        freeze(candidate([cards[0].finding_id], omittedFindings=omitted), cards)


def test_low_priority_finding_can_be_omitted_with_reason():
    cards = [finding(), finding(2, priority="low")]
    omitted = [{"findingId": cards[1].finding_id, "reason": "对经营影响较小，正文已覆盖主要发现"}]
    result = freeze(candidate([cards[0].finding_id], omittedFindings=omitted), cards)
    assert result.omitted_findings == tuple(omitted)


def test_high_priority_finding_cannot_be_hidden_in_appendix_section():
    value = candidate([finding().finding_id])
    value = value.model_copy(update={"sections": (
        value.sections[0].model_copy(update={"narrative_role": "appendix"}),
    )})
    with pytest.raises(ValueError, match="高优先级"):
        freeze(value, [finding()])


def test_new_narrative_outline_is_limited_to_ten_sections_including_appendix():
    cards = [finding(index) for index in range(1, 12)]
    ten = candidate(*[[card.finding_id] for card in cards[:10]])
    assert len(freeze(ten, cards[:10]).sections) == 10
    with pytest.raises(ValidationError):
        candidate(*[[card.finding_id] for card in cards])
    cards[-1] = finding(11, priority="low")
    with pytest.raises(ValueError, match="最多 10"):
        freeze(candidate(*[[card.finding_id] for card in cards[:10]],
                         appendixFindingIds=[cards[-1].finding_id]), cards)
