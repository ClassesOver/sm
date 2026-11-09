from __future__ import annotations

import hashlib
from io import BytesIO
from zipfile import ZipFile

from openpyxl import load_workbook


def test_workbook_roundtrip_preserves_types_formulas_styles_and_sources(tmp_path):
    from smart_reporting.reporting.delivery.xlsx import (
        build_workbook,
        inspect_workbook,
        patch_workbook,
    )

    output = tmp_path / 'report.xlsx'
    built = build_workbook(
        output_path=output,
        title='部门经营汇总',
        period='2026-10',
        sheets=(
            {'name': '汇总', 'rows': [['部门经营汇总'], ['收入', {'value': 120.5, 'formula': "='经营报表'!B2"}]]},
            {'name': '经营报表', 'rows': [['项目', '金额', '缺失', '是否核实'], ['收入', 120.5, None, True]], 'headerRow': 0},
        ),
        source_mapping={'经营报表!B2': {'datasetId': 'sales', 'sha256': 'a' * 64, 'unit': '元'}},
    )
    original = output.read_bytes()
    assert built.sha256 == hashlib.sha256(original).hexdigest()
    assert built.size == len(original)
    book = load_workbook(BytesIO(original), data_only=False)
    assert book.sheetnames == ['汇总', '经营报表']
    assert book['汇总']['B2'].value == "='经营报表'!B2"
    assert load_workbook(BytesIO(original), data_only=True)['汇总']['B2'].value == 120.5
    assert book['经营报表']['B2'].value == 120.5
    assert book['经营报表']['C2'].value is None
    assert book['经营报表']['D2'].value is True
    assert book['经营报表']['A1'].font.bold
    assert book['经营报表'].freeze_panes == 'A2'
    assert book['经营报表'].page_setup.orientation == 'landscape'
    assert book['经营报表'].sheet_properties.pageSetUpPr.fitToPage
    assert book['经营报表'].page_setup.fitToHeight == 0
    assert 'smart-reporting/source-mapping.json' in ZipFile(BytesIO(original)).namelist()
    model = inspect_workbook(original)
    assert model['sheets'][1]['cells']['B2']['value'] == 120.5
    edited = patch_workbook(original, [
        {'kind': 'applyCellEdits', 'edits': [{'sheetName': '经营报表', 'row': 1, 'column': 1, 'writeValue': True, 'cell': {'value': 0}}]},
        {'kind': 'applySheetEdits', 'plan': {'renames': [{'sheetName': '经营报表', 'newName': '经营明细'}], 'additions': [], 'removals': [], 'order': ['汇总', '经营明细']}},
    ])
    changed = load_workbook(BytesIO(edited), data_only=False)
    assert changed['经营明细']['B2'].value == 0
    assert changed['汇总']['B2'].value == "='经营明细'!B2"
    assert changed['经营明细']['A1'].font.bold
    assert load_workbook(BytesIO(original))['经营报表']['B2'].value == 120.5


def test_workbook_patch_rejects_unknown_operation(tmp_path):
    import pytest

    from smart_reporting.reporting.delivery.xlsx import build_workbook, patch_workbook

    output = tmp_path / 'report.xlsx'
    build_workbook(output_path=output, title='汇总', period='', sheets=({'name': '汇总', 'rows': [['金额'], [0]]},))
    with pytest.raises(ValueError, match='workbook_operation_invalid'):
        patch_workbook(output.read_bytes(), [{'kind': 'unknown'}])


def test_workbook_merge_unmerge_can_be_saved_and_reopened(tmp_path):
    from smart_reporting.reporting.delivery.xlsx import (
        build_workbook,
        inspect_workbook,
        patch_workbook,
    )

    output = tmp_path / 'report.xlsx'
    build_workbook(output_path=output, title='汇总', period='', sheets=(
        {'name': '汇总', 'rows': [['标题'], ['指标', 12.5]]},
    ))
    original = output.read_bytes()
    merged = patch_workbook(original, [{'kind': 'applySheetMerges', 'sheetName': '汇总', 'ranges': ['A1:C1']}])
    assert inspect_workbook(merged)['sheets'][0]['merges'] == ['A1:C1']
    sheet = load_workbook(BytesIO(merged))['汇总']
    assert str(sheet.merged_cells) == 'A1:C1'
    assert sheet['A1'].value == '标题'
    assert sheet['A1'].font.bold
    assert sheet['B2'].value == 12.5
    unmerged = patch_workbook(merged, [{'kind': 'applySheetMerges', 'sheetName': '汇总', 'ranges': []}])
    sheet = load_workbook(BytesIO(unmerged))['汇总']
    assert not sheet.merged_cells
    assert sheet['A1'].value == '标题'
    assert output.read_bytes() == original


def test_workbook_bridge_reuses_sort_structure_rules_table_pivot_and_page_setup(tmp_path):
    from smart_reporting.reporting.delivery.xlsx import (
        build_workbook,
        inspect_workbook,
        patch_workbook,
    )

    output = tmp_path / 'report.xlsx'
    build_workbook(output_path=output, title='收入汇总', period='2026-10', sheets=(
        {'name': '明细', 'rows': [['部门', '收入'], ['乙', 20], ['甲', 10], ['乙', 5]]},
        {'name': '透视', 'rows': [['汇总']]},
    ))
    content = patch_workbook(output.read_bytes(), [
        {'kind': 'sortRange', 'sheetName': '明细', 'spec': {'range': 'A1:B4', 'byColumn': 'B', 'ascending': True, 'hasHeader': True}},
        {'kind': 'applyRowColumnOps', 'sheetName': '明细', 'ops': [{'kind': 'insert-rows', 'index': 4, 'count': 1}]},
        {'kind': 'applyTableAdditions', 'additions': [{'worksheetSheetName': '明细', 'area': {'startRow': 0, 'startColumn': 0, 'endRow': 3, 'endColumn': 1}, 'name': 'Revenue', 'columnNames': ['部门', '收入'], 'bandedRows': True}]},
        {'kind': 'applyDvRules', 'rules': [{'sheet': '明细', 'sqref': 'B2:B4', 'type': 'decimal', 'operator': 'greaterThanOrEqual', 'formula1': '0'}]},
        {'kind': 'applyCfRules', 'rules': [{'kind': 'dataBar', 'sheet': '明细', 'sqref': 'B2:B4', 'min': {'type': 'min'}, 'max': {'type': 'max'}, 'color': '#4472C4'}]},
        {'kind': 'applyPageSetups', 'setups': [{'sheetName': '明细', 'orientation': 'landscape', 'frozenRows': 1, 'printArea': 'A1:B4', 'fitToWidth': 1}]},
        {'kind': 'addPivot', 'addition': {
            'worksheetSheetName': '透视', 'sourceSheetName': '明细',
            'sourceArea': {'startRow': 0, 'startColumn': 0, 'endRow': 3, 'endColumn': 1},
            'location': {'startRow': 2, 'startColumn': 0, 'endRow': 5, 'endColumn': 1},
            'name': 'ByDepartment', 'fieldNames': ['部门', '收入'], 'rowFieldIndices': [0],
            'rowLevelItems': [['乙', '甲']], 'rowLines': [{'t': 'data', 'members': [0]}, {'t': 'data', 'members': [1]}],
            'values': [{'fieldIndex': 1, 'agg': 'sum'}],
        }},
        {'kind': 'refreshPivotCaches'},
    ])
    model = inspect_workbook(content)
    assert model['sheets'][0]['cells']['B2']['value'] == 5
    book = load_workbook(BytesIO(content))
    assert book['明细']['B3'].value == 10
    assert 'Revenue' in book['明细'].tables
    assert book['明细'].tables['Revenue'].autoFilter.ref == 'A1:B4'
    assert book['明细'].data_validations.count == 1
    assert len(book['明细'].conditional_formatting) == 1
    assert book['明细'].freeze_panes == 'A2'
    assert book['明细'].page_setup.orientation == 'landscape'
    assert book['透视']._pivots[0].name == 'ByDepartment'
    assert book['透视']['B4'].value == 25
    assert book['透视']['B5'].value == 10


def _static_image(tmp_path, *, kind='PNG', color='navy', image_id='revenue'):
    from PIL import Image

    path = tmp_path / f'{image_id}.{kind.lower()}'
    Image.new('RGB', (120, 80), color=color).save(path, format=kind)
    content = path.read_bytes()
    return {
        'imageId': image_id, 'path': str(path), 'size': len(content),
        'sha256': hashlib.sha256(content).hexdigest(), 'sheetName': '汇总',
        'range': 'D2:L18', 'chartId': 'revenue', 'snapshotId': 'snapshot-1',
        'chartRevision': 'revision-1',
        'sourceRanges': [{'sheetName': '汇总', 'range': 'A1:B2'}],
    }


def test_workbook_image_mapping_keeps_relative_identity_without_host_read_paths(tmp_path):
    import json

    from smart_reporting.reporting.delivery.xlsx import build_workbook

    image = _static_image(tmp_path)
    image['identityPath'] = 'reports/revision-new/chart.png'
    source = tmp_path / 'private-source.json'
    source.write_bytes(b'{"value":180}')
    image['sourceFiles'] = [{'path': str(source), 'identityPath': 'reports/data/input.json',
        'size': source.stat().st_size, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}]
    output = tmp_path / 'mapped.xlsx'
    result = build_workbook(output_path=output, title='修订', period='',
        sheets=({'name': '汇总', 'rows': [['期间', '值'], ['2026-10', 180]]},), images=(image,))
    assert not result.issues
    with ZipFile(output) as archive:
        raw = archive.read('smart-reporting/source-mapping.json').decode()
    mapping = json.loads(raw)
    assert str(tmp_path) not in raw
    assert mapping['images'][0]['path'] == image['identityPath']
    assert mapping['images'][0]['sourceFiles'][0]['path'] == 'reports/data/input.json'
    assert 'identityPath' not in raw


def test_workbook_embeds_verified_png_jpeg_with_sources_and_formula_cache(tmp_path):
    import json

    from smart_reporting.reporting.delivery.xlsx import build_workbook, inspect_workbook

    images = (_static_image(tmp_path), _static_image(tmp_path, kind='JPEG', image_id='cost'))
    sources = {'snapshotId': 'snapshot-1', 'chartRevisions': {'revenue': 'revision-1'},
               'cells': [{'sheetName': '汇总', 'cell': 'B2', 'datasetId': 'sales'}]}
    output = tmp_path / 'report.xlsx'
    result = build_workbook(output_path=output, title='汇总', period='2026-10',
        sheets=({'name': '汇总', 'rows': [['收入', '金额'], [120, {'value': 240, 'formula': 'A2*2'}]]},),
        source_mapping=sources, images=images)
    assert not result.issues
    book = load_workbook(output)
    assert book['汇总']['B2'].value == '=A2*2'
    assert load_workbook(output, data_only=True)['汇总']['B2'].value == 240
    assert len(book['汇总']._images) == 2
    assert (book['汇总']._images[0].anchor._from.col, book['汇总']._images[0].anchor._from.row) == (3, 1)
    with ZipFile(output) as archive:
        mapping = json.loads(archive.read('smart-reporting/source-mapping.json'))
        assert mapping['sources'] == sources
        assert len(mapping['images']) == 2
        assert not any(name.startswith('xl/charts/') for name in archive.namelist())
        for source, stored in zip(images, mapping['images']):
            assert archive.read(stored['mediaPart']) == __import__('pathlib').Path(source['path']).read_bytes()
            assert stored['snapshotId'] == 'snapshot-1'
            assert stored['chartRevision'] == 'revision-1'
            assert stored['sourceRanges'] == source['sourceRanges']
            assert stored['range'] == 'D2:L18'
            assert stored['sha256'] == source['sha256']
    inspected = inspect_workbook(output.read_bytes())
    assert inspected['sourceMapping'] == mapping
    assert len(inspected['images']) == 2


def test_workbook_static_image_replacement_preserves_data_and_source_mapping(tmp_path):
    import json

    from smart_reporting.reporting.delivery.xlsx import build_workbook, inspect_workbook, patch_workbook

    image = _static_image(tmp_path)
    output = tmp_path / 'report.xlsx'
    sources = {'snapshotId': 'snapshot-1', 'cells': [{'cell': 'A2', 'datasetId': 'sales'}]}
    build_workbook(output_path=output, title='汇总', period='',
        sheets=({'name': '汇总', 'rows': [['收入'], [120, {'value': 240, 'formula': 'A2*2'}]]},),
        source_mapping=sources, images=(image,))
    original = output.read_bytes()
    replacement = _static_image(tmp_path, kind='JPEG', color='teal')
    replacement['chartRevision'] = 'revision-2'
    edited = patch_workbook(original, [{'kind': 'applyStaticImages', 'images': [replacement]}])
    assert load_workbook(BytesIO(edited))['汇总']['A2'].value == 120
    assert load_workbook(BytesIO(edited))['汇总']['B2'].value == '=A2*2'
    assert load_workbook(BytesIO(edited), data_only=True)['汇总']['B2'].value == 240
    assert len(load_workbook(BytesIO(edited))['汇总']._images) == 1
    with ZipFile(BytesIO(edited)) as archive:
        mapping = json.loads(archive.read('smart-reporting/source-mapping.json'))
        assert mapping['sources'] == sources
        assert mapping['images'][0]['chartRevision'] == 'revision-2'
        assert archive.read(mapping['images'][0]['mediaPart']) == __import__('pathlib').Path(replacement['path']).read_bytes()
        assert len([name for name in archive.namelist() if name.startswith('xl/media/') and not name.endswith('/')]) == 1
    assert inspect_workbook(original)['images'][0]['sha256'] == image['sha256']


def test_workbook_rejects_changed_invalid_and_foreign_image_without_losing_cells(tmp_path):
    from pathlib import Path

    from smart_reporting.reporting.delivery.xlsx import build_workbook, inspect_workbook, patch_workbook

    image = _static_image(tmp_path)
    output = tmp_path / 'report.xlsx'
    sources = {'snapshotId': 'snapshot-1'}
    build_workbook(output_path=output, title='汇总', period='',
        sheets=({'name': '汇总', 'rows': [['收入'], [120]]},), source_mapping=sources, images=(image,))
    original = output.read_bytes()
    Path(image['path']).write_bytes(b'not-an-image')
    edited = patch_workbook(original, [{'kind': 'applyStaticImages', 'images': [image]}])
    assert inspect_workbook(edited)['images'][0]['sha256'] == image['sha256']
    assert load_workbook(BytesIO(edited))['汇总']['A2'].value == 120
    invalid = {**image, 'size': 12, 'sha256': hashlib.sha256(b'not-an-image').hexdigest()}
    foreign = {**_static_image(tmp_path, image_id='foreign'), 'snapshotId': 'snapshot-other'}
    result = build_workbook(output_path=tmp_path / 'rejected.xlsx', title='汇总', period='',
        sheets=({'name': '汇总', 'rows': [['收入'], [120]]},), source_mapping=sources, images=(invalid, foreign))
    assert len(result.issues) == 2
    assert {issue['imageId'] for issue in result.issues} == {'revenue', 'foreign'}
    assert not inspect_workbook((tmp_path / 'rejected.xlsx').read_bytes())['images']
    assert load_workbook(tmp_path / 'rejected.xlsx')['汇总']['A2'].value == 120


def test_workbook_rejects_changed_image_source_file_identity(tmp_path):
    from smart_reporting.reporting.delivery.xlsx import build_workbook, inspect_workbook

    image = _static_image(tmp_path)
    source = tmp_path / 'data.csv'
    source.write_bytes(b'value\n120\n')
    image['sourceFiles'] = [{'path': str(source), 'size': len(source.read_bytes()),
                             'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}]
    source.write_bytes(b'value\n150\n')
    output = tmp_path / 'report.xlsx'
    result = build_workbook(output_path=output, title='汇总', period='',
        sheets=({'name': '汇总', 'rows': [['收入'], [120]]},), images=(image,))
    assert result.issues and result.issues[0]['imageId'] == 'revenue'
    assert not inspect_workbook(output.read_bytes())['images']


def test_workbook_patch_rejected_image_exposes_issue_and_retains_original(tmp_path):
    from pathlib import Path

    from smart_reporting.reporting.delivery.xlsx import build_workbook, inspect_workbook, patch_workbook

    image = _static_image(tmp_path)
    output = tmp_path / 'report.xlsx'
    build_workbook(output_path=output, title='汇总', period='',
        sheets=({'name': '汇总', 'rows': [['收入'], [120]]},), images=(image,))
    Path(image['path']).write_bytes(b'changed-after-render')
    edited = patch_workbook(output.read_bytes(), [{'kind': 'applyStaticImages', 'images': [image]}])
    inspected = inspect_workbook(edited)
    assert inspected['sourceMapping']['imageIssues'][0]['imageId'] == 'revenue'
    assert inspected['images'][0]['sha256'] == image['sha256']


def test_workbook_node_rechecks_image_and_source_files_after_python_validation(tmp_path, monkeypatch):
    from pathlib import Path

    from smart_reporting.reporting.delivery import xlsx

    original_invoke = xlsx._invoke
    for changed in ('image', 'source'):
        image = _static_image(tmp_path)
        source = tmp_path / 'data.csv'
        source.write_bytes(b'value\n120\n')
        image['sourceFiles'] = [{'path': str(source), 'size': len(source.read_bytes()),
                                'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}]
        def replace_then_invoke(payload):
            if payload['kind'] == 'create':
                Path(image['path'] if changed == 'image' else source).write_bytes(b'changed-after-validation')
            return original_invoke(payload)
        monkeypatch.setattr(xlsx, '_invoke', replace_then_invoke)
        output = tmp_path / f'{changed}.xlsx'
        result = xlsx.build_workbook(output_path=output, title='汇总', period='',
            sheets=({'name': '汇总', 'rows': [['收入'], [120]]},), images=(image,))
        assert result.issues[0]['message'] == 'workbook_image_identity_changed'
        assert not xlsx.inspect_workbook(output.read_bytes())['images']
        assert load_workbook(output)['汇总']['A2'].value == 120


def test_workbook_image_new_snapshot_preserves_existing_cell_source_mapping(tmp_path):
    from smart_reporting.reporting.delivery.xlsx import build_workbook, inspect_workbook, patch_workbook

    image = _static_image(tmp_path)
    output = tmp_path / 'report.xlsx'
    cells = [{'sheetName': '汇总', 'cell': 'A2', 'datasetId': 'sales'}]
    build_workbook(output_path=output, title='汇总', period='',
        sheets=({'name': '汇总', 'rows': [['收入'], [120]]},),
        source_mapping={'snapshotId': 'snapshot-1', 'cells': cells}, images=(image,))
    revised = {**_static_image(tmp_path, color='teal'), 'snapshotId': 'snapshot-2', 'chartRevision': 'revision-2'}
    edited = patch_workbook(output.read_bytes(), [{'kind': 'applyStaticImages', 'images': [revised],
        'sourceMapping': {'snapshotId': 'snapshot-2', 'chartRevisions': {'revenue': 'revision-2'}}}])
    inspected = inspect_workbook(edited)
    assert inspected['sourceMapping']['sources']['cells'] == cells
    assert inspected['images'][0]['snapshotId'] == 'snapshot-2'
    assert inspected['images'][0]['chartRevision'] == 'revision-2'
