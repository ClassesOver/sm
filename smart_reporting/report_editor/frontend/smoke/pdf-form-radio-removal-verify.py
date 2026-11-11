"""独立复读单选按钮逻辑删除：仅 Kids/Opt/Annots 及目标 Widget 移除。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from pypdf import PdfReader
from pypdf.generic import IndirectObject

spec = importlib.util.spec_from_file_location("radio_name_verify", Path(__file__).with_name("pdf-form-radio-name-verify.py"))
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
canonical, fields = shared.canonical, shared.fields


def verify(directory):
    source = PdfReader(directory / "source.pdf")
    baseline = PdfReader(directory / "code-downloaded.pdf")
    old_ref, old_field, old_widgets = fields(baseline)["party.answer"]
    removed_ref, removed_widget = old_widgets[1]
    assert [str(v) for v in old_field["/Opt"]] == ["Yes", "No", "Maybe"]
    assert len(old_widgets) == 3
    old_field["/Kids"].pop(1)
    old_field["/Opt"].pop(1)
    for page in baseline.pages:
        annots = page.get("/Annots", [])
        for index in reversed(range(len(annots))):
            if canonical(annots[index]) == canonical(removed_ref):
                annots.pop(index)
    surviving_refs = [canonical(ref) for ref, _ in (old_widgets[0], old_widgets[2])]
    checks = []
    for label in ("removed", "filled"):
        path = directory / f"{label}-downloaded.pdf"
        reader = PdfReader(path)
        assert len(reader.pages) == len(source.pages)
        for actual, original in zip(reader.pages, source.pages):
            assert actual.extract_text() == original.extract_text()
            assert original.get_contents().get_data() in actual.get_contents().get_data()
            assert list(actual.mediabox) == list(original.mediabox)
            assert list(actual.cropbox) == list(original.cropbox)
            assert actual.rotation == original.rotation
        all_fields = fields(reader)
        assert list(all_fields) == ["party.answer", "party.code"]
        ref, field, widgets = all_fields["party.answer"]
        assert canonical(ref) == canonical(old_ref)
        assert [canonical(ref) for ref, _ in widgets] == surviving_refs
        assert [str(v) for v in field["/Opt"]] == ["Yes", "Maybe"]
        assert canonical(field.get("/DV")) == canonical(old_field.get("/DV"))
        assert str(all_fields["party.code"][1]["/V"]) == "C001"
        on_names = [next(k for k in widget["/AP"]["/N"] if k != "/Off") for _, widget in widgets]
        assert on_names == ["/0", "/2"]
        selected = "/0" if label == "removed" else "/2"
        assert str(field["/V"]) == selected
        assert [str(widget["/AS"]) for _, widget in widgets] == [on if on == selected else "/Off" for on in on_names]
        assert not any(canonical(entry) == canonical(removed_ref) for page in reader.pages for entry in page.get("/Annots", []))
        assert not any(number == removed_ref.idnum and generation == removed_ref.generation for generation, objects in reader.xref.items() for number in objects)
        if label == "removed":
            assert reader.xref.keys() == baseline.xref.keys()
            for generation, objects in baseline.xref.items():
                assert set(reader.xref[generation]) == set(objects) - ({removed_ref.idnum} if generation == removed_ref.generation else set())
                for number in objects:
                    if number == 0 or (number, generation) == (removed_ref.idnum, removed_ref.generation):
                        continue
                    before = baseline.get_object(IndirectObject(number, generation, baseline))
                    after = reader.get_object(IndirectObject(number, generation, reader))
                    assert canonical(after) == canonical(before), (number, generation)
        checks.append({"label": label, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "widgetCount": len(widgets),
                       "selected": "Yes" if label == "removed" else "Maybe", "survivingRefsPreserved": True,
                       "rawObjectsAndAppearancePreservedExceptExactRemoval": label == "removed", "bodyPreserved": True})
    return {"ok": True, "logicalRemovalOnly": True, "sourceSha256": hashlib.sha256((directory / "source.pdf").read_bytes()).hexdigest(), "checks": checks}


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1]))))
