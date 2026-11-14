"""从冻结来源和全部原生单元格独立核验 Word 表格维护字段。"""

import re

from docx.oxml.ns import qn
from markdown_it import MarkdownIt

from .preference_document_table_readback import _UNPROVEN, _caption_visible

WORD_TABLE_FIELD_EVIDENCE = 'word_native_table_fields_v1'
TABLE_FIELDS = ('repeatHeader', 'splitRows', 'borders', 'striped')
TEXT_FIELDS = ('font', 'size', 'color', 'bold', 'lineHeight', 'spaceBefore', 'spaceAfter', 'indent')
_EDGES = ('top', 'left', 'bottom', 'right', 'insideH', 'insideV')
_FONTS = {'sans': 'Noto Sans CJK SC', 'serif': 'Noto Serif CJK SC'}
_HEADER_BREAK = re.compile(r'^([^\n]{2,}?)(（[^（）\n]{1,12}）)$')
_FALSE = ('0', 'false', 'off')


def _source_tables(frozen):
    """只还原可验证受控 HTML；由 Markdown token 推导表格和既定展示变换。"""
    from ..preferences.markdown_adapter import strip_table_preferences

    markdown = strip_table_preferences(frozen['markdown'])
    # 生产先处理登记块再解析 Markdown；关闭标记不属于最后一行单元格。
    markdown = re.sub(r'(?m)^(\[\[/table:[^\]\r\n]+\]\])$', r'\n\1', markdown)
    parser = MarkdownIt('commonmark', {'html': True}).enable('table')
    tokens = parser.parse(markdown)
    lines = markdown.splitlines()
    if any(token.type in ('html_block', 'html_inline') and re.search(r'</?table\b', token.content, re.I)
        for token in tokens):
        raise ValueError('HTML 表格未能与受控隐藏源相互验证。')
    tables, grid, row, source_cells, source_tables = [], None, None, 0, 0
    opening = None
    for token in tokens:
        if token.type == 'table_open':
            if token.level != 0 or grid is not None:
                raise ValueError('来源含未支持的嵌套表格。')
            grid, opening = [], token
        elif grid is not None and token.type == 'tr_open':
            row = []
            grid.append(row)
        elif grid is not None and token.type == 'inline':
            value = ''
            for child in token.children or []:
                if child.type in ('text', 'code_inline'):
                    value += child.content
                elif child.type in ('softbreak', 'hardbreak'):
                    value += '\n'
                elif child.type in ('strong_open', 'strong_close', 'em_open', 'em_close', 'link_open', 'link_close'):
                    continue
                else:
                    raise ValueError('来源表格含未核验的内嵌对象。')
            if re.search(r'\[\[[^\]\r\n]+\]\]', value) or '分别为' in value:
                raise ValueError('表格含尚未独立核验的来源标记或语义展示转换。')
            row.append(value)
        elif token.type == 'table_close' and grid is not None:
            if not grid or not grid[0] or any(len(item) != len(grid[0]) for item in grid):
                raise ValueError('来源表格网格不完整。')
            source_tables += 1
            source_cells += sum(map(len, grid))
            # 只有已登记、严格双列且至少八个期间的原表会每六期转置。
            start, end = opening.map
            while end < len(lines) and not lines[end].strip():
                end += 1
            registered = (start > 0 and end < len(lines) and
                re.fullmatch(r'\[\[table:([^\]\r\n]+)\]\]', lines[start - 1]))
            compact = (registered and lines[end] == '[[/table:' + registered[1] + ']]'
                and len(grid) >= 9 and len(grid[0]) == 2 and grid[0][0] == ''
                and all(line.startswith('|') and line.rstrip().endswith('|') for line in lines[start:opening.map[1]]))
            if compact:
                labels = [item[0] for item in grid[1:]]
                months = [re.fullmatch(r'(\d{4}年)(\d{1,2}月)', label) for label in labels]
                same_year = all(months) and len({month[1] for month in months}) == 1
                corner = months[0][1] if same_year else ''
                labels = [month[2] for month in months] if same_year else labels
                for index in range(0, len(labels), 6):
                    tables.append([[corner, *labels[index:index + 6]],
                        [grid[0][1], *(item[1] for item in grid[1 + index:7 + index])]])
            else:
                tables.append(grid)
            grid = None
    # 仅删除表头已声明的同一单位；数字字符串及精度原样保留。
    for grid in tables:
        for column, title in enumerate(grid[0]):
            unit = re.search(r'[（(](亿元|万元|元|万人次|人次|床日|%)[）)]\s*$', title)
            if unit:
                number = re.compile(r'([+\-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)' + re.escape(unit[1]))
                for row in grid[1:]:
                    match = number.fullmatch(row[column])
                    if match:
                        row[column] = match[1]
        grid[0] = [_HEADER_BREAK.sub(r'\1\n\2', value) for value in grid[0]]
    return tables, source_tables, source_cells


def _one(node, name):
    values = node.findall(qn('w:' + name)) if node is not None else []
    if len(values) > 1:
        raise ValueError('原生属性重复：' + name)
    return values[0] if values else None


def _attr(node, name, default=None):
    return node.get(qn('w:' + name), default) if node is not None else default


def _on(node):
    if node is None:
        return False
    value = _attr(node, 'val', 'true')
    if value not in (*_FALSE, '1', 'true', 'on'):
        raise ValueError('原生布尔属性无效。')
    return value not in _FALSE


def _unsupported_properties(properties):
    for node in properties.iter():
        if (node.tag in _UNPROVEN or node.tag in {qn('w:shd'), qn('w:highlight'), qn('w:numPr'), qn('w:contextualSpacing')}
            or node.tag in {qn('w:cs'), qn('w:rtl'), qn('w:vanish'), qn('w:webHidden'), qn('w:specVanish')} and _on(node)
            or node.tag == qn('w:spacing') and any(_attr(node, key) is not None
                for key in ('beforeLines', 'afterLines', 'beforeAutospacing', 'afterAutospacing'))
            or node.tag == qn('w:ind') and any(_attr(node, key) is not None
                for key in ('hanging', 'firstLineChars', 'hangingChars'))):
            return True
    return False


def _table_style_safe(document, table):
    """直接属性不足以证明复杂条件样式；不把无法解析的覆盖提升为完整证据。"""
    reference = _one(_one(table, 'tblPr'), 'tblStyle')
    identity = _attr(reference, 'val')
    if reference is not None and not identity:
        return False
    if reference is None:
        defaults = [style for style in document.styles.element.findall(qn('w:style'))
            if _attr(style, 'type') == 'table' and _attr(style, 'default') in ('1', 'true', 'on')]
        if len(defaults) > 1 or defaults and not _attr(defaults[0], 'styleId'):
            return False
        identity = _attr(defaults[0], 'styleId') if defaults else None
    seen = set()
    while identity:
        styles = [style for style in document.styles.element.findall(qn('w:style'))
            if _attr(style, 'styleId') == identity]
        if identity in seen or len(styles) != 1 or _attr(styles[0], 'type') != 'table':
            return False
        seen.add(identity)
        style = styles[0]
        if _unsupported_properties(style) or any(item.tag in {qn('w:tblStylePr'), qn('w:tcBorders')}
            for item in style.iter()):
            return False
        base = _one(style, 'basedOn')
        identity = _attr(base, 'val')
        if base is not None and not identity:
            return False
    return True


def _text_style_safe(document, paragraph):
    """复用隐藏/样式身份检查；额外拒绝未解析的继承脚本、底纹和自动编号。"""
    if not _caption_visible(document, paragraph):
        return False
    properties = [paragraph, *document.styles.element.findall(qn('w:docDefaults'))]
    styles = document.styles.element.findall(qn('w:style'))
    selected = [(_one(paragraph, 'pPr'), 'pStyle', 'paragraph')]
    selected.extend((_one(run, 'rPr'), 'rStyle', 'character') for run in paragraph.iter(qn('w:r')))
    for source, key, kind in selected:
        reference = _one(source, key)
        candidates = [style for style in styles if _attr(style, 'styleId') == _attr(reference, 'val')]
        if reference is None:
            candidates = [style for style in styles if _attr(style, 'type') == kind
                and _attr(style, 'default') in ('1', 'true', 'on')]
        if len(candidates) > 1 or reference is not None and not candidates:
            return False
        seen = set()
        while candidates:
            style = candidates[0]
            identity = _attr(style, 'styleId')
            if not identity or identity in seen or _attr(style, 'type') != kind:
                return False
            seen.add(identity)
            properties.append(style)
            base_node = _one(style, 'basedOn')
            base = _attr(base_node, 'val')
            candidates = [item for item in styles if _attr(item, 'styleId') == base] if base else []
            if base_node is not None and (not base or len(candidates) != 1):
                return False
    for properties_node in properties:
        if _unsupported_properties(properties_node):
            return False
    # 本轮不把未解析的隐式复杂脚本字号/粗体当作拉丁/CJK样式的同一证据。
    return not any(re.search(r'[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufeff]', text.text or '')
        for text in paragraph.iter(qn('w:t')))


def _text(paragraph):
    text = []
    allowed = {qn('w:' + key) for key in ('pPr', 'r', 'hyperlink', 'bookmarkStart', 'bookmarkEnd', 'proofErr')}
    if any(child.tag not in allowed for child in paragraph):
        raise ValueError('表格段落包含未核验对象。')
    for hyperlink in paragraph.iter(qn('w:hyperlink')):
        if any(child.tag not in allowed - {qn('w:pPr'), qn('w:hyperlink')} for child in hyperlink):
            raise ValueError('表格超链接包含未核验的包装对象。')
    for run in paragraph.iter(qn('w:r')):
        for item in run:
            if item.tag == qn('w:t'):
                text.append(item.text or '')
            elif item.tag == qn('w:br') and _attr(item, 'type', 'textWrapping') == 'textWrapping':
                text.append('\n')
            elif item.tag == qn('w:tab'):
                text.append('\t')
            elif item.tag != qn('w:rPr'):
                raise ValueError('表格文字包含字段或非静态内容。')
    return ''.join(text)


def _font_values(run):
    properties = _one(run, 'rPr')
    fonts = _one(properties, 'rFonts')
    # 所有脚本均需直接确定；主题/复杂脚本切换不由普通文字抽样推断。
    if (fonts is not None and any(key.rsplit('}', 1)[-1].endswith('Theme') for key in fonts.attrib)
        or _attr(fonts, 'hint', 'default') != 'default'
        or any(_one(properties, key) is not None for key in ('cs', 'rtl', 'szCs', 'bCs'))):
        raise ValueError('表格字体包含未解析的主题或复杂脚本覆盖。')
    color = _one(properties, 'color')
    if color is not None and any(_attr(color, key) is not None for key in ('themeColor', 'themeTint', 'themeShade')):
        raise ValueError('表格文字含主题色覆盖。')
    size = _attr(_one(properties, 'sz'), 'val')
    return {'font': [_attr(fonts, key) for key in ('ascii', 'hAnsi', 'eastAsia', 'cs')],
        'size': float(size) / 2 if size is not None else None,
        'color': '#' + _attr(color, 'val', '').upper(),
        'bold': _on(_one(properties, 'b')) if _one(properties, 'b') is not None else None}


def _paragraph_values(paragraph):
    properties = _one(paragraph, 'pPr')
    spacing, indent = _one(properties, 'spacing'), _one(properties, 'ind')
    if (any(_attr(spacing, key) is not None for key in
        ('beforeLines', 'afterLines', 'beforeAutospacing', 'afterAutospacing'))
        or any(_attr(indent, key) is not None for key in ('hanging', 'firstLineChars', 'hangingChars'))
        or _attr(spacing, 'lineRule', 'auto') != 'auto'):
        raise ValueError('表格段落含未核验的行距、自动间距或字符缩进。')
    def scaled(node, key, divisor):
        value = _attr(node, key)
        return float(value) / divisor if value is not None else None
    return {'lineHeight': scaled(spacing, 'line', 240), 'spaceBefore': scaled(spacing, 'before', 20),
        'spaceAfter': scaled(spacing, 'after', 20), 'indent': scaled(indent, 'firstLine', 20)}


def read_word_tables(document, prefs, frozen, check):
    """逐表、逐行、逐格及全部 XML run 回读，保留数字原文而非格式化后猜测。"""
    try:
        expected, source_tables, source_cells = _source_tables(frozen)
    except (ValueError, KeyError, TypeError) as error:
        return {'status': 'unverified', 'issues': [{'code': 'word_table_source_unverified', 'message': str(error)}]}
    native = list(document.element.body.iter(qn('w:tbl')))
    if not expected and not native:
        return {'status': 'not_exercised', 'sourceTables': 0, 'nativeTables': 0}
    counts = {'sourceStatus': 'verified', 'sourceTables': source_tables, 'sourceCells': source_cells,
        'expectedTables': len(expected), 'nativeTables': len(native), 'checkedTables': 0,
        'expectedCells': sum(len(row) for grid in expected for row in grid),
        'nativeCells': sum(len(table.findall('./' + qn('w:tr') + '/' + qn('w:tc'))) for table in native),
        'checkedNativeCells': 0, 'rows': 0, 'paragraphs': 0, 'runs': 0}
    actual = {'tables.' + key: [] for key in TABLE_FIELDS}
    actual.update({'typography.table.' + key: [] for key in TEXT_FIELDS})
    wanted = {key: [] for key in actual}
    grids, issues = [], []
    protected = any(_attr(item, 'enforcement') not in _FALSE
        for item in document.settings.element.findall(qn('w:documentProtection')))
    if protected:
        issues.append('文档保护使原生表格可维护性未通过。')
    try:
        for table in native:
            if (table.getparent() is not document.element.body or not _table_style_safe(document, table)
                or any(child.tag not in {qn('w:tblPr'), qn('w:tblGrid'), qn('w:tr')} for child in table)
                or any(item.tag in _UNPROVEN or item.tag in {qn('w:tcBorders'), qn('w:tblPrEx'),
                    qn('w:gridSpan'), qn('w:vMerge'), qn('w:hMerge'), qn('w:fldSimple'), qn('w:fldChar'),
                    qn('w:instrText'), qn('w:gridBefore'), qn('w:gridAfter'), qn('w:hidden')} for item in table.iter())):
                raise ValueError('表格结构、样式或覆盖属性未通过。')
            rows = table.findall(qn('w:tr'))
            columns = _one(table, 'tblGrid')
            if columns is None or not rows:
                raise ValueError('原生表格没有完整网格。')
            properties = _one(table, 'tblPr')
            if _one(properties, 'shd') is not None:
                raise ValueError('表格包含未解析的整表底纹覆盖。')
            borders = _one(properties, 'tblBorders')
            if borders is None or len(borders) != 6 or {item.tag for item in borders} != {qn('w:' + edge) for edge in _EDGES}:
                raise ValueError('表格边框未完整定义。')
            if any(_attr(edge, key) is not None for edge in borders for key in ('themeColor', 'themeTint', 'themeShade')):
                raise ValueError('表格边框含未解析的主题覆盖。')
            actual['tables.borders'].append([[_attr(_one(borders, edge), key) for key in ('val', 'sz', 'color')]
                for edge in _EDGES])
            wanted['tables.borders'].append([['nil' if prefs['tables']['borders'] == 'none' or
                prefs['tables']['borders'] == 'light' and edge in ('left', 'right', 'insideV') else 'single',
                '4', 'C7D7E5'] for edge in _EDGES])
            grid = []
            for index, row in enumerate(rows):
                counts['rows'] += 1
                properties = _one(row, 'trPr')
                actual['tables.repeatHeader'].append(_on(_one(properties, 'tblHeader')))
                wanted['tables.repeatHeader'].append(index == 0 and prefs['tables']['repeatHeader'])
                actual['tables.splitRows'].append(not _on(_one(properties, 'cantSplit')))
                wanted['tables.splitRows'].append(prefs['tables']['splitRows'])
                cells = row.findall(qn('w:tc'))
                if len(cells) != len(columns) or len(row) != len(cells) + (properties is not None):
                    raise ValueError('原生行与网格不一致或含包装对象。')
                values = []
                for cell in cells:
                    cell_properties = _one(cell, 'tcPr')
                    shade = _one(cell_properties, 'shd')
                    if shade is not None and any(_attr(shade, key) is not None for key in
                        ('themeFill', 'themeFillTint', 'themeFillShade', 'themeColor', 'themeTint', 'themeShade')):
                        raise ValueError('表格底纹含未解析的主题覆盖。')
                    actual['tables.striped'].append([_attr(shade, 'fill'), _attr(shade, 'val', 'clear')])
                    wanted['tables.striped'].append(['EDF5FC' if index == 0 else
                        'F9FAFB' if prefs['tables']['striped'] and index % 2 == 0 else None, 'clear'])
                    paragraphs = cell.findall(qn('w:p'))
                    if not paragraphs or len(cell) != len(paragraphs) + (cell_properties is not None):
                        raise ValueError('单元格含嵌套表或未核验对象。')
                    values.append('\n'.join(_text(paragraph) for paragraph in paragraphs))
                    for paragraph in paragraphs:
                        if not _text_style_safe(document, paragraph):
                            raise ValueError('表格含隐藏、修订或无法解析的文字样式。')
                        for key, value in _paragraph_values(paragraph).items():
                            actual['typography.table.' + key].append(value)
                            wanted['typography.table.' + key].append(prefs['typography']['table'][key])
                        runs = list(paragraph.iter(qn('w:r')))
                        if not runs:
                            raise ValueError('空段落未保存可维护的字体属性。')
                        for run in runs:
                            for key, value in _font_values(run).items():
                                actual['typography.table.' + key].append(value)
                                wanted['typography.table.' + key].append([_FONTS[prefs['typography']['table']['font']]] * 4
                                    if key == 'font' else prefs['typography']['table'][key].upper()
                                    if key == 'color' else prefs['typography']['table'][key])
                        counts['paragraphs'] += 1
                        counts['runs'] += len(runs)
                    counts['checkedNativeCells'] += 1
                grid.append(values)
            grids.append(grid)
            counts['checkedTables'] += 1
    except (ValueError, TypeError, KeyError) as error:
        issues.append(str(error))
    valid = (not issues and grids == expected and len(native) == len(expected)
        and counts['checkedTables'] == len(native) and counts['checkedNativeCells'] == counts['expectedCells'])
    check('tables.nativeStructure', [not issues, grids], [True, expected], coverage='complete',
        evidence_kind=WORD_TABLE_FIELD_EVIDENCE, evidence_objects=dict(counts),
        message='全部原生网格、来源原文和可见静态文字逐对象核验。' + '；'.join(issues))
    for path in actual:
        check(path, actual[path], wanted[path], coverage='complete', evidence_kind=WORD_TABLE_FIELD_EVIDENCE,
            evidence_objects=dict(counts), message='全部原生表格对象的维护属性逐项回读。')
    valid = valid and all(actual[key] == wanted[key] for key in actual)
    return {'status': 'passed' if valid else 'failed', **counts, 'issues': issues}
