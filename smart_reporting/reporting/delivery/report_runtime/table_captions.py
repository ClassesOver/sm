"""从已核验修订索引投影表题；不从普通正文猜表名或改写源文件。"""

import re
from collections import Counter
from hashlib import sha256
from html import escape

from markdown_it import MarkdownIt

from ...trace.contracts_v1 import RevisionTraceIndexV1, derive_resource_id
from ...trace.markdown_body import registered_table_captions
from ..artifacts_v1 import ReportArtifactManifest, _markdown_table_artifacts
from .validation import _input_path


def _issue(code, message):
    return {'code': code, 'message': message}


def validate_table_caption_input(value, source_markdown_bytes):
    """纯校验：字节身份、修订归属和原生表块均需一致。"""
    try:
        manifest = ReportArtifactManifest.model_validate(value['manifest'])
        raw = value['traceIndexText'].encode('utf-8')
        source = value['markdownText'].encode('utf-8')
        identity = manifest.trace_index
        if (source != source_markdown_bytes or len(source) != manifest.markdown.size
            or sha256(source).hexdigest() != manifest.markdown.sha256 or identity is None
            or len(raw) != identity.size or sha256(raw).hexdigest() != identity.sha256):
            raise ValueError('table caption source bytes changed')
        index = RevisionTraceIndexV1.model_validate_json(raw)
        markdown_id = derive_resource_id(manifest.markdown.path)
        record = next(item for item in index.files if item.resource_id == markdown_id)
        if (index.report_id != manifest.report_id or index.revision != manifest.revision
            or index.report_basis_id != manifest.report_basis_id or index.markdown_file_resource_id != markdown_id
            or record.path != manifest.markdown.path or record.size != manifest.markdown.size
            or record.sha256 != manifest.markdown.sha256 or record.media_type != 'text/markdown'
            or not isinstance(value.get('workflowRunId'), str) or value['workflowRunId'] != index.workflow_run_id):
            raise ValueError('table caption revision identity mismatch')
        tables = _markdown_table_artifacts(source.decode().replace('\r\n', '\n').replace('\r', '\n'))
        if tables != manifest.tables:
            raise ValueError('table blocks differ from current manifest')
        registered = registered_table_captions(item.model_dump(mode='json', by_alias=True) for item in index.tables)
        table_ids = {item.table_id for item in manifest.tables}
        return {'status': 'verified', 'captions': {key: title for key, title in registered.items() if key in table_ids},
            'issues': [], 'source': {'markdown': manifest.markdown.model_dump(mode='json', by_alias=True),
                'traceIndex': identity.model_dump(mode='json', by_alias=True)}}
    except Exception:
        return {'status': 'unavailable', 'captions': {}, 'issues': [_issue('report_table_caption_source_unavailable',
            '表题登记来源无法与本修订实际正文和索引身份核对；保留原文和已生成文件，未猜测编号。')], 'source': None}


def load_table_caption_input(state, workspace, source_path, source_bytes):
    """运行时仅读取现有已绑定 manifest 的精确索引路径。"""
    try:
        manifest = ReportArtifactManifest.model_validate(state['_tableCaptionManifest'])
        if manifest.markdown.path != source_path or manifest.trace_index is None or manifest.trace_index.size > 32 * 1024 * 1024:
            raise ValueError('table caption input unavailable')
        index_path = _input_path(workspace, manifest.trace_index.path, '.json')
        if index_path.stat().st_size != manifest.trace_index.size:
            raise ValueError('table caption index size changed')
        raw = index_path.read_bytes()
        value = {'manifest': manifest.model_dump(mode='json', by_alias=True),
            'traceIndexText': raw.decode('utf-8'), 'markdownText': source_bytes.decode('utf-8')}
        if '_tableCaptionWorkflowRunId' in state:
            value['workflowRunId'] = state['_tableCaptionWorkflowRunId']
        return validate_table_caption_input(value, source_bytes)
    except Exception:
        return validate_table_caption_input(None, source_bytes)


def caption_bookmark(table_id):
    return 'tblcap_' + sha256(table_id.encode()).hexdigest()[:24]


_TABLE_BLOCK = re.compile(r'^\[\[table:(?P<id>[^\]\r\n]+)\]\]\n.*?^\[\[/table:(?P=id)\]\][ \t]*(?:\n|\Z)', re.MULTILINE | re.DOTALL)


def prepare_table_captions(markdown, captions):
    """仅保护精确登记且紧邻原生表块的原题；代码和人工改题不被覆盖。"""
    parser = MarkdownIt('commonmark').enable('table')
    tokens = parser.parse(markdown)
    paragraphs = {token.map[0]: tokens[index + 1].content for index, token in enumerate(tokens[:-1])
        if token.type == 'paragraph_open' and token.level == 0 and token.map and tokens[index + 1].type == 'inline'}
    matches = [match for match in _TABLE_BLOCK.finditer(markdown)
        if paragraphs.get(markdown.count('\n', 0, match.start())) == f'[[table:{match["id"]}]]']
    counts = Counter(match['id'] for match in matches)
    plans, replacements, issues = [], [], []
    source_digest = sha256(markdown.encode()).hexdigest()
    for match in matches:
        table_id = match['id']
        title = captions.get(table_id)
        prefix = (title + '\n\n') if isinstance(title, str) and title else None
        start = match.start() - len(prefix) if prefix else -1
        if (counts[table_id] != 1 or not prefix or start < 0 or markdown[start:match.start()] != prefix
            or paragraphs.get(markdown.count('\n', 0, start)) != title):
            issues.append(_issue('report_table_caption_unverified',
                f'表格 {table_id} 缺少可唯一核对的登记表题，或表题已修改；保留原文，未猜测编号。'))
            continue
        marker = 'REPORTING-TABLE-CAPTION-' + sha256((source_digest + str(start)).encode()).hexdigest()
        while marker in markdown:
            marker += '-X'
        plans.append({'tableId': table_id, 'caption': title, 'marker': marker})
        replacements.append((start, match.start() - 2, marker))
    prepared = markdown
    for start, end, marker in reversed(replacements):
        prepared = prepared[:start] + marker + prepared[end:]
    return prepared, plans, issues


def render_table_captions(body, plans, *, numbered):
    """标记只属于本次精确段落；同名普通段不会被套用 Caption。"""
    parser = MarkdownIt('commonmark', {'html': False})
    for number, plan in enumerate(plans, 1):
        label = ('表 ' + str(number) + '：') if numbered else ''
        title = parser.renderInline(plan['caption'])
        anchor = caption_bookmark(plan['tableId'])
        replacement = (f'<p class="report-table-caption" data-table-id="{escape(plan["tableId"], quote=True)}" '
            f'data-caption-anchor="{anchor}"><span id="{anchor}">{label}{title}</span></p>')
        body = body.replace('<p>' + plan['marker'] + '</p>', replacement, 1)
    return body
