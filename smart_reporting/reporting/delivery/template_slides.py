"""模板原生落款：只回写目标幻灯片及新增页目录，不重存其他业务部件。"""
from copy import deepcopy
from io import BytesIO
from math import ceil
from zipfile import ZipFile

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Pt


def _text_shapes(shapes):
    """递归识别明确声明；分组坐标不按幻灯片坐标猜测。"""
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _text_shapes(shape.shapes)
        elif shape.has_text_frame:
            yield shape


def bind_slide_signature(content, signature):
    deck = Presentation(BytesIO(content))
    lines = [signature['signer'], signature['date'], *signature.get('description', '').splitlines()]
    slots = [(slide, shape) for slide in deck.slides for shape in _text_shapes(slide.shapes)
        if shape.name == 'report_signature' or shape.text.strip() == '{{report_signature}}']
    changed, issues = set(), []
    if len(slots) > 1:
        issues.append({'code': 'report_template_signature_multiple_slots',
            'message': '模板声明了多个落款位置，已保留首处并清除重复落款，请复核布局。'})
        for slide, shape in slots[1:]:
            shape.text_frame.clear()
            changed.add(str(slide.part.partname)[1:])
    slot = slots[0] if slots else None
    if slot and slot[1]._element.getparent().tag.endswith('}grpSp'):
        slide, shape = slot
        shape.text_frame.clear()
        changed.add(str(slide.part.partname)[1:])
        issues.append({'code': 'report_template_signature_grouped_slot',
            'message': '模板落款位于分组内，其缩放与旋转布局尚未核验，已清除该处样例并移至独立结束页。'})
        slot = None
    if slot:
        slide, shape = slot
        run = next((run for paragraph in shape.text_frame.paragraphs for run in paragraph.runs), None)
        size = run.font.size.pt if run is not None and run.font.size is not None else 18
        # 以文字估算判断位置是否足够；空间不足不挤压现有正文。
        width = max(1, (shape.width - shape.text_frame.margin_left - shape.text_frame.margin_right) / 12700)
        height = max(0, (shape.height - shape.text_frame.margin_top - shape.text_frame.margin_bottom) / 12700)
        needed = sum(max(1, ceil(len(line) * size / width)) for line in lines) * size * 1.4
        overlaps = any(other != shape and (other.has_text_frame and other.text.strip() or other.has_chart
                or other.has_table or other.shape_type == MSO_SHAPE_TYPE.PICTURE)
            and max(shape.left, other.left) < min(shape.left + shape.width, other.left + other.width)
            and max(shape.top, other.top) < min(shape.top + shape.height, other.top + other.height)
            for other in slide.shapes)
        outside = (shape.left < 0 or shape.top < 0 or shape.left + shape.width > deck.slide_width
            or shape.top + shape.height > deck.slide_height)
        if needed > height or overlaps or outside:
            shape.text_frame.clear()
            changed.add(str(slide.part.partname)[1:])
            issues.append({'code': 'report_template_signature_slot_small',
                'message': '模板落款位置不足、越界或与正文对象重叠，已移至独立结束页，原正文保持不变。'})
            slot = None
    added = slot is None
    if added:
        slide = deck.slides.add_slide(min(deck.slide_layouts, key=lambda layout: len(layout.placeholders)))
        for shape in list(slide.shapes):
            shape._element.getparent().remove(shape._element)
        shape = slide.shapes.add_textbox(int(deck.slide_width * .1), int(deck.slide_height * .2),
            int(deck.slide_width * .8), int(deck.slide_height * .65))
        shape.name = 'report_signature'
        width = shape.width / 12700 - 15
        height = shape.height / 12700 - 10
        size = 18
        while size > 14 and sum(max(1, ceil(len(line) * size / width)) for line in lines) * size * 1.4 > height:
            size -= 1
        if sum(max(1, ceil(len(line) * size / width)) for line in lines) * size * 1.4 > height:
            issues.append({'code': 'report_template_signature_overflow_unverified',
                'message': '落款内容超过结束页可读容量，已保留全部文字，请复核并精简说明。'})
    else:
        slide, shape = slot
        shape.name = 'report_signature'
    frame = shape.text_frame
    original = frame.paragraphs[0]
    paragraph_properties = deepcopy(original._p.pPr)
    run_properties = next((deepcopy(run._r.rPr) for paragraph in frame.paragraphs for run in paragraph.runs
        if run._r.rPr is not None), None)
    frame.clear()
    frame.word_wrap = True
    for index, line in enumerate(lines):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        if paragraph_properties is not None:
            paragraph._p.insert(0, deepcopy(paragraph_properties))
        else:
            paragraph.alignment = PP_ALIGN.RIGHT
        run = paragraph.add_run()
        run.text = line
        if run_properties is not None:
            run._r.insert(0, deepcopy(run_properties))
        else:
            run.font.name = 'Noto Sans CJK SC'
            run.font.size = Pt(size)
    changed.add(str(slide.part.partname)[1:])
    output = BytesIO()
    deck.save(output)
    result = BytesIO()
    with ZipFile(BytesIO(content)) as source, ZipFile(output) as edited, ZipFile(result, 'w') as target:
        existing = set(source.namelist())
        if added:
            changed.update({'ppt/presentation.xml', 'ppt/_rels/presentation.xml.rels', '[Content_Types].xml'})
        for entry in source.infolist():
            target.writestr(entry, edited.read(entry.filename) if entry.filename in changed else source.read(entry))
        for name in edited.namelist():
            if name not in existing:
                target.writestr(name, edited.read(name))
    return result.getvalue(), sorted(changed), issues, {
        'placement': 'ending_slide' if added else 'declared_textbox',
        'layoutSource': 'generated_fallback' if added else 'template',
        'templateSampleStatus': 'cleared' if slots and added else 'replaced' if slots else 'no_declared_slot',
        'slideNumber': next(index + 1 for index, item in enumerate(deck.slides) if item == slide)}
