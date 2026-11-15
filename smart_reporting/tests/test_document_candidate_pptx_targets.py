import pytest

from smart_reporting.document_candidate_pptx_targets import validate_pptx_selection


def test_pptx_valid_targets():
    validate_pptx_selection((
        {"slide_id": 256, "shape_id": 2},
        {"slide_id": 257, "shape_id": 2},
    ))


@pytest.mark.parametrize("target", [
    {"slide_id": True, "shape_id": 2},
    {"slide_id": 256, "shape_id": False},
    {"slide_id": 0, "shape_id": 2},
    {"slide_id": 256, "shape_id": -1},
    {"slide_id": "256", "shape_id": 2},
    {"slide_id": 256, "shape_id": 2, "xml": "<a/>"},
    {"slide_id": 256},
    {"slide_id": 2**31, "shape_id": 2},
])
def test_pptx_invalid_targets(target):
    with pytest.raises(ValueError, match="pptx_target_invalid"):
        validate_pptx_selection((target,))


def test_pptx_duplicate_targets_rejected():
    with pytest.raises(ValueError, match="pptx_target_duplicate"):
        validate_pptx_selection((
            {"slide_id": 256, "shape_id": 2},
            {"slide_id": 256, "shape_id": 2},
        ))
