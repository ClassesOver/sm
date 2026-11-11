"""独立 pypdf 检查实际下载的字段叶子改名、外观及字段树引用。"""
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
        return [canonical(dict(value)), hashlib.sha256(value.get_data()).hexdigest()]
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
                assert node["/FT"] == "/Tx" and len(node["/Kids"]) == 1
                widget_ref = node["/Kids"][0]
                widget = widget_ref.get_object()
                assert canonical(widget.raw_get("/Parent")) == canonical(ref)
                assert canonical(widget.raw_get("/P")) == canonical(reader.pages[0].indirect_reference)
                result[name] = (ref, node, widget_ref, widget)

    walk(reader.trailer["/Root"]["/AcroForm"]["/Fields"])
    return result


def verify(directory):
    source = PdfReader(directory / "source.pdf")
    baseline, checks = None, []
    for label in ("code", "renamed", "filled"):
        path = directory / f"{label}-downloaded.pdf"
        reader = PdfReader(path)
        assert len(reader.pages) == len(source.pages) == 3
        for actual, original in zip(reader.pages, source.pages):
            assert actual.extract_text() == original.extract_text()
            assert original.get_contents().get_data() in actual.get_contents().get_data()
            assert list(actual.mediabox) == list(original.mediabox)
            assert list(actual.cropbox) == list(original.cropbox)
            assert actual.rotation == original.rotation
        name = "party.customer.name" if label == "code" else "party.customer.renamed"
        all_fields = fields(reader)
        assert list(all_fields) == [name, "party.customer.code"]
        ref, field, widget_ref, widget = all_fields[name]
        assert field["/V"] == ("Alice Updated" if label == "filled" else "Alice")
        assert bool(field.get("/Ff", 0) & 2)
        assert [canonical(v) for v in reader.pages[0]["/Annots"]] == [canonical(v[2]) for v in all_fields.values()]
        appearance = widget["/AP"]["/N"]
        assert appearance.get_data()
        invariant = {"fieldRef": canonical(ref), "widgetRef": canonical(widget_ref),
                     "field": canonical({k: v for k, v in field.items() if k not in ("/T", "/V")}),
                     "widget": canonical({k: v for k, v in widget.items() if k != "/AP"}),
                     "other": [canonical(v) for v in all_fields["party.customer.code"]],
                     "parents": canonical(reader.trailer["/Root"]["/AcroForm"]["/Fields"])}
        if baseline is None:
            baseline = invariant
            baseline_appearance = canonical(appearance)
            baseline_ap_ref = canonical(widget["/AP"].raw_get("/N"))
        else:
            assert invariant == baseline
        if label == "renamed":
            assert canonical(appearance) == baseline_appearance
            assert canonical(widget["/AP"].raw_get("/N")) == baseline_ap_ref
            before = PdfReader(directory / "code-downloaded.pdf")
            target_id = ref.idnum
            assert reader.xref.keys() == before.xref.keys()
            for generation, objects in before.xref.items():
                assert objects.keys() == reader.xref[generation].keys()
                for number in objects:
                    if number == 0:
                        continue
                    old = before.get_object(IndirectObject(number, generation, before))
                    new = reader.get_object(IndirectObject(number, generation, reader))
                    if number == target_id:
                        old = {k: v for k, v in old.items() if k != "/T"}
                        new = {k: v for k, v in new.items() if k != "/T"}
                    assert canonical(old) == canonical(new), (number, generation)
        checks.append({"label": label, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                       "name": name, "value": str(field["/V"]), "bodyPreserved": True,
                       "treeAndReferencesPreserved": True, "renameAppearancePreserved": label == "renamed"})
    return {"ok": True, "sourceSha256": hashlib.sha256((directory / "source.pdf").read_bytes()).hexdigest(), "checks": checks}


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1]))))
