"""从已核身份的冻结事实复用正式表体投影；不读取自由正文或图片。"""

from hashlib import sha256

from markdown_it import MarkdownIt


def normalize_slide_table(table):
    from ..workflow.checkpoint import FileIdentity

    if not isinstance(table, dict) or set(table) != {
        'tableId', 'caption', 'headers', 'rows', 'sourceAnalysisId', 'sourceFile',
    }:
        raise ValueError('pptx_table_input_invalid')
    if any(not isinstance(table[key], str) or not table[key].strip()
           for key in ('tableId', 'sourceAnalysisId')) or not isinstance(table['caption'], str):
        raise ValueError('pptx_table_input_invalid')
    headers, rows = table['headers'], table['rows']
    if (not isinstance(headers, list) or not headers or not isinstance(rows, list) or not rows
            or not all(isinstance(cell, str) for cell in headers)
            or any(not isinstance(row, list) or len(row) != len(headers)
                or not all(isinstance(cell, str) for cell in row) for row in rows)):
        raise ValueError('pptx_table_input_invalid')
    source = FileIdentity.model_validate(table['sourceFile'])
    return {**table, 'sourceFile': source.model_dump(mode='json', by_alias=True)}


def project_fact_slide_tables(analysis_id, source_file, raw):
    """只解码服务端生成的表格语法，沿用既有数值显示和稳定 tableId。"""
    from ..hospital_operation.deterministic_analysis import DeterministicAnalysisBundle
    from ..trace.contracts_v1 import derive_resource_id
    from ..trace.table_builder import build_analysis_tables

    if len(raw) != source_file.size or sha256(raw).hexdigest() != source_file.sha256:
        raise ValueError('pptx_table_source_identity_mismatch')
    bundle = DeterministicAnalysisBundle.model_validate_json(raw)
    if bundle.analysis_id != analysis_id:
        raise ValueError('pptx_table_source_analysis_mismatch')
    projected = []
    parser = MarkdownIt('commonmark').enable('table')
    for trace, markdown in build_analysis_tables(bundle, fact_file_resource_id=derive_resource_id(source_file.path)):
        tokens = parser.parse(markdown)
        grid, row, inside = [], None, False
        for token in tokens:
            if token.type == 'table_open':
                inside = True
            elif token.type == 'table_close':
                inside = False
            elif inside and token.type == 'tr_open':
                row = []
            elif inside and token.type == 'inline' and row is not None:
                row.append(''.join(child.content for child in token.children or ()))
            elif inside and token.type == 'tr_close':
                grid.append(row)
        caption = markdown.split('[[table:', 1)[0].strip()
        projected.append(normalize_slide_table({'tableId': trace.table_id, 'caption': caption,
            'headers': grid[0], 'rows': grid[1:], 'sourceAnalysisId': analysis_id,
            'sourceFile': source_file.model_dump(mode='json', by_alias=True)}))
    return projected
