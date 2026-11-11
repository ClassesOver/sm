"""独立复读整组必填：只允许字段 Ff 的 Required 位切换。"""
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
    original_flags = int(old_field["/Ff"])
    assert not original_flags & 2 and len(old_widgets) == 2
    checks = []
    for label, required in (("required", True), ("optional", False), ("filled", False)):
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
        assert int(field["/Ff"]) == (original_flags | 2 if required else original_flags)
        assert [canonical(ref) for ref, _ in widgets] == [canonical(ref) for ref, _ in old_widgets]
        assert [str(v) for v in field["/Opt"]] == ["Yes", "No"]
        assert canonical(field.get("/DV")) == canonical(old_field.get("/DV"))
        assert str(all_fields["party.code"][1]["/V"]) == "C001"
        on_names = [next(k for k in widget["/AP"]["/N"] if k != "/Off") for _, widget in widgets]
        selected = on_names[1] if label == "filled" else on_names[0]
        assert str(field["/V"]) == selected
        assert [str(widget["/AS"]) for _, widget in widgets] == [on if on == selected else "/Off" for on in on_names]
        if label != "filled":
            assert reader.xref.keys() == baseline.xref.keys()
            for generation, objects in baseline.xref.items():
                assert reader.xref[generation].keys() == objects.keys()
                for number in objects:
                    if number == 0:
                        continue
                    before = baseline.get_object(IndirectObject(number, generation, baseline))
                    after = reader.get_object(IndirectObject(number, generation, reader))
                    if (number, generation) == (old_ref.idnum, old_ref.generation):
                        before = {k: v for k, v in before.items() if k != "/Ff"}
                        after = {k: v for k, v in after.items() if k != "/Ff"}
                    assert canonical(after) == canonical(before), (number, generation)
        checks.append({"label": label, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "required": required,
                       "selected": "No" if label == "filled" else "Yes", "widgetCount": len(widgets),
                       "onlyRequiredBitChanged": label != "filled", "survivingRefsPreserved": True, "bodyPreserved": True})
    return {"ok": True, "sourceSha256": hashlib.sha256((directory / "source.pdf").read_bytes()).hexdigest(), "checks": checks}


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1]))))
