"""Actual pending-note preview bytes and trustworthy/unknown creation dates."""

from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject

from smart_reporting.reporting.delivery.pdf_native import inspect_pdf, patch_pdf_with_receipt
from smart_reporting.reporting.tests.test_pdf_saved_notes import note_operation
from smart_reporting.reporting.tests.test_pdf_selection_markup import markup_source, operation

CREATED = 1793970000123


def addition(source, created=CREATED, page=0, text="预览便签 750 ✓"):
    op = {
        "kind": "addTextAnnotation",
        "pageId": inspect_pdf(source)["pages"][page]["pageId"],
        "rect": [30, 100, 50, 118],
        "text": text,
    }
    if created is not None:
        op["createdMs"] = created
    return op


def source_with_existing_date():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(markup_source())))
    note = next(
        a.get_object()
        for a in writer.pages[0]["/Annots"]
        if a.get_object().get("/Subtype") == "/Text"
    )
    note[NameObject("/CreationDate")] = TextStringObject("D:20100101000000Z")
    note[NameObject("/M")] = TextStringObject("D:20110101000000Z")
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.mark.parametrize("created", [CREATED, None])
def test_preview_bytes_digest_and_dates_ignore_wall_clock_and_timezone(
    monkeypatch, tmp_path, created
):
    source = source_with_existing_date()
    op = addition(source, created)
    outputs = []
    for index, zone in enumerate(["UTC", "Asia/Tokyo", "America/Los_Angeles"]):
        clock = tmp_path / f"clock-{index}.mjs"
        clock.write_text(
            "const OriginalDate=Date; globalThis.Date=class extends OriginalDate { constructor(...args){super(...(args.length?args:["
            + str(1262304000000 + index * 315360000000)
            + "]));} static now(){return "
            + str(1262304000000 + index * 315360000000)
            + ";} };"
        )
        monkeypatch.setenv("TZ", zone)
        monkeypatch.setenv("NODE_OPTIONS", f"--import={clock}")
        outputs.append(patch_pdf_with_receipt(source, [op]))
    assert len({r["previewDigest"] for r in outputs}) == 1
    assert len({r["content"] for r in outputs}) == 1
    before, after = PdfReader(BytesIO(source)), PdfReader(BytesIO(outputs[0]["content"]))
    old_note, new_note = [
        a.get_object()
        for a in after.pages[0]["/Annots"]
        if a.get_object().get("/Subtype") == "/Text"
    ]
    assert (
        old_note["/CreationDate"] == "D:20100101000000Z" and old_note["/M"] == "D:20110101000000Z"
    )
    assert new_note["/Contents"] == op["text"] and new_note["/AP"]["/N"].get_data()
    if created is None:
        assert "/CreationDate" not in new_note and "/M" not in new_note
    else:
        assert new_note["/CreationDate"] == new_note["/M"] == "D:20261106130000Z"
    for old, new in zip(before.pages, after.pages, strict=True):
        assert old.get_contents().get_data() == new.get_contents().get_data()
        assert old.extract_text() == new.extract_text()
    assert {k: v.get("/V") for k, v in before.get_fields().items()} == {
        k: v.get("/V") for k, v in after.get_fields().items()
    }


@pytest.mark.parametrize("created", [-1, 0.5, 253402300800000, "invalid", None])
def test_invalid_explicit_creation_time_refuses_before_output(created):
    source = markup_source()
    with pytest.raises(ValueError):
        patch_pdf_with_receipt(source, [{**addition(source), "createdMs": created}])


@pytest.mark.parametrize(
    ("created", "expected"), [(0, "D:19700101000000Z"), (253402300799999, "D:99991231235959Z")]
)
def test_supported_creation_time_extremes_are_canonical(created, expected):
    source = markup_source()
    result = patch_pdf_with_receipt(source, [addition(source, created)])
    note = PdfReader(BytesIO(result["content"])).pages[0]["/Annots"][-1].get_object()
    assert note["/CreationDate"] == note["/M"] == expected


def test_note_dates_compose_with_existing_note_edit_markup_form_crop_reorder_and_delete():
    source = markup_source()
    model = inspect_pdf(source)
    ids = [p["pageId"] for p in model["pages"]]
    field = next(field for field in model["formFields"] if field["name"] == "contact")
    operations = [
        {"kind": "cropPage", "pageId": ids[0], "rect": [20, 30, 380, 470]},
        addition(source),
        addition(source, None, 1, "legacy unknown"),
        operation(source),
        note_operation(source, contents="existing edited"),
        {
            "kind": "setFormValue",
            "name": "contact",
            "fieldId": field["fieldId"],
            "fieldKind": "text",
            "expectedFieldSha256": field["expectedFieldSha256"],
            "value": "Ada",
        },
        {"kind": "rotatePage", "pageId": ids[1], "delta": 90},
        {"kind": "deletePage", "pageId": ids[2]},
        {"kind": "reorderPages", "pageIds": [ids[1], ids[0]]},
    ]
    result = patch_pdf_with_receipt(source, operations)
    reader = PdfReader(BytesIO(result["content"]))
    assert len(reader.pages) == 2 and reader.get_fields()["contact"]["/V"] == "Ada"
    notes = [
        [
            a.get_object()
            for a in page.get("/Annots", [])
            if a.get_object().get("/Subtype") == "/Text"
        ]
        for page in reader.pages
    ]
    assert notes[0][-1]["/Contents"] == "legacy unknown" and "/CreationDate" not in notes[0][-1]
    assert (
        notes[1][-1]["/CreationDate"] == "D:20261106130000Z"
        and notes[1][0]["/Contents"] == "existing edited"
    )
    assert list(reader.pages[1].cropbox) == [20, 30, 380, 470]
    assert result["appliedOperationIndices"] == list(range(len(operations)))


def test_note_date_survives_final_paper_transform():
    source = markup_source()
    result = patch_pdf_with_receipt(
        source, [addition(source), {"kind": "setPageSize", "preset": "A4"}]
    )
    note = PdfReader(BytesIO(result["content"])).pages[0]["/Annots"][-1].get_object()
    assert note["/CreationDate"] == "D:20261106130000Z" and note["/Contents"] == "预览便签 750 ✓"


def test_fractional_placement_uses_pinned_two_decimal_rect_quantization():
    source = markup_source()
    operation = {**addition(source), "rect": [30.123456, 100.123456, 50.123456, 118.123456]}
    result = patch_pdf_with_receipt(source, [operation])
    note = PdfReader(BytesIO(result["content"])).pages[0]["/Annots"][-1].get_object()
    assert [float(value) for value in note["/Rect"]] == [30.12, 100.12, 50.12, 118.12]
    assert note["/CreationDate"] == "D:20261106130000Z"


def test_shared_indirect_annots_cannot_append_new_note_to_an_untargeted_page():
    writer = PdfWriter(clone_from=PdfReader(BytesIO(markup_source())))
    shared = writer._add_object(writer.pages[0]["/Annots"])
    writer.pages[0][NameObject("/Annots")] = shared
    writer.pages[1][NameObject("/Annots")] = shared
    out = BytesIO()
    writer.write(out)
    source = out.getvalue()
    with pytest.raises(ValueError, match="pdf_added_note_append_count_changed"):
        patch_pdf_with_receipt(source, [addition(source)])
    reader = PdfReader(BytesIO(source))
    assert len(reader.pages[0]["/Annots"]) == len(reader.pages[1]["/Annots"])


def test_new_note_preview_composes_with_actual_text_replacement():
    from smart_reporting.reporting.tests.test_pdf_native_text_edits import (
        source_pdf,
        text_operation,
    )

    source = source_pdf()
    result = patch_pdf_with_receipt(
        source, [addition(source), text_operation(source, "Amount due 750")]
    )
    reader = PdfReader(BytesIO(result["content"]))
    assert "Amount due 750" in reader.pages[0].extract_text()
    assert reader.pages[0]["/Annots"][-1].get_object()["/CreationDate"] == "D:20261106130000Z"
