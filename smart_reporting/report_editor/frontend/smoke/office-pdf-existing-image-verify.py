"""独立读取浏览器实际下载：核对原文、页面、替换像素与未编辑区域。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pymupdf
from PIL import Image, ImageChops, ImageDraw
from pypdf import PdfReader


def verify(directory: Path) -> dict:
    source_bytes = (directory / "source.pdf").read_bytes()
    output_bytes = (directory / "downloaded.pdf").read_bytes()
    source = pymupdf.open(stream=source_bytes, filetype="pdf")
    output = pymupdf.open(stream=output_bytes, filetype="pdf")
    save = json.loads((directory / "save.json").read_text())
    request, result = save["request"], save["result"]
    assert len(source) == len(output) == 3
    assert len(request["operations"]) == 1
    operation = request["operations"][0]
    assert operation["kind"] == "transformExistingImage"
    assert operation["rect"] == [80, 110, 230, 210]
    assert hashlib.sha256(source_bytes).hexdigest() == request["expectedSha256"]
    assert hashlib.sha256(output_bytes).hexdigest() == result["artifacts"]["pdf"]["sha256"]
    assert len(output_bytes) == result["artifacts"]["pdf"]["size"]
    before = source[0].get_image_info(hashes=True, xrefs=True)
    after = output[0].get_image_info(hashes=True, xrefs=True)
    assert len(before) == len(after) == 1
    assert all(abs(a - b) < 0.05 for a, b in zip(before[0]["bbox"], [60, 230, 160, 310], strict=True))
    assert all(abs(a - b) < 0.05 for a, b in zip(after[0]["bbox"], [80, 190, 230, 290], strict=True))
    pixels = pymupdf.Pixmap(output, after[0]["xref"])
    assert (pixels.width, pixels.height, pixels.n) == (40, 30, 3)
    with Image.open(directory / "replacement.png") as replacement:
        assert pixels.samples == replacement.convert("RGB").tobytes()
    texts, unchanged_page_renders = [], []
    for index in range(3):
        original, saved = source[index], output[index]
        assert original.get_text() == saved.get_text()
        assert tuple(original.mediabox) == tuple(saved.mediabox)
        assert tuple(original.cropbox) == tuple(saved.cropbox)
        assert original.rotation == saved.rotation
        assert not list(saved.annots() or [])
        a, b = original.get_pixmap(alpha=False), saved.get_pixmap(alpha=False)
        assert (a.width, a.height, a.n) == (b.width, b.height, b.n)
        if index:
            assert a.samples == b.samples
            unchanged_page_renders.append(index + 1)
        else:
            image_a = Image.frombytes("RGB", (a.width, a.height), a.samples)
            image_b = Image.frombytes("RGB", (b.width, b.height), b.samples)
            diff = ImageChops.difference(image_a, image_b)
            mask = ImageDraw.Draw(diff)
            for x1, y1, x2, y2 in [before[0]["bbox"], after[0]["bbox"]]:
                mask.rectangle((int(x1) - 1, int(y1) - 1, int(x2) + 1, int(y2) + 1), fill=(0, 0, 0))
            assert diff.getbbox() is None, "first-page changes outside the old/new image footprints"
        texts.append(saved.get_text())
    assert not PdfReader(directory / "downloaded.pdf").get_fields()
    return {
        "ok": True,
        "sourceSha256": hashlib.sha256(source_bytes).hexdigest(),
        "sourceBytes": len(source_bytes),
        "outputSha256": hashlib.sha256(output_bytes).hexdigest(),
        "outputBytes": len(output_bytes),
        "actualSaveCount": 1,
        "replacementSize": [pixels.width, pixels.height],
        "replacementPixelsSha256": hashlib.sha256(pixels.samples).hexdigest(),
        "allReplacementPixelsEqual": True,
        "sourceImageRect": before[0]["bbox"],
        "outputImageRect": after[0]["bbox"],
        "sourceMatrix": before[0]["transform"],
        "outputMatrix": after[0]["transform"],
        "pageTexts": texts,
        "pageGeometryAndTextPreserved": True,
        "firstPageUneditedAreaPixelsEqual": True,
        "unchangedPageRenders": unchanged_page_renders,
        "newAnnotationsOrFields": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    evidence = verify(args.directory)
    (args.directory / "independent-check.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence))
