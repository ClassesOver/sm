"""3D宿主真实包链：插入后可旋转，GLB与海报共同保存，外链不被使用。"""
import base64
import hashlib
import io
import json
import struct
from zipfile import ZipFile

from PIL import Image
from lxml import etree
from pptx import Presentation
import pytest

from .test_native_pptx_media_package import invoke


def glb(uri=None):
    model = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}], 'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}], 'accessors': [{'min': [-1, -1, -1], 'max': [1, 1, 1]}]}
    if uri:
        model['buffers'] = [{'uri': uri, 'byteLength': 1}]
    chunk = json.dumps(model).encode(); chunk += b' ' * (-len(chunk) % 4)
    return struct.pack('<IIIII', 0x46546c67, 2, 20 + len(chunk), len(chunk), 0x4e4f534a) + chunk


def poster(color):
    stream = io.BytesIO(); Image.new('RGBA', (32, 24), color).save(stream, format='PNG'); return stream.getvalue()


def item(data=None):
    return dict(slideIndex=0, key='model-one', bytesBase64=base64.b64encode(data or glb()).decode(), posterBase64=base64.b64encode(poster('red')).decode(), name='真实模型.glb', aspect=1.3, rot={'ax': 0, 'ay': 0, 'az': 0})


def test_model3d_native_insert_turn_and_actual_package_source(tmp_path):
    source, output, turned = [tmp_path / name for name in ['source.pptx', 'inserted.pptx', 'turned.pptx']]
    deck = Presentation(); deck.slides.add_slide(deck.slide_layouts[6]); deck.slides.add_slide(deck.slide_layouts[6]); deck.save(source)
    insertion = item()
    invoke(tmp_path, 'edit', input=str(source), output=str(output), modelInsertions=[insertion])
    model = invoke(tmp_path, 'inspect', input=str(output))
    elements = [e for e in model['slides'][0]['elements'] if e.get('model3d')]
    assert len(elements) == 1, 'model insertion must be a native model, not a normal poster picture'
    element = elements[0]
    tree = invoke(tmp_path, 'render', input=str(output))
    read = tree['slides'][0]['modelSources'][0]
    assert read['sha256'] == hashlib.sha256(glb()).hexdigest()
    assert base64.b64decode(read['bytesBase64']) == glb()
    rot = {'ax': 1800000, 'ay': 2700000, 'az': 0}
    invoke(tmp_path, 'edit', input=str(output), output=str(turned), modelViews=[dict(slideIndex=0, elementId=element['id'], expectedSha256=read['sha256'], rot=rot, posterBase64=base64.b64encode(poster('blue')).decode())])
    reopened = invoke(tmp_path, 'render', input=str(turned))
    assert reopened['slides'][0]['modelSources'][0]['rot'] == rot
    with ZipFile(source) as a, ZipFile(turned) as b:
        assert a.read('ppt/slides/slide2.xml') == b.read('ppt/slides/slide2.xml')
        assert [b.read(n) for n in b.namelist() if n.endswith('.glb')] == [glb()]
        xml = etree.fromstring(b.read('ppt/slides/slide1.xml'))
        assert xml.xpath('count(//*[local-name()="model3d"])') == 1
        assert xml.xpath('count(//*[local-name()="AlternateContent"]/*[local-name()="Fallback"]/*[local-name()="pic"])') == 1
        assert poster('blue') in [b.read(n) for n in b.namelist() if n.endswith('.png')]


@pytest.mark.parametrize('uri', ['https://example.invalid/private.bin', 'file:///etc/passwd', 'data:application/octet-stream;base64,AA=='])
def test_model3d_never_embeds_unbound_external_resources(tmp_path, uri):
    source, output = tmp_path / 'source.pptx', tmp_path / 'output.pptx'
    deck = Presentation(); deck.slides.add_slide(deck.slide_layouts[6]); deck.save(source)
    with pytest.raises(AssertionError):
        invoke(tmp_path, 'edit', input=str(source), output=str(output), modelInsertions=[item(glb(uri))])
    assert not output.exists()
