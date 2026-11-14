"""管理验收的真实模板消费者收到冻结图片，而非通用布局替身。"""
import hashlib
import shutil
from io import BytesIO

from docx import Document

from smart_reporting.preferences.models import FormatPreferences
from smart_reporting.reporting.delivery.template_body import TEMPLATE_BODY_VERSION
from smart_reporting.tests.test_preference_preflight import _inputs
from smart_reporting.tests.test_preference_template_preflight import template_bytes


def test_template_preflight_generates_native_body_from_copied_frozen_resources(tmp_path):
    from smart_reporting.management.preference_template_preflight import generate_template_documents

    source = tmp_path / 'source'
    source.mkdir()
    draft, materials = _inputs(source)
    root = tmp_path / 'generation'
    inputs = root / 'inputs'
    inputs.mkdir(parents=True)
    for identity in materials.state['sources']:
        shutil.copyfile(source / identity['path'], inputs / identity['path'])
    template = template_bytes()
    (inputs / 'template.docx').write_bytes(template)
    frozen = {'markdownPath': materials.markdown_path, 'markdown': (source / 'report.md').read_text(),
        'state': materials.state, 'formats': ('word',),
        'templateSource': {'identity': {'path': 'template.docx'}}}
    generated = generate_template_documents(root, FormatPreferences.model_validate(draft['document']), frozen)
    raw = (root / 'report.docx').read_bytes()
    doc = Document(BytesIO(raw))
    tables = doc._element.body.xpath('.//w:tbl')
    assert len(tables) == 1
    assert [[''.join(cell.xpath('.//w:t/text()')) for cell in row.xpath('./w:tc')] for row in tables[0].xpath('./w:tr')] == [
        ['指标', '金额'], ['本期收入', '1234.56'], ['本期支出', '-234.56']]
    assert len(doc.inline_shapes) == 2
    assert doc.styles['Normal'].font.size.pt == 17
    assert doc.paragraphs[0].text == '保留业务引用：既有作者；2000-01-01'
    assert generated['word']['bodyBinding']['version'] == TEMPLATE_BODY_VERSION
    assert generated['word']['bodyBinding']['status'] == 'projected'
    assert (inputs / 'template.docx').read_bytes() == template
    assert hashlib.sha256((inputs / 'chart.png').read_bytes()).hexdigest() == hashlib.sha256((source / 'chart.png').read_bytes()).hexdigest()
