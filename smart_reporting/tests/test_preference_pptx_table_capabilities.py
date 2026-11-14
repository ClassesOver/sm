"""只开放真实原生表格消费的字段，历史拒绝清单继续作为迁移记录。"""

from smart_reporting.preferences.approval_contract import approval_contract
from smart_reporting.preferences.capabilities import unsupported_preference_reason

SUPPORTED = (
    'tables.repeatHeader', 'tables.borders', 'tables.striped', 'tables.captionNumbering',
    'typography.table.font', 'typography.table.size', 'typography.table.color',
    'typography.table.bold', 'typography.table.lineHeight',
    'typography.table.spaceBefore', 'typography.table.spaceAfter',
)


def test_only_consumed_pptx_table_properties_become_editable():
    fields = {field['path']: field for field in approval_contract()['fields']}
    for local in SUPPORTED:
        path = 'pptx.' + local
        assert unsupported_preference_reason('pptx', path) is None, path
        assert fields[path]['support'] == 'implemented', path
        assert fields[path]['editable'] is True, path
        assert fields[path]['consumer'] and fields[path]['nativeProperty'], path
        assert fields[path]['legacyUnsupportedReason'], '历史拒绝记录不能被覆盖'
    for local in ('tables.splitRows', 'typography.h2.font', 'typography.h3.font'):
        path = 'pptx.' + local
        assert unsupported_preference_reason('pptx', path), path
        assert fields[path]['editable'] is False, path
    assert fields['pptx.tables.splitRows']['support'] == 'not_applicable'


def test_current_refusals_preserve_historical_inventory_except_real_table_consumers():
    from smart_reporting.tests.test_preference_supported_changes import unsupported_paths

    historical = set(unsupported_paths())
    supported = {'pptx.' + local for local in SUPPORTED} | {'pptx.signature.spaceBefore'}
    supported.update('pptx.' + local for local in ('signature.indent', 'footerStyle.indent',
        'typography.body.indent', 'typography.h1.indent', 'typography.table.indent', 'typography.caption.indent'))
    supported.update(f'{format}.tables.captionNumbering' for format in ('word', 'pdf'))
    assert len(historical) == 65 and supported <= historical
    assert {path for path in historical if unsupported_preference_reason(path.split('.', 1)[0], path)} == historical - supported
