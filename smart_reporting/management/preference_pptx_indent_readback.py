"""复用原生对象和来源绑定，独立核验全部段落的 DrawingML 首行缩进。"""

import re
from collections import Counter

from ..preferences.workbook_adapter import displayed_date

PPTX_INDENT_FIELD_EVIDENCE = 'pptx_native_indent_fields_v1'
_ROLES = ('h1', 'body', 'table', 'caption', 'signature', 'footer')


def _matches_chunks(chunks, expected):
    """允许一个来源段被分页拆开，但不允许合段、换序或遗漏末段。"""
    cursor = 0
    for value in expected:
        combined = ''
        first = True
        while cursor < len(chunks) and (first or combined != value):
            combined += chunks[cursor]
            cursor += 1
            first = False
            if not value.startswith(combined):
                return False
        if first or combined != value:
            return False
    return cursor == len(chunks)


def _guard(checks, paths):
    return all(any(item.get('path') == path for item in checks) and all(
        item.get('passed') is True and item.get('coverage') == 'complete'
        for item in checks if item.get('path') == path) for path in paths)


def read_pptx_indents(deck, prefs, frozen, check, existing_checks):
    """仅完整绑定且可见的角色取得 complete；空角色不产生空集通过。"""
    context = frozen['state']['_documentContext']
    groups = {role: [] for role in _ROLES}
    valid = dict.fromkeys(_ROLES, True)
    body, captions = [], {}
    source_titles = [source['title'] for source in frozen['slides']]
    titles = [context['title'], *source_titles, '报告落款', '报告落款（附加说明续页）']
    table_number = 0
    chart_number = 0
    required_titles = []
    for source in frozen['slides']:
        for table in source.get('tables', []):
            table_number += 1
            titles.append((f'表 {table_number} ' if prefs['tables']['captionNumbering'] else '')
                + (table['caption'] or source['title']))
        if source.get('chartPath'):
            chart_number += 1
            prefix = f'图 {chart_number} ' if prefs['charts']['captionNumbering'] else ''
            captions[chart_number] = {'prefix': prefix, 'value': source['title'], 'chunks': []}
            titles.extend([prefix + '图表分析', prefix + '图注'])
            required_titles.append((source['title'], prefix + '图表分析'))
        else:
            required_titles.append((source['title'],))
    heading_pattern = re.compile('(?:' + '|'.join(re.escape(value) for value in titles) + r')(?:（续 \d+）)?\Z')
    values = {'title': context['title'], 'period': context['periodLabel'],
        'signer': prefs['common']['signer'], 'date': displayed_date(context['generatedDate'],
            prefs['common']['dateFormat']), 'filename': 'report.pptx', 'slides': str(len(deck.slides))}

    def add(role, slide, shape, paragraphs):
        visible = (slide._element.get('show', '1') not in {'0', 'false'}
            and not shape._element.xpath('.//p:cNvPr[@hidden="1" or @hidden="true"]'))
        bounds = (shape.left >= 0 and shape.top >= 0 and shape.width > 0 and shape.height > 0
            and shape.left + shape.width <= deck.slide_width + 100
            and shape.top + shape.height <= deck.slide_height + 100)
        valid[role] = valid[role] and visible and bounds
        groups[role].append(list(paragraphs))

    actual_titles = Counter()
    for page, slide in enumerate(deck.slides):
        # 分组对象没有既有独立源绑定；不能把未枚举的内部文字当作完整覆盖。
        if any(shape.shape_type == 6 for shape in slide.shapes):
            valid = dict.fromkeys(_ROLES, False)
        text_shapes = [shape for shape in slide.shapes if shape.has_text_frame
            and (shape.shape_type == 17 or shape.text)]
        values['slide'] = str(page + 1)
        expected_footers = ([] if page == 0 and prefs['hideTitleSlideFooter'] else
            [template.format(**values) for template in prefs['footer'].values() if template])
        footers = [shape for shape in text_shapes if shape.text in expected_footers
            and shape.top > deck.slide_height / 2 and shape.width < deck.slide_width / 2]
        valid['footer'] = valid['footer'] and sorted(shape.text for shape in footers) == sorted(expected_footers)
        for shape in footers:
            add('footer', slide, shape, shape.text_frame.paragraphs)
        rest = [shape for shape in text_shapes if shape not in footers]
        heading = min(rest, key=lambda shape: shape.top) if rest else None
        heading_valid = (heading is not None and heading_pattern.fullmatch(heading.text) is not None
            and (page > 0 or heading.text == context['title']))
        valid['h1'] = valid['h1'] and heading_valid
        if heading is None:
            valid['body'] = valid['caption'] = valid['signature'] = False
            continue
        add('h1', slide, heading, heading.text_frame.paragraphs)
        signature = heading.text in {'报告落款', '报告落款（附加说明续页）'}
        if page and not signature:
            actual_titles[heading.text] += 1
        for shape in rest:
            if shape == heading:
                continue
            matches = [number for number, caption in captions.items() if
                (caption['prefix'] and shape.text.startswith(caption['prefix'])) or
                (not caption['prefix'] and caption['value'].startswith(shape.text) and shape.text)]
            if signature:
                role = 'signature'
            elif page and len(matches) == 1:
                role = 'caption'
                caption = captions[matches[0]]
                value = shape.text[len(caption['prefix']):]
                if ('图注（续 ' in heading.text or not caption['chunks'] or caption['chunks'][-1] != value):
                    caption['chunks'].append(value)
            else:
                role = 'body'
                body.append(shape.text)
                if matches:
                    valid['caption'] = False
            add(role, slide, shape, shape.text_frame.paragraphs)
        for shape in slide.shapes:
            if shape.has_table:
                add('table', slide, shape, [paragraph for row in shape.table.rows for cell in row.cells
                    for paragraph in cell.text_frame.paragraphs])

    expected_body = [context['periodLabel'], '管理分析报告',
        *[bullet for source in frozen['slides'] for bullet in source.get('bullets', [])]]
    valid['body'] = valid['body'] and _matches_chunks(body, expected_body)
    # 空正文源页同样必须存在；仅枚举剩余页面不能证明冻结标题的完整覆盖。
    for alternatives in required_titles:
        found = next((value for value in alternatives if actual_titles[value]), None)
        valid['h1'] = valid['h1'] and found is not None
        if found is not None:
            actual_titles[found] -= 1
    for caption in captions.values():
        # 正文续页可重复同一图注片段；独立恢复完整来源文字，不相信消费者回执。
        valid['caption'] = valid['caption'] and ''.join(caption['chunks']) == caption['value']
    valid['table'] = valid['table'] and _guard(existing_checks, ['pptx.tables.' + key for key in
        ('content', 'visibility', 'structure', 'bounds', 'nativeRuns', 'objectCoverage')])
    valid['signature'] = valid['signature'] and _guard(existing_checks,
        ['pptx.common.signer', 'pptx.common.dateFormat', 'pptx.signature.description'])
    for role in _ROLES:
        declared = {'table': bool(table_number), 'caption': bool(captions),
            'footer': any(prefs['footer'].values())}.get(role, True)
        if not declared and not groups[role]:
            continue
        path = ('typography.' + role if role in prefs['typography'] else
            'footerStyle' if role == 'footer' else role) + '.indent'
        style = prefs['typography'][role] if role in prefs['typography'] else prefs[
            'footerStyle' if role == 'footer' else role]
        paragraphs = [paragraph for shape in groups[role] for paragraph in shape]
        actual = []
        for paragraph in paragraphs:
            native = paragraph._p.find('{http://schemas.openxmlformats.org/drawingml/2006/main}pPr')
            # 本批消费者显式写入0；缺属性不能绕过文本框/母版的继承值取得零值证明。
            value = native.get('indent') if native is not None else None
            if value is None:
                valid[role] = False
                continue
            try:
                actual.append(int(value))
            except ValueError:
                valid[role] = False
        complete = bool(groups[role] and paragraphs) and valid[role]
        expected = [round(style['indent'] * 12700)] * max(1, len(paragraphs))
        check(path, actual if complete else None, expected,
            '按冻结角色逐对象、逐段核验原生首行缩进EMU；不代表视觉验收。',
            coverage='complete' if complete else 'sample', evidence_kind=PPTX_INDENT_FIELD_EVIDENCE,
            evidence_objects={'nativeObjects': len(groups[role]),
                'checkedNativeObjects': len(groups[role]) if complete else 0, 'paragraphs': len(paragraphs)})
