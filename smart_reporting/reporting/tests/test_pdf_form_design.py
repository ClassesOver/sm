from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject
from reportlab.pdfgen.canvas import Canvas

from smart_reporting.reporting.delivery.pdf_form_design import (
    inspect_pdf_design_widgets,
    remove_pdf_design_widget,
)


def form_pdf():
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(300, 400))
    canvas.drawString(20, 350, "unchanged body")
    canvas.acroForm.textfield(name="remove_me", x=20, y=200, width=120, height=24, value="Alice")
    canvas.acroForm.checkbox(name="keep", x=20, y=150, size=20)
    canvas.showPage()
    canvas.save()
    # ReportLab merges the field and widget dictionaries; the first adapter milestone
    # deliberately supports separate single-widget fields only. Build that real PDF shape.
    writer = PdfWriter(clone_from=PdfReader(BytesIO(stream.getvalue())))
    fields = writer._root_object["/AcroForm"]["/Fields"]
    field_keys = {"/FT", "/T", "/V", "/DV", "/Ff", "/MaxLen", "/DA"}
    for index, widget_ref in enumerate(list(fields)):
        widget = widget_ref.get_object()
        field = DictionaryObject({NameObject(key): widget.pop(key) for key in field_keys if key in widget})
        field[NameObject("/Kids")] = ArrayObject([widget_ref])
        field_ref = writer._add_object(field)
        widget[NameObject("/Parent")] = field_ref
        fields[index] = field_ref
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


def test_form_design_bridge_removes_exact_widget_with_verified_output_identity():
    content = form_pdf()
    census = inspect_pdf_design_widgets(content)
    target = next(widget for widget in census["widgets"] if widget["fieldName"] == "remove_me")
    assert target["removable"] is True
    receipt = remove_pdf_design_widget(content, target)
    output = PdfReader(BytesIO(receipt["content"]))
    assert set(output.get_fields()) == {"keep"}
    assert len(output.pages[0]["/Annots"]) == 1
    assert output.pages[0].extract_text() == PdfReader(BytesIO(content)).pages[0].extract_text()
    assert receipt["sourceSha256"] == hashlib.sha256(content).hexdigest()
    assert receipt["sha256"] == hashlib.sha256(receipt["content"]).hexdigest()
    assert receipt["size"] == len(receipt["content"])
    assert set(PdfReader(BytesIO(content)).get_fields()) == {"remove_me", "keep"}


def test_form_design_bridge_refuses_forged_dictionary_digest():
    content = form_pdf()
    target = inspect_pdf_design_widgets(content)["widgets"][0]
    with pytest.raises(ValueError):
        remove_pdf_design_widget(content, {**target, "expectedWidgetSha256": "0" * 64})


@pytest.mark.parametrize("field", ["sourceSha256", "sha256", "size"])
def test_form_design_bridge_rejects_tampered_actual_output_receipt(monkeypatch, field):
    from smart_reporting.reporting.delivery import pdf_form_design

    content = form_pdf()
    target = inspect_pdf_design_widgets(content)["widgets"][0]
    original_invoke = pdf_form_design._invoke

    def tamper(payload, root):
        receipt = original_invoke(payload, root)
        return {**receipt, field: 0 if field == "size" else "0" * 64}

    monkeypatch.setattr(pdf_form_design, "_invoke", tamper)
    with pytest.raises(ValueError, match="pdf_form_design_output_identity_invalid"):
        remove_pdf_design_widget(content, target)


def test_form_design_census_rejects_tampered_actual_source_receipt(monkeypatch):
    from smart_reporting.reporting.delivery import pdf_form_design

    original_invoke = pdf_form_design._invoke

    def tamper(payload, root):
        return {**original_invoke(payload, root), "sourceSha256": "0" * 64}

    monkeypatch.setattr(pdf_form_design, "_invoke", tamper)
    with pytest.raises(ValueError, match="pdf_form_design_source_identity_invalid"):
        inspect_pdf_design_widgets(form_pdf())
