"""固定源公式是 Unicode 数学文本框；通过真实桥和独立 OOXML 核对，不冒称 OMML。"""
from io import BytesIO
from pathlib import Path
import subprocess
from zipfile import ZipFile

import pytest
from lxml import etree
from pptx import Presentation
from pptx.oxml.ns import qn

from smart_reporting.report_editor.native_office import inspect_office, patch_office
from smart_reporting.report_editor.pptx_engine import PptxEngine, _validate_structure_edits
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_office import presentation_bytes


@pytest.fixture(scope='module')
def equation_engine(tmp_path_factory):
    engine = Path(__file__).parents[1] / 'slides_engine'
    isolated = tmp_path_factory.mktemp('pptx-equation-engine')
    target = isolated / 'dist' / 'edit-pptx.mjs'
    target.parent.mkdir()
    subprocess.run([
        str(engine / 'node_modules/.bin/esbuild'), 'bridge/edit-pptx.ts', '--bundle', '--platform=node',
        '--format=esm', f'--outfile={target}', '--log-level=warning',
        '--banner:js=import { createRequire } from "node:module"; const require = createRequire(import.meta.url);',
    ], cwd=engine, check=True, capture_output=True, text=True)
    return isolated


@pytest.fixture(autouse=True)
def use_equation_engine(equation_engine, monkeypatch):
    monkeypatch.setenv('AGENT_REPORTING_SLIDES_ENGINE_DIR', str(equation_engine))


def equation(**changes):
    return {'slideIndex': 0, 'text': 'E = mc² <&> α 😀', 'geometry': {'x': 432, 'y': 222, 'width': 96, 'height': 96},
            'fontSize': 18, 'fontFamily': 'Cambria Math', 'color': '#000000', 'italic': True, 'equation': True, **changes}


def test_native_protocol_accepts_equation_flag_without_reclassifying_it_as_wordart():
    assert _validate_structure_edits({'textBoxes': [equation()]})[1] == [equation()]


def test_real_equation_preserves_unicode_source_body_and_unrelated_parts(tmp_path):
    source = presentation_bytes()
    result = patch_office('pptx', source, [{'kind': 'editSlides', 'textBoxes': [equation()]}])
    (tmp_path / 'source.pptx').write_bytes(source)
    (tmp_path / 'equation.pptx').write_bytes(result)
    before = Presentation(BytesIO(source))
    after = Presentation(BytesIO(result))
    assert [[shape.text for shape in slide.shapes] for slide in after.slides] == [['第一张', 'E = mc² <&> α 😀'], ['第二张']]
    added = after.slides[0].shapes[-1]
    assert (added.left, added.top, added.width, added.height) == (4114800, 2114550, 914400, 914400)
    run = added.text_frame.paragraphs[0].runs[0]
    assert run.font.name == 'Cambria Math' and run.font.italic is True and run.font.size.pt == 18
    body = added._element.find(qn('p:txBody'))
    assert body.find(qn('a:bodyPr')).get('wrap') == 'none'
    assert body.find(qn('a:bodyPr')).find(qn('a:spAutoFit')) is not None
    assert body.find(qn('a:bodyPr')).find(qn('a:normAutofit')) is None
    # 固定源仅框居中，段落沿用默认左对齐，不复用艺术字的居中段落。
    assert body.find(qn('a:p')).find(qn('a:pPr')) is None or body.find(qn('a:p')).find(qn('a:pPr')).get('algn') != 'ctr'
    assert etree.tostring(before.slides[0].shapes[0]._element) == etree.tostring(after.slides[0].shapes[0]._element)
    assert etree.tostring(before.slides[1]._element) == etree.tostring(after.slides[1]._element)
    with ZipFile(BytesIO(source)) as original, ZipFile(BytesIO(result)) as updated:
        parts = {part for part in original.namelist() if not part.endswith('/')}
        assert parts == {part for part in updated.namelist() if not part.endswith('/')}
        for part in parts:
            if part not in {'ppt/slides/slide1.xml', 'docProps/core.xml', 'ppt/presentation.xml'}:
                assert original.read(part) == updated.read(part), part
        xml = etree.fromstring(updated.read('ppt/slides/slide1.xml'))
        assert not xml.xpath('//*[local-name()="oMath" or local-name()="oMathPara"]')
    assert inspect_office('pptx', result)['slides'][0]['elements'][-1]['text'] == 'E = mc² <&> α 😀'


def test_equation_maps_original_source_page_through_reordering():
    result = patch_office('pptx', presentation_bytes(), [{'kind': 'editSlides', 'order': [1, 0], 'textBoxes': [equation(slideIndex=1)]}])
    assert [[shape.text for shape in slide.shapes] for slide in Presentation(BytesIO(result)).slides] == [['第二张', 'E = mc² <&> α 😀'], ['第一张']]


def test_equation_false_keeps_normal_textbox_autofit():
    result = patch_office('pptx', presentation_bytes(), [{'kind': 'editSlides', 'textBoxes': [equation(equation=False)]}])
    body = Presentation(BytesIO(result)).slides[0].shapes[-1]._element.find(qn('p:txBody')).find(qn('a:bodyPr'))
    assert body.get('wrap') != 'none'
    assert body.find(qn('a:normAutofit')) is not None


@pytest.mark.parametrize('value', ['yes', 1, None, {}, []])
def test_invalid_equation_flag_rejected_before_engine(value):
    with pytest.raises(ReportingError) as raised:
        _validate_structure_edits({'textBoxes': [equation(equation=value)]})
    assert '新增文本框' in str(raised.value)


def test_direct_bridge_also_rejects_nonboolean_equation_marker():
    with pytest.raises(ReportingError, match='textbox_wordart_invalid'):
        PptxEngine._run_engine(presentation_bytes(), 'edit', text_boxes=[equation(equation='yes')])
