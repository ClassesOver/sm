"""独立复读实际下载的单选组改名、状态、外观原始流及字段树引用。"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from pypdf import PdfReader
from pypdf.generic import IndirectObject, StreamObject


def canonical(value):
    if isinstance(value, IndirectObject):
        return ["ref", value.idnum, value.generation]
    if isinstance(value, StreamObject):
        return [canonical(dict(value)), hashlib.sha256(value._data).hexdigest(), hashlib.sha256(value.get_data()).hexdigest()]
    if isinstance(value, dict):
        return [[str(k), canonical(v)] for k, v in sorted(value.items())]
    if isinstance(value, list):
        return [canonical(v) for v in value]
    return repr(value)


def fields(reader):
    result, seen = {}, set()

    def walk(refs, parent=None, prefix=""):
        siblings = set()
        for ref in refs:
            key = (ref.idnum, ref.generation)
            assert key not in seen
            seen.add(key)
            node = ref.get_object()
            part = str(node["/T"])
            assert part and "." not in part and part not in siblings
            siblings.add(part)
            assert canonical(node.raw_get("/Parent")) == canonical(parent) if parent else "/Parent" not in node
            name = prefix + part
            if "/FT" not in node:
                walk(node["/Kids"], ref, name + ".")
            else:
                widgets = []
                for widget_ref in node["/Kids"]:
                    widget = widget_ref.get_object()
                    assert canonical(widget.raw_get("/Parent")) == canonical(ref)
                    occurrences = [(i, entry) for i, page in enumerate(reader.pages) for entry in page.get("/Annots", []) if canonical(entry) == canonical(widget_ref)]
                    assert len(occurrences) == 1
                    assert canonical(widget.raw_get("/P")) == canonical(reader.pages[occurrences[0][0]].indirect_reference)
                    widgets.append((widget_ref, widget))
                result[name] = (ref, node, widgets)

    walk(reader.trailer["/Root"]["/AcroForm"]["/Fields"])
    return result


def verify(directory):
    source = PdfReader(directory / "source.pdf")
    baseline, checks = None, []
    for label in ("code", "renamed", "filled"):
        path = directory / f"{label}-downloaded.pdf"
        reader = PdfReader(path)
        assert len(reader.pages) == len(source.pages)
        for actual, original in zip(reader.pages, source.pages):
            assert actual.extract_text() == original.extract_text()
            assert original.get_contents().get_data() in actual.get_contents().get_data()
            assert list(actual.mediabox) == list(original.mediabox)
            assert list(actual.cropbox) == list(original.cropbox)
            assert actual.rotation == original.rotation
        name = "party.answer" if label == "code" else "party.renamedAnswer"
        all_fields = fields(reader)
        assert list(all_fields) == [name, "party.code"]
        ref, field, widgets = all_fields[name]
        assert field["/FT"] == "/Btn" and field.get("/Ff", 0) & 32768
        assert bool(field.get("/Ff", 0) & 2) and len(widgets) == 2
        options = [str(value) for value in field["/Opt"]]
        assert options == ["Yes", "No"]
        selected = "No" if label == "filled" else "Yes"
        on_names = []
        for _, widget in widgets:
            states = widget["/AP"]["/N"]
            on = [key for key in states if key != "/Off"]
            assert len(on) == 1
            on_names.append(on[0])
            for key in widget["/AP"]:
                appearances = widget["/AP"][key]
                assert set(appearances) == {"/Off", on[0]}
                for stream in appearances.values():
                    assert isinstance(stream, IndirectObject) and stream.get_object().get_data()
        assert len(set(on_names)) == 2
        assert field["/V"] == on_names[options.index(selected)]
        assert [str(widget["/AS"]) for _, widget in widgets] == [str(on) if option == selected else "/Off" for option, on in zip(options, on_names)]
        invariant = {"fieldRef": canonical(ref), "field": canonical({k: v for k, v in field.items() if k not in ("/T", "/V")}),
                     "widgets": [[canonical(wref), canonical({k: v for k, v in widget.items() if k not in ("/AS", "/AP")})] for wref, widget in widgets],
                     "other": canonical(all_fields["party.code"][1]),
                     "annots": [canonical(page.get("/Annots", [])) for page in reader.pages],
                     "parents": canonical(reader.trailer["/Root"]["/AcroForm"]["/Fields"])}
        if baseline is None:
            baseline = invariant
        else:
            assert invariant == baseline
        if label == "renamed":
            before = PdfReader(directory / "code-downloaded.pdf")
            assert reader.xref.keys() == before.xref.keys()
            for generation, objects in before.xref.items():
                assert objects.keys() == reader.xref[generation].keys()
                for number in objects:
                    if number == 0:
                        continue
                    old = before.get_object(IndirectObject(number, generation, before))
                    new = reader.get_object(IndirectObject(number, generation, reader))
                    if number == ref.idnum:
                        old = {k: v for k, v in old.items() if k != "/T"}
                        new = {k: v for k, v in new.items() if k != "/T"}
                    assert canonical(old) == canonical(new), (number, generation)
        checks.append({"label": label, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "name": name, "selected": selected,
                       "widgetCount": len(widgets), "bodyPreserved": True, "treeAndReferencesPreserved": True,
                       "renameRawObjectsAndAppearancePreserved": label == "renamed"})
    return {"ok": True, "sourceSha256": hashlib.sha256((directory / "source.pdf").read_bytes()).hexdigest(), "checks": checks}


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1]))))
