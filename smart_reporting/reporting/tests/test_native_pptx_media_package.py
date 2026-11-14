"""固定源 writer 的真实包回读；不依赖共享 dist 或模拟媒体身份。"""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile

from lxml import etree
from pptx import Presentation
from pptx.util import Inches
import pytest

ENGINE = Path(__file__).parents[1] / 'slides_engine'


def invoke(root, action, **request):
    path = root / 'request.json'
    path.write_text(json.dumps(request | ({'action': action} if action != 'render' else {})))
    process = subprocess.run([str(ENGINE / 'node_modules/.bin/tsx'), str(ENGINE / 'bridge' / ('render-pptx.ts' if action == 'render' else 'edit-pptx.ts')), str(path)], cwd=ENGINE, capture_output=True, text=True, timeout=120)
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


def test_media_real_writer_and_snapshot_preserve_bytes_and_existing_parts(tmp_path):
    source, output = tmp_path / 'source.pptx', tmp_path / 'output.pptx'
    deck = Presentation()
    for index in range(2):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1)).text = f'保留正文 {index}'
        slide.notes_slide.notes_text_frame.text = f'保留讲稿 {index}'
    deck.save(source)
    original_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    wav, video = b'RIFFmedia-original-audio', b'fixture-video-original-bytes'
    items = [dict(slideIndex=0, kind=kind, extension=ext, bytesBase64=base64.b64encode(data).decode(), name=name) for kind, ext, data, name in [('audio', 'wav', wav, '音频.wav'), ('video', 'webm', video, '视频.webm')]]
    invoke(tmp_path, 'edit', input=str(source), output=str(output), mediaInsertions=items)
    model = invoke(tmp_path, 'inspect', input=str(output))
    assert [el['mediaKind'] for el in model['slides'][0]['elements'] if el.get('mediaKind')] == ['audio', 'video']
    tree = invoke(tmp_path, 'render', input=str(output))
    sources = tree['slides'][0]['mediaSources']
    assert len(sources) == 2
    for media, data in zip(sources, (wav, video)):
        assert base64.b64decode(media['dataUrl'].split(',', 1)[1]) == data
        assert media['size'] == len(data) and media['sha256'] == hashlib.sha256(data).hexdigest()
    reopened = Presentation(output)
    assert len(reopened.slides) == 2
    assert [s.notes_slide.notes_text_frame.text for s in reopened.slides] == [f'保留讲稿 {i}' for i in range(2)]
    with ZipFile(source) as a, ZipFile(output) as b:
        assert b.testzip() is None
        assert a.read('ppt/slides/slide2.xml') == b.read('ppt/slides/slide2.xml')
        assert {n for n in a.namelist() if not n.endswith('/')} <= set(b.namelist())
        media_parts = [n for n in b.namelist() if n.endswith(('.wav', '.webm'))]
        assert sorted(b.read(n) for n in media_parts) == sorted([wav, video])
        ns = {'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}
        rels = etree.fromstring(b.read('ppt/slides/_rels/slide1.xml.rels'))
        for ext in ('.wav', '.webm'):
            linked = [r for r in rels if r.get('Target', '').endswith(ext)]
            assert len(linked) == 2
            assert {r.get('Type').split('/')[-1] for r in linked} == ({'audio', 'media'} if ext == '.wav' else {'video', 'media'})
        for name in a.namelist():
            if name not in {'ppt/slides/slide1.xml', 'ppt/slides/_rels/slide1.xml.rels', '[Content_Types].xml'} and not name.endswith('/'):
                assert a.read(name) == b.read(name), name
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_sha


@pytest.mark.parametrize('item', [dict(slideIndex=5, kind='audio', extension='wav', bytesBase64='UklGRg=='), dict(slideIndex=0, kind='video', extension='wav', bytesBase64='UklGRg=='), dict(slideIndex=0, kind='audio', extension='wav', bytesBase64='Zh==')])
def test_media_bridge_rejects_invalid_requests_before_output(tmp_path, item):
    source, output = tmp_path / 'source.pptx', tmp_path / 'output.pptx'
    deck = Presentation(); deck.slides.add_slide(deck.slide_layouts[6]); deck.save(source)
    with pytest.raises(AssertionError):
        invoke(tmp_path, 'edit', input=str(source), output=str(output), mediaInsertions=[item])
    assert not output.exists()
