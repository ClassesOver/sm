"""已解析偏好映射到现有工作簿引擎，不改写业务值或公式。"""
import subprocess
from copy import deepcopy
from datetime import date
from string import Formatter

FONTS = {"sans": "Noto Sans CJK SC", "serif": "Noto Serif CJK SC"}


def _signature_layout(rows, signature, page):
    """按真实字体测量独立说明页，超长单元格缩字以保留完整内容。"""
    from PIL import ImageFont

    face = FONTS[signature['font']] + (':style=Bold' if signature['bold'] else '')
    path = subprocess.run(['fc-match', '-f', '%{file}', face], capture_output=True, text=True, check=True).stdout
    heights, sizes = [], []
    # Excel 60字符列宽约425像素；扣除单元格内边距并转换为磅。
    width = 310
    dimensions = {'A4': (210, 297), 'A3': (297, 420), 'Letter': (215.9, 279.4)}[page['paper']]
    height_mm = dimensions[0] if page['orientation'] == 'landscape' else dimensions[1]
    available = max(80, (height_mm - page['margins']['top'] - page['margins']['bottom']) * 72 / 25.4 - 70)
    for index, row in enumerate(rows):
        size = signature['size'] if index else 11
        while True:
            font = ImageFont.truetype(path, round(size * 4))
            lines, remaining = 0, row[0]
            while remaining:
                low, high, count = 1, len(remaining), 1
                while low <= high:
                    middle = (low + high) // 2
                    if font.getlength(remaining[:middle]) / 4 <= width:
                        count, low = middle, middle + 1
                    else:
                        high = middle - 1
                lines += 1
                remaining = remaining[count:]
            height = max(1, lines) * size * 1.4 + 10
            limit = min(380, (available - 30) / 2 if index in (1, 2) else available - 30)
            if height <= limit or size <= 6:
                break
            size = max(6, size - .5)
        heights.append(min(409, height))
        sizes.append(size)
    # 署名和日期是一组身份信息，缩字时保持相同字号。
    identity_size = min(sizes[1:3])
    for index in (1, 2):
        heights[index] = (heights[index] - 10) * identity_size / sizes[index] + 10
        sizes[index] = identity_size
    return heights, sizes


def displayed_date(value: str, format: str) -> str:
    parsed = date.fromisoformat(value)
    return f"{parsed.year}年{parsed.month}月{parsed.day}日" if format == "chinese" else parsed.strftime("%Y/%m/%d") if format == "slash" else parsed.isoformat()


def prepare_workbook(sheets, preferences, *, title, period, generated_date, filename):
    result = deepcopy(list(sheets))
    from openpyxl.utils.datetime import to_excel

    date_pattern = {'iso': 'yyyy-mm-dd', 'slash': 'yyyy/mm/dd', 'chinese': 'yyyy"年"m"月"d"日"'}[preferences['numbers']['dateFormat']]
    for sheet in result:
        for row in sheet['rows']:
            for cell in row:
                if not isinstance(cell, dict) or cell.get('valueType') != 'date':
                    continue
                try:
                    parsed = date.fromisoformat(cell['value'])
                    if parsed.year < 1900:
                        continue
                    cell['value'] = to_excel(parsed)
                    cell['style'] = {'numberFormat': date_pattern, **cell.get('style', {})}
                except (ValueError, TypeError):
                    # 无法核验的日期保留源值，不能靠宽松解析猜测。
                    continue
    occupied = {sheet["name"].casefold() for sheet in result}
    name, index = "说明", 2
    while name.casefold() in occupied:
        name, index = f"说明{index}", index + 1
    signature = preferences["signature"]
    result.append({"name": name, "headerRow": 0, "signatureSheet": True,
        "rows": [["报告落款"], [preferences["common"]["signer"]],
            [displayed_date(generated_date, preferences["common"]["dateFormat"])],
            *[[line] for line in signature["description"].splitlines()]]})
    heights, sizes = _signature_layout(result[-1]['rows'], signature, preferences['print']['page'])
    result[-1]['signatureRowHeights'] = heights
    result[-1]['signatureFontSizes'] = sizes
    layout_issues = ([{'code': 'workbook_signature_font_reduced',
        'message': '落款内容过长，说明页字号已自动缩小以保留完整文字；原始内容和业务表样式不变。'}]
        if any(size < signature['size'] for size in sizes[1:]) else [])
    numbers = preferences["numbers"]
    positive = ("#,##0" if numbers["thousandsSeparator"] else "0") + ("." + "0" * numbers["decimalPlaces"] if numbers["decimalPlaces"] else "")
    negative = "(" + positive + ")" if numbers["negativeStyle"] == "parentheses" else ("[Red]-" if numbers["negativeStyle"] == "red" else "-") + positive
    percent = '0' + ('.' + '0' * numbers['percentPlaces'] if numbers['percentPlaces'] else '') + '"%"'
    percent_negative = '(' + percent + ')' if numbers['negativeStyle'] == 'parentheses' else (
        '[Red]-' if numbers['negativeStyle'] == 'red' else '-') + percent
    values = {"title": title, "signer": preferences["common"]["signer"], "period": period,
        "date": displayed_date(generated_date, preferences["common"]["dateFormat"]), "filename": filename}
    header_footer = preferences["print"]["headerFooter"]
    print_style = header_footer['style']
    print_size = round(print_style['size'])
    font_prefix = (f'&"{FONTS[print_style["font"]]},{"Bold" if print_style["bold"] else "Regular"}"'
        f'&{print_size}&K{print_style["color"][1:].upper()}')
    if header_footer['enabled'] and print_size != print_style['size'] and any(
        header_footer[kind][side] for kind in ('header', 'footer') for side in ('left', 'center', 'right')
    ):
        layout_issues.append({'code': 'workbook_header_footer_font_rounded',
            'message': f'电子表格打印页眉页脚使用整磅字号，本次按 {print_size} 磅输出；冻结偏好保留原值。'})
    if header_footer['enabled']:
        for kind, margin, label in [('header', 'top', '页眉'), ('footer', 'bottom', '页脚')]:
            lines = max((value.count('\n') + 1 for value in header_footer[kind].values() if value), default=0)
            band = (preferences['print']['page']['margins'][margin] - header_footer[kind + 'Distance']) * 72 / 25.4
            # 仅作保守高度风险提示，不将估算冒充真实分页验收，也不改写冻结配置。
            if lines and print_size * 1.5 * lines > band:
                layout_issues.append({'code': 'workbook_header_footer_band_overflow',
                    'message': f'打印{label}字号/行数可能超出页边距内的可用打印带，存在遮挡或裁切风险；请调整字号或页边距并检查实际打印预览。'})

    def field(value):
        parts = []
        for literal, name, _, _ in Formatter().parse(value):
            parts.append(literal.replace("&", "&&"))
            if name:
                parts.append({"page": "&P", "pages": "&N"}.get(name, values.get(name, "").replace("&", "&&")))
        text = "".join(parts)
        return font_prefix + text if text else ''

    return result, {**deepcopy(preferences), 'layoutIssues': layout_issues, "fontNames": FONTS, "numberFormat": positive + ";" + negative,
        'percentPointsFormat': percent + ';' + percent_negative,
        "print": {**preferences["print"], "header": {side: field(value) for side, value in header_footer["header"].items()} if header_footer["enabled"] else None,
            "footer": {side: field(value) for side, value in header_footer["footer"].items()} if header_footer["enabled"] else None}}
