"""Real HTTP fixture with rotated PDF pages and non-zero CropBoxes."""
from __future__ import annotations

import argparse
import asyncio
from io import BytesIO
import json
import os
from pathlib import Path
from runpy import run_path

import uvicorn
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject

create_app = run_path(str(Path(__file__).with_name("pdf-static-text-server.py")))["create_app"]
source_pdf = run_path(str(Path(__file__).resolve().parents[3] / "reporting/tests/test_native_pdf_extract.py"))["source_pdf"]


def rotated_crop_source() -> bytes:
    reader = PdfReader(BytesIO(source_pdf()))
    writer = PdfWriter()
    rotations = tuple(int(value) for value in __import__('os').environ.get('PDF_STATIC_TEXT_THUMBNAIL_ROTATIONS', '90,270').split(','))
    if len(rotations) != 2 or any(value not in (0, 90, 180, 270) for value in rotations):
        raise ValueError('invalid PDF_STATIC_TEXT_THUMBNAIL_ROTATIONS')
    for index, rotation in enumerate(rotations):
        page = reader.pages[index]
        page.rotate(rotation)
        page.cropbox = RectangleObject((20, 30, 280, 370))
        writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4298)
    args = parser.parse_args()
    source_path = os.environ.get("PDF_STATIC_TEXT_THUMBNAIL_SOURCE")
    source = Path(source_path).read_bytes() if source_path else rotated_crop_source()
    app = asyncio.run(create_app(args.directory, args.port, source=source))
    reader = PdfReader(BytesIO(source))
    facts = [{"page": index, "rotation": int(page.rotation or 0), "cropBox": [float(value) for value in page.cropbox], "mediaBox": [float(value) for value in page.mediabox]} for index, page in enumerate(reader.pages)]
    info_path = args.directory / "server-info.json"
    info_path.write_text(json.dumps({**json.loads(info_path.read_text()), "sourcePages": facts}, indent=2))
    uvicorn.run(app,
                host="127.0.0.1", port=args.port, log_level="warning")
