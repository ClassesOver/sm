"""从同一冻结数据修订汇编四格式；单格式或验收失败保留已生成文件。"""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from loguru import logger

from ..reporting.contract import safe_relative_posix_path
from ..reporting.delivery.pptx import build_editable_pptx
from ..reporting.delivery.report_runtime.runtime import ReportRuntime
from ..reporting.delivery.report_runtime.validation import ReportFailure, _reject_symlinks
from ..reporting.delivery.xlsx import build_workbook
from ..reporting.workflow.checkpoint import FileIdentity


def _identity(root, path):
    path = Path(path)
    _checked_path(root, path)
    raw = path.read_bytes()
    return FileIdentity(path=path.relative_to(root).as_posix(), size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest()).model_dump(mode='json')


def _read(root, identity):
    ref = FileIdentity.model_validate(identity)
    path = root.joinpath(*Path(ref.path).parts)
    _checked_path(root, path)
    raw = path.read_bytes()
    if len(raw) != ref.size or hashlib.sha256(raw).hexdigest() != ref.sha256:
        raise ValueError('data_revision_identity_changed')
    return raw


def _checked_path(root, path):
    try:
        _reject_symlinks(root, path)
        path.resolve().relative_to(root)
    except (ReportFailure, ValueError) as error:
        raise ValueError('data_revision_symlink_or_boundary_rejected') from error


def validate_data_revision_documents(runtime, state, artifacts, temporary_directory):
    if 'pdf' not in artifacts:
        return {'ok': False, 'issues': [{'code': 'report_data_pdf_unavailable', 'message': 'PDF未生成，未执行文档渲染验收。'}]}
    return runtime.validate_pdf(state, artifacts['pdf']['path'], temporary_directory,
        word_path=artifacts.get('word', {}).get('path'))


def render_data_revision_formats(*, root, snapshot, tables, job, output_root):
    """宿主入口只接服务端已核验清单；不运行模型，不重新绘图，不覆盖旧导出。

    新目录保留原Markdown相对图片路径，以当前修订PNG替换对应字节；原正文保留并
    明示待复核。数据表与图片均来自同一snapshot，业务公式不在此层猜测重算。
    """
    root = Path(root).resolve()
    target = root.joinpath(*safe_relative_posix_path(output_root, '导出目录无效').parts)
    _checked_path(root, target)
    target.mkdir(parents=True, exist_ok=False)
    issues = deepcopy(snapshot.get('warnings', []))
    artifacts, image_refs, image_entries, slides = {}, [], [], []
    documents, sheets, source_ranges, cells = {}, [], {}, []
    chart_revisions = {key: chart['chartRevision'] for key, chart in snapshot['charts'].items()}
    for n, (table_id, table) in enumerate(snapshot['tables'].items(), 1):
        raw = _read(root, table['file'])
        if raw != tables[table_id]:
            raise ValueError('data_revision_table_identity_changed')
        document = json.loads(raw)
        documents[table_id] = document
        name = f'数据{n}'
        rows = [document['columns'], *document['rows']]
        sheets.append({'name': name, 'rows': rows})
        # A1引用复用openpyxl已有列名转换，不自建工作簿表达式系统。
        from openpyxl.utils.cell import get_column_letter
        source_ranges[table_id] = {'sheetName': name, 'range': f'A1:{get_column_letter(len(document["columns"]))}{len(rows)}'}
        for row_number, row in enumerate(document['rows'], 2):
            for column_number, value in enumerate(row, 1):
                cells.append({'tableId': table_id, 'sheetName': name,
                    'cell': f'{get_column_letter(column_number)}{row_number}', 'value': value,
                    'sourceFile': table['file'], 'snapshotId': snapshot['snapshotId']})
    for n, (chart_id, chart) in enumerate(snapshot['charts'].items(), 1):
        image = chart['image']
        raw = _read(root, image)
        relative = safe_relative_posix_path(chart['originalRelativePath'], '图片相对路径无效')
        copied = target.joinpath(*relative.parts)
        _checked_path(root, copied)
        copied.parent.mkdir(parents=True, exist_ok=True)
        copied.write_bytes(raw)
        ref = _identity(root, copied)
        image_refs.append(ref)
        # 分页补图也纳入三种Office格式；文档附加页在正文后显式展示。
        images = [(ref, chart.get('title', chart_id))]
        for page_number, page in enumerate(chart.get('pages', []), 2):
            suffix = Path(page['image']['path']).suffix.lower()
            page_path = target / 'pages' / f'chart-{n}-page-{page_number}{suffix}'
            _checked_path(root, page_path)
            page_path.parent.mkdir(parents=True, exist_ok=True)
            page_path.write_bytes(_read(root, page['image']))
            page_ref = _identity(root, page_path)
            image_refs.append(page_ref)
            images.append((page_ref, f'{chart.get("title", chart_id)}（第{page_number}页）'))
        for page_number, (ref, title) in enumerate(images, 1):
            slides.append({'title': title, 'bullets': [chart.get('altText', ''), '数据已编辑，业务结论待复核。'],
                'evidenceIds': list(chart['tableIds']), 'chartPath': str(root / ref['path'])})
            image_entries.append({'imageId': f'chart-{n}-page-{page_number}', 'path': str(root / ref['path']),
                'identityPath': ref['path'],
                'size': ref['size'], 'sha256': ref['sha256'], 'chartId': chart_id,
                'snapshotId': snapshot['snapshotId'], 'chartRevision': chart['chartRevision'],
                'sheetName': f'图表{n}', 'range': f'A{2 + (page_number - 1) * 24}:L{23 + (page_number - 1) * 24}',
                'sourceRanges': [source_ranges[table_id] for table_id in chart['tableIds']],
                'sourceFiles': [{**snapshot['tables'][key]['file'],
                    'identityPath': snapshot['tables'][key]['file']['path'],
                    'path': str(root / snapshot['tables'][key]['file']['path'])} for key in chart['tableIds']]})
        sheets.append({'name': f'图表{n}', 'rows': [[chart.get('title', chart_id)], ['数据已编辑，业务结论待复核。']]})
    markdown = _read(root, snapshot['markdown']).decode('utf-8')
    markdown += '\n\n> 数据修订说明：本次图表使用用户编辑后的数据；原有正文、表格和图注结论保留，需重新复核。\n'
    for ref in image_refs:
        relative = (root / ref['path']).relative_to(target).as_posix()
        if relative.startswith('pages/'):
            markdown += f'\n![分页补图]({relative})\n'
    markdown_path = target / 'report.md'
    markdown_path.write_text(markdown, encoding='utf-8')
    state = deepcopy(job)
    state.update(sources=[table['file'] for table in snapshot['tables'].values()],
        render={'images': image_refs})
    runtime = ReportRuntime(root)
    temporary = f'.reporting-tmp/workspace-report-data-{target.name}'
    try:
        rendered = runtime.render_markdown(state, str(markdown_path.relative_to(root)),
            str((target / 'report.pdf').relative_to(root)),
            f'{temporary}-render/render.pdf',
            word_output_path=str((target / 'report.docx').relative_to(root)))
        state['render'] = rendered['render']
        issues.extend(rendered.get('renderIssues', []))
    except Exception as error:
        logger.warning('report_data_document_render_failed error_type={}', type(error).__name__)
        issues.append({'code': 'report_data_document_render_failed', 'message': 'PDF/Word汇编发生错误，保留已生成且可读的文件。'})
    for label, suffix in [('pdf', '.pdf'), ('word', '.docx')]:
        path = target / f'report{suffix}'
        try:
            artifacts[label] = _identity(root, path)
        except (OSError, ValueError):
            issues.append({'code': f'report_data_{label}_unavailable', 'message': f'{label}未生成或无法读取文件身份。'})
    try:
        validation = validate_data_revision_documents(runtime, state, artifacts,
            f'{temporary}-validate')
        issues.extend(validation.get('issues', []))
        if not validation.get('ok', False) and not validation.get('issues'):
            issues.append({'code': 'report_data_document_validation_failed', 'message': '文档验收未通过。'})
    except Exception as error:
        logger.warning('report_data_document_validation_failed error_type={}', type(error).__name__)
        issues.append({'code': 'report_data_document_validation_failed', 'message': '文档验收未完成；保留实际产物且不标记通过。'})
    for label, suffix, build in [
        ('pptx', '.pptx', lambda path: build_editable_pptx(output_path=path, title='数据修订报告', period='', theme='executive', slides=tuple(slides))),
        ('xlsx', '.xlsx', lambda path: build_workbook(output_path=path, title='数据修订报告', period='', sheets=tuple(sheets),
            source_mapping={'snapshotId': snapshot['snapshotId'], 'chartRevisions': chart_revisions, 'cells': cells}, images=tuple(image_entries))),
    ]:
        path = target / f'report{suffix}'
        try:
            built = build(path)
            artifacts[label] = _identity(root, path)
            issues.extend({'code': f'report_data_{label}_layout_warning', **issue} for issue in built.issues)
        except Exception as error:
            logger.warning('report_data_office_render_failed format={} error_type={}', label, type(error).__name__)
            issues.append({'code': f'report_data_{label}_render_failed', 'message': f'{label}汇编失败；保留其他格式及本格式已生成的可读文件。'})
        if label not in artifacts:
            try:
                artifacts[label] = _identity(root, path)
            except (OSError, ValueError):
                issues.append({'code': f'report_data_{label}_unavailable',
                    'message': f'{label}未生成或无法读取文件身份。'})
    return {'snapshotId': snapshot['snapshotId'], 'chartRevisions': chart_revisions,
        'artifacts': artifacts, 'validation': {'ok': not issues, 'issues': issues}}
