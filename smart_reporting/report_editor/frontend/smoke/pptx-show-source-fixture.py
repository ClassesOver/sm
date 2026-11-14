"""真实PC放映夹具：来源动画、隐藏页及push/Morph，独立回读来源字节。"""
import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches
from smart_reporting.report_editor.native_office import inspect_office, patch_office

directory = Path(sys.argv[1]); directory.mkdir(parents=True, exist_ok=True)
deck = Presentation()
for index, positions in enumerate([[(1, 2), (7, 2)], [(2, 1), (6, 4)], [(2, 3), (6, 3)], [(5, 2), (1, 4)]]):
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    for (x, y), color in zip(positions, ['2476CA', 'E48132']):
        shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(2), Inches(1))
        shape.fill.solid(); shape.fill.fore_color.rgb = RGBColor.from_string(color); shape.line.fill.background()
stream = BytesIO(); deck.save(stream); content = stream.getvalue()
model = inspect_office('pptx', content); target = model['slides'][0]['elements'][0]['id']; other = model['slides'][0]['elements'][1]['id']
content = patch_office('pptx', content, [{'kind': 'editSlides', 'hiddenSlides': [{'slideIndex': 1, 'hidden': True}],
    'transitions': [{'slideIndex': 2, 'kind': 'push'}, {'slideIndex': 3, 'kind': 'morph'}],
    'animations': [{'slideIndex': 0, 'elementId': target, 'effect': 'fade', 'trigger': 'onClick', 'durationMs': 600, 'delayMs': 0},
                   {'slideIndex': 0, 'elementId': other, 'effect': 'wipe', 'trigger': 'withPrev', 'durationMs': 600, 'delayMs': 0, 'direction': 'top'}]}])
model = inspect_office('pptx', content)
content = patch_office('pptx', content, [{'kind': 'editSlides', 'animationSequences': [{'slideIndex': 0, 'items': [
    *[{'source': i, 'spid': item['spid'], 'effect': item['effect']} for i, item in enumerate(model['slides'][0]['animations'])],
    {'elementId': target, 'effect': 'motionPath', 'trigger': 'afterPrev', 'durationMs': 500, 'delayMs': 0, 'motionPath': 'M 0 0 L 0.25 0'},
]}]}])
source = directory / 'source.pptx'; assert not source.exists(), '来源夹具不可覆盖'; source.write_bytes(content)
actual = Presentation(BytesIO(content)); assert len(actual.slides) == 4
assert actual.slides[1]._element.get('show') == '0'
assert actual.slides[0]._element.xpath('.//p:timing')
assert all([str(shape.fill.fore_color.rgb) for shape in slide.shapes] == ['2476CA', 'E48132'] for slide in actual.slides)
result = {'source': str(source), 'sha256': hashlib.sha256(content).hexdigest(), 'size': len(content), 'model': inspect_office('pptx', content),
          'independent': {'slideCount': 4, 'hiddenOriginalIndex': 1, 'timingPresent': True, 'colors': ['2476CA', 'E48132']}}
(directory / 'source-inspect.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps({key: value for key, value in result.items() if key != 'model'}))
