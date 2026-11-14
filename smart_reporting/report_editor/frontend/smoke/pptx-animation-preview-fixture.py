"""真实PPTX动画来源；文件引擎写入，python-pptx独立读取目标/计时。"""
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

directory = Path(sys.argv[1])
directory.mkdir(parents=True, exist_ok=True)
deck = Presentation()
for index in range(2):
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    for x, color in [(1, '2476CA'), (7, 'E48132')]:
        shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(2), Inches(2), Inches(1))
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor.from_string(color)
        shape.line.fill.background()
stream = BytesIO()
deck.save(stream)
model = inspect_office('pptx', stream.getvalue())
targets = model['slides'][0]['elements']
content = patch_office('pptx', stream.getvalue(), [{'kind': 'editSlides', 'animations': [
    {'slideIndex': 0, 'elementId': targets[0]['id'], 'effect': 'fade', 'trigger': 'onClick', 'durationMs': 600, 'delayMs': 0},
    {'slideIndex': 0, 'elementId': targets[1]['id'], 'effect': 'wipe', 'trigger': 'withPrev', 'durationMs': 600, 'delayMs': 0, 'direction': 'top'},
], 'animationSequences': []}])
# 动作路径使用同一整页序列协议；保留前两条来源引用。
model = inspect_office('pptx', content)
animations = model['slides'][0]['animations']
content = patch_office('pptx', content, [{'kind': 'editSlides', 'animationSequences': [{'slideIndex': 0, 'items': [
    *[{'source': index, 'spid': item['spid'], 'effect': item['effect']} for index, item in enumerate(animations)],
    {'elementId': targets[0]['id'], 'effect': 'motionPath', 'trigger': 'afterPrev', 'durationMs': 500, 'delayMs': 0, 'motionPath': 'M 0 0 L 0.25 0'},
]}]}])
source = directory / 'source.pptx'
assert not source.exists(), '来源夹具不可覆盖'
source.write_bytes(content)
actual = Presentation(BytesIO(content))
assert [shape.fill.fore_color.rgb.__str__() for shape in actual.slides[0].shapes] == ['2476CA', 'E48132']
assert actual.slides[0]._element.xpath('.//p:timing')
result = {'source': str(source), 'sha256': hashlib.sha256(content).hexdigest(), 'size': len(content), 'model': inspect_office('pptx', content), 'independentShapeColors': ['2476CA', 'E48132'], 'independentTimingPresent': True}
(directory / 'source-inspect.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps({key: value for key, value in result.items() if key != 'model'}))
