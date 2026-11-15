import pytest

from smart_reporting.document_candidate_xlsx_targets import validate_xlsx_selection


@pytest.mark.parametrize("cell", ["A1", "Z99", "XFD1048576", "$B$2", "A1:B20"])
def test_valid_xlsx_targets(cell):
    validate_xlsx_selection(({"sheet": "Sheet1", "range": cell},))


@pytest.mark.parametrize("cell", [
    "A0", "XFE1", "A1048577", "A-1", "A1:B0", "B2:A1",
    "A1:B2:C3", "Sheet1!A1", "a1", "A1;DROP", "A1\nB2",
])
def test_invalid_xlsx_targets(cell):
    with pytest.raises(ValueError):
        validate_xlsx_selection(({"sheet": "Sheet1", "range": cell},))


@pytest.mark.parametrize("sheet", ["", "A" * 32, "Bad/Name", "'Sheet", "Sheet'", "Bad\nName"])
def test_invalid_xlsx_sheet_names(sheet):
    with pytest.raises(ValueError, match="xlsx_sheet_invalid"):
        validate_xlsx_selection(({"sheet": sheet, "range": "A1"},))


def test_xlsx_rejects_unknown_selection_fields():
    with pytest.raises(ValueError, match="xlsx_target_invalid"):
        validate_xlsx_selection(({"sheet": "Sheet1", "range": "A1", "formula": "=1+1"},))
