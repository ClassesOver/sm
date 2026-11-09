"""原生 XLSX/PPTX 包装复用既有引擎，保存前严格验证人工操作。"""
from io import BytesIO
from copy import deepcopy
from unittest.mock import Mock

import pytest


def workbook_bytes():
    from openpyxl import Workbook
    workbook = Workbook();workbook.active['A1']='原值';stream=BytesIO();workbook.save(stream);return stream.getvalue()


def presentation_bytes():
    from pptx import Presentation
    from pptx.util import Inches
    presentation=Presentation()
    for text in ['第一张', '第二张']:
        slide=presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1),Inches(1),Inches(3),Inches(1)).text=text
    stream=BytesIO();presentation.save(stream);return stream.getvalue()


@pytest.mark.parametrize('format', ['xlsx','pptx'])
def test_empty_operations_preserve_exact_original_bytes(format):
    from smart_reporting.report_editor.native_office import patch_office
    content=workbook_bytes() if format=='xlsx' else presentation_bytes()
    assert patch_office(format,content,[]) is content


@pytest.mark.parametrize('operation', [
    {'kind':'editSlides','unknown':True}, {'kind':'editSlides','images':[]},
    {'kind':'editSlides','chartReplacements':[]}, {'kind':'editSlides','expectedSha256':'fake'},
    {'kind':'editSlides','theme':[]}, {'kind':'editSlides','edits':None},
    {'kind':'editSlides','slideSize':{'cx':1,'cy':1}},
    {'kind':'editSlides','slideSize':{'cx':12192000,'cy':6858000,'extra':True}},
    {'kind':'editSlides','order':[True]}, {'kind':'editSlides','order':[0,0]},
    {'kind':'editSlides','transitions':[{'slideIndex':False,'kind':'fade'}]},
    {'kind':'editSlides','transitions':[{'slideIndex':0,'kind':[]}]},
    {'kind':'editSlides','animations':[{'slideIndex':0,'elementId':'x','effect':'fade','trigger':'onClick','delayMs':float('nan')}]},
    {'kind':'editSlides','animations':[{'slideIndex':0,'elementId':'x','effect':'flyIn','trigger':'onClick','direction':'diagonal'}]},
    {'kind':'editSlides','animations':[{'slideIndex':0,'elementId':'x','effect':'fade','trigger':'onClick','direction':'left'}]},
    {'kind':'editSlides','animations':[{'slideIndex':0,'elementId':'x','effect':'fade','trigger':'onClick','append':'yes'}]},
    {'kind':'editSlides','textFormatting':[{'slideIndex':0,'elementId':'x','fontSizePt':0}]},
    {'kind':'editSlides','textFormatting':[{'slideIndex':0,'elementId':'x','color':'red'}]},
    {'kind':'editSlides','textFormatting':[{'slideIndex':0,'elementId':'x','bold':'yes'}]},
    {'kind':'editSlides','textFormatting':[{'slideIndex':0,'elementId':'x','italic':'yes'}]},
    {'kind':'editSlides','paragraphFormatting':[{'slideIndex':0,'elementId':'x','align':'distributed'}]},
    {'kind':'editSlides','slideLayouts':[{'slideIndex':0,'layoutPath':'ppt/slideLayouts/../../evil.xml'}]},
    {'kind':'editSlides','textBoxes':[{'slideIndex':0,'text':'x','geometry':{'x':0,'y':0,'width':True,'height':1}}]},
    {'kind':'editSlides','deletions':[{'slideIndex':0,'elementId':''}]},
])
def test_invalid_pptx_operations_never_call_engine(monkeypatch,operation):
    from smart_reporting.report_editor.native_office import patch_office
    from smart_reporting.report_editor.slides import ReportSlidesEditorService
    engine=Mock(side_effect=AssertionError('should not call engine'));monkeypatch.setattr(ReportSlidesEditorService,'_run_engine',engine)
    with pytest.raises(ValueError):patch_office('pptx',b'source',[operation])
    engine.assert_not_called()


def test_real_xlsx_patch_and_independent_readback():
    from smart_reporting.report_editor.native_office import inspect_office,patch_office
    from openpyxl import load_workbook
    content=workbook_bytes();source=bytes(content)
    operations=[{'kind':'applyCellEdits','edits':[{'sheetName':'Sheet','row':0,'column':0,'writeValue':True,'cell':{'value':'修改值'}}]}]
    edited=patch_office('xlsx',content,operations)
    assert content==source
    assert load_workbook(BytesIO(content)).active['A1'].value=='原值'
    assert load_workbook(BytesIO(edited)).active['A1'].value=='修改值'
    assert inspect_office('xlsx',edited)['sheets'][0]['cells']['A1']['value']=='修改值'


def test_real_pptx_manual_changes_and_independent_readback():
    from smart_reporting.report_editor.native_office import inspect_office,patch_office
    from pptx import Presentation
    content=presentation_bytes();source=bytes(content);model=inspect_office('pptx',content)
    target=model['slides'][0]['elements'][0];deleted=model['slides'][1]['elements'][0]
    operation={'kind':'editSlides','edits':[{'slideIndex':0,'elementId':target['id'],'text':'修改文字','geometry':{'x':80,'y':100,'width':320,'height':90}}],
        'order':[1,0],'theme':'modern','transitions':[{'slideIndex':0,'kind':'fade'}],
        'animations':[{'slideIndex':0,'elementId':target['id'],'effect':'fade','trigger':'onClick','durationMs':500}],
        'slideLayouts':[{'slideIndex':0,'layoutPath':model['layouts'][0]['path']}],
        'backgrounds':[{'slideIndex':0,'color':'#123456'}],
        'textBoxes':[{'slideIndex':0,'text':'新增水印','geometry':{'x':10,'y':10,'width':180,'height':30},'bold':True}],
        'deletions':[{'slideIndex':1,'elementId':deleted['id']}]}
    original=deepcopy(operation);edited=patch_office('pptx',content,[operation]);assert operation==original and content==source
    assert Presentation(BytesIO(content)).slides[0].shapes[0].text=='第一张'
    reopened=inspect_office('pptx',edited)
    assert not reopened['slides'][0]['elements']
    texts=[item['text'] for item in reopened['slides'][1]['elements']]
    assert '修改文字' in texts and '新增水印' in texts
    assert reopened['slides'][1]['background']=='#123456'
    assert reopened['slides'][1]['transition']=='fade'
    assert reopened['slides'][1]['animations'][0]['effect']=='fade'


@pytest.mark.parametrize('size', [{'cx': 12192000, 'cy': 6858000}, {'cx': 9144000, 'cy': 6858000}, {'cx': 9000000, 'cy': 7200000}, {'cx': 914400, 'cy': 51206400}])
def test_real_pptx_slide_size_roundtrips_through_native_operation_and_inspect(size):
    from smart_reporting.report_editor.native_office import inspect_office,patch_office
    from pptx import Presentation

    content = presentation_bytes()
    original_size = inspect_office('pptx', content)['size']
    edited = patch_office('pptx', content, [{
        'kind': 'editSlides', 'slideSize': size,
    }])

    assert Presentation(BytesIO(edited)).slide_width == size['cx']
    assert Presentation(BytesIO(edited)).slide_height == size['cy']
    assert inspect_office('pptx', edited)['size'] == size
    assert inspect_office('pptx', content)['size'] == original_size


@pytest.mark.parametrize('size', [
    {'cx': 12192000, 'cy': 6858000}, {'cx': 6858000, 'cy': 12192000},
    {'cx': 9144000, 'cy': 6858000}, {'cx': 6858000, 'cy': 9144000},
    {'cx': 10692000, 'cy': 7560000}, {'cx': 7560000, 'cy': 10692000},
    {'cx': 15120000, 'cy': 10692000}, {'cx': 10692000, 'cy': 15120000},
])
def test_native_pptx_paper_size_schema_accepts_pinned_presets_in_both_orientations(size):
    from smart_reporting.report_editor.native_office import _pptx_arguments

    assert _pptx_arguments({'kind': 'editSlides', 'slideSize': size})['slide_size'] == size


@pytest.mark.parametrize('size', [
    {'cx': 914399, 'cy': 7560000}, {'cx': True, 'cy': 10692000},
    {'cx': 7560000.0, 'cy': 10692000}, {'cx': 10692000, 'cy': 7560000, 'extra': True},
    {'cx': 5143500, 'cy': 51206401},
])
def test_native_pptx_size_schema_rejects_out_of_range_or_malformed_sizes(size):
    from smart_reporting.report_editor.native_office import _pptx_arguments

    with pytest.raises(ValueError, match='native_office_operations_invalid'):
        _pptx_arguments({'kind': 'editSlides', 'slideSize': size})


def test_real_pptx_slide_size_scales_pending_geometry_and_textboxes_after_other_edits():
    from smart_reporting.report_editor.native_office import inspect_office,patch_office
    from pptx import Presentation

    content = presentation_bytes()
    target = inspect_office('pptx', content)['slides'][0]['elements'][0]
    edited = patch_office('pptx', content, [{
        'kind': 'editSlides', 'slideSize': {'cx': 12192000, 'cy': 6858000},
        'edits': [{'slideIndex': 0, 'elementId': target['id'], 'geometry': {'x': 75, 'y': 80, 'width': 300, 'height': 90}}],
        'textFormatting': [{'slideIndex': 0, 'elementId': target['id'], 'fontSizePt': 24}],
        'textBoxes': [{'slideIndex': 0, 'text': '新增文本', 'geometry': {'x': 30, 'y': 20, 'width': 180, 'height': 30}}],
    }])

    slide = inspect_office('pptx', edited)['slides'][0]
    target = next(item for item in slide['elements'] if item['text'] == '第一张')
    inserted = next(item for item in slide['elements'] if item['text'] == '新增文本')
    assert target['geometry'] == {'x': 100, 'y': 80, 'width': 400, 'height': 90}
    assert target['textStyle']['fontSizePt'] == 24
    assert inserted['geometry'] == {'x': 40, 'y': 20, 'width': 240, 'height': 30}
    shape = next(shape for shape in Presentation(BytesIO(edited)).slides[0].shapes if shape.has_text_frame and shape.text == '新增文本')
    assert shape.left == 40 * 9525 and shape.width == 240 * 9525


def test_real_pptx_animation_directions_roundtrip_for_fly_and_wipe_effects():
    from smart_reporting.report_editor.native_office import inspect_office,patch_office
    from pptx import Presentation
    from pptx.util import Inches

    directions = [
        ('flyIn', 'top'), ('flyIn', 'bottom'), ('flyIn', 'left'), ('flyIn', 'right'),
        ('wipe', 'top'), ('wipe', 'bottom'), ('wipe', 'left'), ('wipe', 'right'),
        ('wipeOut', 'top'), ('wipeOut', 'bottom'), ('wipeOut', 'left'), ('wipeOut', 'right'),
    ]
    presentation = Presentation()
    for index in range(len(directions)):
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)).text = f'页面 {index}'
    stream = BytesIO()
    presentation.save(stream)
    content = stream.getvalue()
    model = inspect_office('pptx', content)

    edited = patch_office('pptx', content, [{
        'kind': 'editSlides',
        'animations': [
            {'slideIndex': index, 'elementId': model['slides'][index]['elements'][0]['id'],
             'effect': effect, 'trigger': 'onClick', 'direction': direction}
            for index, (effect, direction) in enumerate(directions)
        ],
    }])

    reopened = inspect_office('pptx', edited)
    actual = [
        (animation['effect'], animation.get('direction', 'bottom'))
        for slide in reopened['slides']
        for animation in slide['animations']
    ]
    assert actual == directions


def test_real_pptx_animation_append_preserves_order_and_timing_on_readback():
    from smart_reporting.report_editor.native_office import inspect_office,patch_office

    content = presentation_bytes()
    model = inspect_office('pptx', content)
    target = next(item for item in model['slides'][0]['elements'] if item['editable'] and item['text'].strip())
    edits = [
        {'slideIndex': 0, 'elementId': target['id'], 'effect': 'fade', 'trigger': 'withPrev',
         'durationMs': 700, 'delayMs': 50, 'append': True},
        {'slideIndex': 0, 'elementId': target['id'], 'effect': 'pulse', 'trigger': 'afterPrev',
         'durationMs': 900, 'delayMs': 100, 'append': True},
    ]

    edited = patch_office('pptx', content, [{'kind': 'editSlides', 'animations': edits}])

    animations = inspect_office('pptx', edited)['slides'][0]['animations']
    assert [(item['effect'], item['trigger'], item['durationMs'], item['delayMs']) for item in animations] == [
        ('fade', 'withPrev', 700, 50), ('pulse', 'afterPrev', 900, 100),
    ]


def test_real_pptx_selected_text_formatting_roundtrips_through_inspect():
    from smart_reporting.report_editor.native_office import inspect_office,patch_office
    content = presentation_bytes()
    model = inspect_office('pptx', content)
    target = next(item for item in model['slides'][0]['elements'] if item['editable'] and item['text'].strip())

    edited = patch_office('pptx', content, [{
        'kind': 'editSlides',
        'theme': 'modern',
        'textFormatting': [{
            'slideIndex': 0, 'elementId': target['id'], 'fontSizePt': 24,
            'fontFamily': 'Arial', 'color': '#123456', 'bold': True,
            'italic': True, 'underline': True, 'strike': True,
        }],
    }])

    reopened = inspect_office('pptx', edited)
    formatted = next(item for item in reopened['slides'][0]['elements'] if item['id'] == target['id'])['textStyle']
    assert formatted == {
        'fontSizePt': 24, 'fontFamily': 'Arial', 'color': '#123456', 'bold': True,
        'italic': True, 'underline': True, 'strike': True,
    }
    original = next(item for item in inspect_office('pptx', content)['slides'][0]['elements'] if item['id'] == target['id'])
    assert original['textStyle'] != formatted


def test_real_pptx_paragraph_alignment_roundtrips_through_inspect():
    from smart_reporting.report_editor.native_office import inspect_office,patch_office
    content = presentation_bytes()
    model = inspect_office('pptx', content)
    target = next(item for item in model['slides'][0]['elements'] if item['editable'] and item['text'].strip())

    edited = patch_office('pptx', content, [{
        'kind': 'editSlides',
        'paragraphFormatting': [{'slideIndex': 0, 'elementId': target['id'], 'align': 'center'}],
    }])

    reopened = inspect_office('pptx', edited)
    actual = next(item for item in reopened['slides'][0]['elements'] if item['id'] == target['id'])
    original = next(item for item in inspect_office('pptx', content)['slides'][0]['elements'] if item['id'] == target['id'])
    assert actual['paragraphAlignments'] == ['center']
    assert original['paragraphAlignments'] != ['center']


def test_xlsx_unknown_operation_fields_are_rejected_before_engine(monkeypatch):
    from smart_reporting.report_editor import native_office
    engine=Mock();monkeypatch.setattr(native_office,'patch_workbook',engine)
    with pytest.raises(ValueError):native_office.patch_office('xlsx',b'source',[{'kind':'applyCellEdits','edits':[],'unknown':True}])
    engine.assert_not_called()


def test_real_pptx_new_slide_roundtrips_with_source_layout_and_order():
    from smart_reporting.report_editor.native_office import inspect_office,patch_office
    content=presentation_bytes();model=inspect_office('pptx',content)
    edited=patch_office('pptx',content,[{'kind':'editSlides','edits':[],'order':[0,2,1],'newSlides':[{'layoutFrom':0}]}])
    reopened=inspect_office('pptx',edited)['slides']
    assert len(reopened)==3 and reopened[1]['elements']==[]
    assert reopened[1]['layoutPath']==model['slides'][0]['layoutPath']
    assert [item['elements'][0]['text'] for item in (reopened[0],reopened[2])]==['第一张','第二张']


@pytest.mark.parametrize('new_slides', [[{'layoutFrom':-1}], [{'layoutFrom':0,'x':1}], [{}], 'one', [{'layoutFrom':0}]*51])
def test_invalid_new_slides_never_call_engine(monkeypatch,new_slides):
    from smart_reporting.report_editor import native_office
    engine=Mock();monkeypatch.setattr(native_office.ReportSlidesEditorService,'_run_engine',engine)
    with pytest.raises(ValueError):native_office.patch_office('pptx',presentation_bytes(),[{'kind':'editSlides','order':[0,1,2],'newSlides':new_slides}])
    with pytest.raises(ValueError):native_office.patch_office('pptx',presentation_bytes(),[{'kind':'editSlides','newSlides':[{'layoutFrom':0}]}])
    engine.assert_not_called()
