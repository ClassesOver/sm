"""六项缩进必须有实际末端能力登记，历史缺口身份继续保留。"""

from smart_reporting.preferences.approval_contract import approval_contract
from smart_reporting.preferences.capabilities import unsupported_preference_reason

INDENTS = ('signature.indent', 'typography.body.indent', 'typography.h1.indent',
    'typography.table.indent', 'typography.caption.indent', 'footerStyle.indent')


def test_exact_six_native_indent_consumers_are_editable_without_erasing_history():
    contract = approval_contract()
    fields = {row['path']: row for row in contract['fields']}
    for local in INDENTS:
        path = 'pptx.' + local
        field = fields[path]
        assert unsupported_preference_reason('pptx', path) is None, path
        assert field['support'] == 'implemented' and field['editable'], path
        assert field['consumer'].endswith('build-pptx.ts') and 'indent' in field['nativeProperty'], path
        assert field['legacyUnsupportedReason'], path
        assert any(row.get('path') == path for requirement in contract['requirements'] for row in requirement['checks'])
    assert {row['path'] for row in fields.values() if row['support'] == 'missing'} == {
        'xlsx.print.headerFooter.divider'}
    for format in ('pptx', 'pdf', 'word'):
        field = fields[f'{format}.charts.imageDpi']
        assert field['support'] == 'implemented' and field['editable']
        assert field['nativeProperty'] and field['legacyUnsupportedReason']
    for local in ('typography.h2.indent', 'typography.h3.indent'):
        assert fields['pptx.' + local]['support'] == 'not_applicable'
        assert unsupported_preference_reason('pptx', 'pptx.' + local)
