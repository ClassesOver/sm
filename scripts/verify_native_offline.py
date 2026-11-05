#!/usr/bin/env python3
"""Exercise installed packaged runtimes in a network-isolated container.

Mount this script read-only into the image, use PYTHONPATH=/app, and optionally
mount --output-dir to retain source/edited samples and evidence.json. No HTTP,
production database, browser execution or desktop Office certification is implied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit


def require(ok: bool, issue: str) -> None:
    if not ok:
        raise RuntimeError(issue)


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def verify_static(root: Path) -> dict:
    """Validate shipped entry URLs/resources, not the full JS fetch graph."""
    root = root.resolve()
    prefix = '/reports/v1/editor/assets/'
    assets = {}
    for entry in ('index.html', 'native.html'):
        path = root / entry
        require(path.is_file(), f'static_entry_missing:{entry}')
        targets = re.findall(r'<(?:script|link)\b[^>]*(?:src|href)=["\']([^"\']+)', path.read_text())
        require(bool(targets), f'static_entry_assets_missing:{entry}')
        for target in targets:
            parsed = urlsplit(target)
            require(not parsed.scheme and not parsed.netloc and parsed.path.startswith(prefix),
                    f'static_entry_not_same_origin:{entry}:{target}')
            asset = (root / parsed.path.removeprefix(prefix)).resolve()
            require(asset.is_relative_to(root.resolve()), f'static_asset_outside_root:{target}')
            require(asset.is_file() and asset.stat().st_size > 0, f'static_asset_missing:{target}')
            assets[str(asset.relative_to(root))] = digest(asset.read_bytes())
    require((root / 'native-upload.js').is_file(), 'native_upload_entry_missing')
    for folder in ('cmaps', 'standard_fonts', 'wasm'):
        files = sorted(path for path in (root / 'pdfjs' / folder).rglob('*') if path.is_file())
        require(bool(files), f'pdfjs_assets_missing:{folder}')
        assets[f'pdfjs/{folder}'] = {str(p.relative_to(root)): digest(p.read_bytes()) for p in files}
    return {'assets': assets, 'browserExecution': False, 'scope': 'Entry URLs and PDF.js asset files only'}


def verify(output: Path, *, allow_network: bool, skip_static: bool, static_root: Path, provenance: str) -> dict:
    interfaces = sorted(name for _, name in socket.if_nameindex())
    require(allow_network or interfaces == ['lo'], f'network_isolation_not_established:{interfaces}')
    require(not os.getenv('NODE_PATH') and not os.getenv('NODE_OPTIONS'), 'external_node_configuration_present')
    from docx import Document
    from openpyxl import Workbook, load_workbook
    from pptx import Presentation
    from pptx.util import Inches
    from pypdf import PdfReader, PdfWriter

    from smart_reporting.report_editor.native_office import inspect_office, patch_office
    from smart_reporting.report_editor.native_readiness import native_readiness_checks
    from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
    from smart_reporting.reporting.delivery.office_engine import engine_dir
    from smart_reporting.reporting.delivery.pdf_native import inspect_pdf, patch_pdf

    config = dict(native_docx_enabled=False, native_pdf_enabled=False, native_pdf_text_enabled=False,
                  native_ai_enabled=False, native_upload_enabled=False)
    require(native_readiness_checks(SimpleNamespace(**config)) == {}, 'disabled_readiness_requires_resources')
    flags = {}
    for name in ('DOCX', 'PDF', 'PDF_TEXT', 'AI', 'UPLOAD'):
        value = os.getenv(f'AGENT_REPORT_EDITOR_{name}_ENABLED', os.getenv(f'AGENT_NATIVE_{name}_ENABLED', 'false'))
        flags[name] = value.strip().lower() in {'1', 'true', 'yes', 'on'}
    require(not any(flags.values()), 'native_features_must_remain_disabled')
    checks = native_readiness_checks(SimpleNamespace(**{**config, 'native_upload_enabled': True}))
    require(bool(checks) and all(checks.values()), f'enabled_resource_probe_failed:{checks}')
    runtimes = {}
    for name in ('slides', 'workbook', 'pdf'):
        root = engine_dir(name).resolve()
        for development in ('node_modules', 'packages', 'bridge', 'src'):
            require(not (root / development).exists(), f'development_tree_in_runtime:{name}:{development}')
        bundles = sorted((root / 'dist').glob('*.mjs'))
        require(bool(bundles), f'packaged_bridge_missing:{name}')
        runtimes[name] = {'path': str(root), 'bundles': {p.name: digest(p.read_bytes()) for p in bundles}}
    output.mkdir(parents=True, exist_ok=True)
    results = {}

    def receipt(format: str, source: bytes, original_hash: str, edited: bytes, detail: dict) -> None:
        require(digest(source) == original_hash, f'source_mutated:{format}')
        require(source != edited and bool(edited), f'edit_not_materialized:{format}')
        (output / f'source.{format}').write_bytes(source)
        (output / f'edited.{format}').write_bytes(edited)
        results[format] = {'sourceSha256': digest(source), 'editedSha256': digest(edited),
                          'editedSize': len(edited), 'independentReadback': detail}

    stream = BytesIO()
    document = Document()
    document.add_paragraph('Native offline source')
    document.add_paragraph('Unchanged paragraph')
    document.save(stream)
    source = stream.getvalue()
    identity = digest(source)
    block = next(item for item in inspect_docx(source)['blocks'] if item['editable'])
    edited = patch_docx(source, [{'kind': 'replaceParagraph', 'blockId': block['blockId'],
                                'expectedObjectSha256': block['expectedObjectSha256'], 'text': 'Native offline edited'}])
    paragraphs = [p.text for p in Document(BytesIO(edited)).paragraphs]
    require(paragraphs == ['Native offline edited', 'Unchanged paragraph'], 'docx_readback_failed')
    receipt('docx', source, identity, edited, {'paragraphs': paragraphs})

    stream = BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet['A1'], sheet['A2'], sheet['B1'] = 1, 2, '=SUM(A1:A2)'
    sheet['A1'].number_format = '0.000'
    sheet.merge_cells('D1:E1')
    workbook.save(stream)
    source = stream.getvalue()
    identity = digest(source)
    edited = patch_office('xlsx', source, [{'kind': 'applyCellEdits', 'edits': [
        {'sheetName': 'Sheet', 'row': 1, 'column': 0, 'writeValue': True, 'cell': {'value': 3}},
    ]}])
    readback = load_workbook(BytesIO(edited)).active
    require(readback['A2'].value == 3 and readback['B1'].value == '=SUM(A1:A2)', 'xlsx_value_formula_failed')
    require(readback['A1'].number_format == '0.000' and 'D1:E1' in readback.merged_cells, 'xlsx_preservation_failed')
    receipt('xlsx', source, identity, edited, {'A2': 3, 'B1': readback['B1'].value,
                                            'A1Format': readback['A1'].number_format, 'merged': 'D1:E1'})

    stream = BytesIO()
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)).text = 'Native offline source'
    deck.save(stream)
    source = stream.getvalue()
    identity = digest(source)
    model = inspect_office('pptx', source)
    target = next(item for item in model['slides'][0]['elements'] if item['editable'] and item['text'])
    edited = patch_office('pptx', source, [{'kind': 'editSlides', 'slideSize': {'cx': 9000000, 'cy': 7200000},
        'edits': [{'slideIndex': 0, 'elementId': target['id'], 'text': 'Native offline edited'}]}])
    readback = Presentation(BytesIO(edited))
    shape = readback.slides[0].shapes[0]
    require((readback.slide_width, readback.slide_height) == (9000000, 7200000), 'pptx_size_failed')
    require(shape.text == 'Native offline edited', 'pptx_text_failed')
    geometry = [shape.left, shape.top, shape.width, shape.height]
    require(geometry == [900000, 960000, 2700000, 960000], 'pptx_geometry_failed')
    receipt('pptx', source, identity, edited, {'sizeEmu': [readback.slide_width, readback.slide_height],
        'text': shape.text, 'geometryEmu': geometry})

    stream = BytesIO()
    pdf = PdfWriter()
    pdf.add_blank_page(width=612, height=792)
    pdf.add_blank_page(width=500, height=400)
    pdf.write(stream)
    source = stream.getvalue()
    identity = digest(source)
    pages = inspect_pdf(source)['pages']
    edited = patch_pdf(source, [{'kind': 'reorderPages', 'pageIds': [p['pageId'] for p in reversed(pages)]}])
    sizes = [(float(p.mediabox.width), float(p.mediabox.height)) for p in PdfReader(BytesIO(edited)).pages]
    require(sizes == [(500, 400), (612, 792)], 'pdf_order_failed')
    receipt('pdf', source, identity, edited, {'pageSizes': sizes})
    static = {'skipped': True} if skip_static else verify_static(static_root)
    report = {'ok': True, 'offline': not allow_network, 'runtimeProvenance': provenance, 'interfaces': interfaces, 'featureFlags': flags,
              'disabledReadiness': {}, 'enabledResourceProbe': checks, 'runtimes': runtimes,
              'formats': results, 'static': static,
              'scope': 'Packaged file engines and independent readers; no HTTP/database/browser acceptance'}
    (output / 'evidence.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provenance', required=True, choices=('runtime-image', 'mounted-runtime-probe'),
                        help='Caller-declared runtime origin; a mounted probe is not a fresh application image')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--static-root', type=Path, default=Path(os.getenv('AGENT_REPORT_EDITOR_STATIC_DIR', '/opt/report-editor-static')))
    parser.add_argument('--allow-network-for-local-diagnostics', action='store_true')
    parser.add_argument('--skip-static-for-local-diagnostics', action='store_true')
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix='native-offline-') as temporary:
            result = verify(args.output_dir or Path(temporary), allow_network=args.allow_network_for_local_diagnostics,
                            skip_static=args.skip_static_for_local_diagnostics, static_root=args.static_root, provenance=args.provenance)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:
        failure = {'ok': False, 'errorType': type(error).__name__, 'issue': str(error)}
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            (args.output_dir / 'evidence.json').write_text(json.dumps(failure, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(failure, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
