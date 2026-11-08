"""Bounded saved sticky-note mutation keeps exact source identity and other PDF objects."""

from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from smart_reporting.reporting.delivery.pdf_native import (
    inspect_pdf,
    patch_pdf,
    patch_pdf_with_receipt,
)
from smart_reporting.reporting.tests.test_pdf_native_text_edits import source_pdf, text_operation
from smart_reporting.reporting.tests.test_pdf_selection_markup import markup_source, operation

WHEN = "2026-11-06T13:00:00Z"


def note_operation(source, kind="editNote", contents="已复核 金额 750 ✓"):
    page = inspect_pdf(source)["pages"][0]
    note = page["notes"][0]
    return {
        "kind": kind,
        "pageId": page["pageId"],
        "annotationId": note["annotationId"],
        "expectedAnnotationSha256": note["expectedAnnotationSha256"],
        **({"contents": contents, "modifiedAt": WHEN} if kind == "editNote" else {}),
    }


def rewrite(source, mutate):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(source)))
    mutate(writer)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def note_dict(reader):
    return next(
        item.get_object()
        for item in reader.pages[0]["/Annots"]
        if item.get_object().get("/Subtype") == "/Text"
    )


def test_edit_in_place_changes_only_contents_date_and_has_repeatable_preview_bytes():
    source = markup_source()
    source = patch_pdf(source, [operation(source)])
    op = note_operation(source)
    receipt = patch_pdf_with_receipt(source, [op])
    again = patch_pdf_with_receipt(source, [op])
    assert (
        receipt["content"] == again["content"]
        and receipt["previewDigest"] == again["previewDigest"]
    )
    before, after = PdfReader(BytesIO(source)), PdfReader(BytesIO(receipt["content"]))
    old, new = note_dict(before), note_dict(after)
    assert new["/Contents"] == op["contents"] and new["/M"] == "D:20261106130000Z"

    def canonical(value):
        if isinstance(value, IndirectObject):
            return (value.idnum, value.generation)
        if isinstance(value, dict):
            return {k: canonical(v) for k, v in value.items()}
        if isinstance(value, list):
            return [canonical(v) for v in value]
        return value

    assert canonical({k: v for k, v in old.items() if k not in ["/Contents", "/M"]}) == canonical(
        {k: v for k, v in new.items() if k not in ["/Contents", "/M"]}
    )
    for old_page, new_page in zip(before.pages, after.pages, strict=True):
        assert old_page.get_contents().get_data() == new_page.get_contents().get_data()
        assert old_page.extract_text() == new_page.extract_text()
    assert {k: v.get("/V") for k, v in before.get_fields().items()} == {
        k: v.get("/V") for k, v in after.get_fields().items()
    }
    old_mark = before.pages[0]["/Annots"][-1].get_object()
    new_mark = after.pages[0]["/Annots"][-1].get_object()
    assert old_mark["/AP"]["/N"].get_data() == new_mark["/AP"]["/N"].get_data()
    assert inspect_pdf(receipt["content"])["pages"][0]["notes"][0]["contents"] == op["contents"]
    with pytest.raises(ValueError):
        patch_pdf(receipt["content"], [op])


def test_delete_note_keeps_widget_and_markup_and_composes_under_reorder():
    source = markup_source()
    source = patch_pdf(source, [operation(source)])
    ids = [p["pageId"] for p in inspect_pdf(source)["pages"]]
    result = patch_pdf(
        source,
        [
            note_operation(source, "removeNote"),
            {"kind": "rotatePage", "pageId": ids[0], "delta": 90},
            {"kind": "deletePage", "pageId": ids[1]},
            {"kind": "reorderPages", "pageIds": [ids[2], ids[0]]},
        ],
    )
    model = inspect_pdf(result)
    assert len(model["pages"]) == 2 and model["pages"][1]["rotation"] == 90
    assert not model["pages"][1]["notes"] and len(model["pages"][1]["markups"]) == 1
    assert PdfReader(BytesIO(result)).get_fields()["contact"]["/V"] == "original"


@pytest.mark.parametrize(
    "change",
    [
        {"annotationId": "0" * 64},
        {"expectedAnnotationSha256": "0" * 64},
        {"sourceSha256": "0" * 64},
        {"contents": ""},
        {"contents": "x" * 10001},
        {"modifiedAt": "invalid"},
        {"modifiedAt": "2026-11-06T13:00:00.123Z"},
        {"rect": [1, 2, 3, 4]},
    ],
)
def test_bad_saved_note_edit_is_rejected_before_output(change):
    source = markup_source()
    with pytest.raises(ValueError):
        patch_pdf(source, [{**note_operation(source), **change}])
    assert inspect_pdf(source)["pages"][0]["notes"][0]["contents"] == "keep note"


@pytest.mark.parametrize(
    "protection", ["reply", "popup", "rich", "locked", "direct", "shared", "perms", "malformed"]
)
def test_linked_rich_locked_shared_and_unreadable_notes_stay_readonly(protection):
    def mutate(w):
        annots = w.pages[0]["/Annots"]
        ref = next(item for item in annots if item.get_object().get("/Subtype") == "/Text")
        note = ref.get_object()
        if protection == "reply":
            annots.append(
                w._add_object(
                    DictionaryObject(
                        {
                            NameObject("/Subtype"): NameObject("/Text"),
                            NameObject("/IRT"): ref,
                            NameObject("/Contents"): TextStringObject("reply"),
                        }
                    )
                )
            )
        elif protection == "popup":
            note[NameObject("/Popup")] = ref
        elif protection == "rich":
            note[NameObject("/RC")] = TextStringObject("<p>rich</p>")
        elif protection == "locked":
            note[NameObject("/F")] = NumberObject(64)
        elif protection == "direct":
            annots[annots.index(ref)] = note
        elif protection == "shared":
            w.pages[1].setdefault(NameObject("/Annots"), ArrayObject()).append(ref)
        elif protection == "perms":
            w.root_object[NameObject("/Perms")] = DictionaryObject()
        else:
            note[NameObject("/Contents")] = DictionaryObject()

    source = rewrite(markup_source(), mutate)
    page = inspect_pdf(source)["pages"][0]
    if protection == "malformed":
        assert not page["notesReadSafe"]
    else:
        assert not page["notes"][0]["editable"]
        for kind in ["editNote", "removeNote"]:
            with pytest.raises(ValueError):
                patch_pdf(source, [note_operation(source, kind)])


def test_duplicate_or_conflicting_note_mutations_refuse_whole_batch():
    source = markup_source()
    op = note_operation(source)
    for operations in [
        [op, op],
        [op, note_operation(source, "removeNote")],
        [op, {"kind": "deletePage", "pageId": op["pageId"]}],
        [op, {**op, "annotationId": "0" * 64}],
    ]:
        with pytest.raises(ValueError):
            patch_pdf(source, operations)


def test_note_edit_and_text_rewrite_keep_both_requested_changes():
    source = source_pdf()
    page = inspect_pdf(source)["pages"][0]
    source = patch_pdf(
        source,
        [
            {
                "kind": "addTextAnnotation",
                "pageId": page["pageId"],
                "rect": [30, 100, 50, 118],
                "text": "original note",
            }
        ],
    )
    result = patch_pdf(source, [note_operation(source), text_operation(source, "Amount due 750")])
    assert inspect_pdf(result)["pages"][0]["notes"][0]["contents"] == "已复核 金额 750 ✓"
    text = PdfReader(BytesIO(result)).pages[0].extract_text()
    assert "Amount due 750" in text and "UNCHANGED CONTROL" in text


def test_same_geometry_and_contents_have_distinct_note_identities():
    def duplicate(w):
        annots = w.pages[0]["/Annots"]
        original = next(
            item.get_object() for item in annots if item.get_object().get("/Subtype") == "/Text"
        )
        annots.append(w._add_object(DictionaryObject(original)))

    source = rewrite(markup_source(), duplicate)
    page = inspect_pdf(source)["pages"][0]
    first, second = page["notes"]
    assert (
        first["annotationId"] != second["annotationId"] and first["contents"] == second["contents"]
    )
    op = {
        **note_operation(source),
        "annotationId": second["annotationId"],
        "expectedAnnotationSha256": second["expectedAnnotationSha256"],
    }
    assert [n["contents"] for n in inspect_pdf(patch_pdf(source, [op]))["pages"][0]["notes"]] == [
        "keep note",
        op["contents"],
    ]


def test_malformed_note_census_rejects_forced_identity_requests():
    source = markup_source()
    original = note_operation(source)
    malformed = rewrite(
        source, lambda w: note_dict(w).__setitem__(NameObject("/Contents"), DictionaryObject())
    )
    page = inspect_pdf(malformed)["pages"][0]
    assert not page["notesReadSafe"]
    with pytest.raises(ValueError):
        patch_pdf(malformed, [{**original, "pageId": page["pageId"]}])


def test_raw_xfa_census_precedes_pdf_lib_get_form_side_effect():
    from pypdf.generic import DecodedStreamObject

    def attach(w):
        xfa = DecodedStreamObject()
        xfa.set_data(b"<xdp><template/></xdp>")
        w.root_object["/AcroForm"][NameObject("/XFA")] = w._add_object(xfa)

    source = rewrite(markup_source(), attach)
    model = inspect_pdf(source)
    assert not model["pages"][0]["notes"][0]["editable"]
    assert not model["capabilities"]["pageSize"]
    assert all(not field["editable"] for field in model["formFields"])
    for kind in ["editNote", "removeNote"]:
        with pytest.raises(ValueError):
            patch_pdf(source, [note_operation(source, kind)])
    assert (
        PdfReader(BytesIO(source)).trailer["/Root"]["/AcroForm"]["/XFA"].get_data()
        == b"<xdp><template/></xdp>"
    )
