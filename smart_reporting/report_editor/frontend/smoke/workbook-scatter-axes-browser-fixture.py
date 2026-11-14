"""Scatter 双数值轴真实浏览器夹具，以及独立 ZIP 回读校验。"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook
from openpyxl.chart import Reference, ScatterChart, Series
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor

C = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
NS = {'c': C, 'a': A}
ET.register_namespace('c', C)
ET.register_namespace('a', A)


def node(parent, tag, value=None):
    return ET.SubElement(parent, f'{{{C}}}{tag}', {} if value is None else {'val': str(value)})


def title(parent, text):
    t = node(parent, 'title')
    rich = node(node(t, 'tx'), 'rich')
    ET.SubElement(rich, f'{{{A}}}bodyPr')
    ET.SubElement(rich, f'{{{A}}}lstStyle')
    p = ET.SubElement(rich, f'{{{A}}}p')
    r = ET.SubElement(p, f'{{{A}}}r')
    ET.SubElement(r, f'{{{A}}}t').text = text
    return t


def parts(path):
    with ZipFile(path) as z:
        return {name: z.read(name) for name in z.namelist()}


def create(path):
    book = Workbook()
    sheet = book.active
    sheet.title = 'Scatter axes'
    sheet.append(['Elapsed', 'Sales', 'Hidden X', 'Hidden Y'])
    for x, y in [(0, 0), (1000, 5000), (2000, 10000)]:
        sheet.append([x, y, x, y])
    for index, name in enumerate(['Axes standard', 'Axes hidden'], 1):
        chart = ScatterChart()
        chart.title = name
        chart.scatterStyle = 'lineMarker'
        chart.legend = None
        chart.series.append(Series(Reference(sheet, min_col=index * 2, min_row=2, max_row=4),
                                   xvalues=Reference(sheet, min_col=index * 2 - 1, min_row=2, max_row=4)))
        col = 1 + (index - 1) * 10
        chart.anchor = TwoCellAnchor(_from=AnchorMarker(col=col, row=2), to=AnchorMarker(col=col + 9, row=19))
        sheet.add_chart(chart)
    book.save(path)
    package = parts(path)
    for index in (1, 2):
        name = f'xl/charts/chart{index}.xml'
        root = ET.fromstring(package[name])
        plot = root.find('.//c:plotArea', NS)
        scatter = plot.find('c:scatterChart', NS)
        x_id, y_id = ((101, 202) if index == 1 else (303, 404))
        for old in list(plot.findall('c:valAx', NS)):
            plot.remove(old)
        for old in list(scatter.findall('c:axId', NS)):
            scatter.remove(old)
        labels = node(scatter, 'dLbls')
        node(labels, 'showVal', 1)
        node(scatter, 'axId', x_id)
        node(scatter, 'axId', y_id)
        series = scatter.find('c:ser', NS)
        symbol = series.find('c:marker/c:symbol', NS)
        if symbol is None:
            marker = series.find('c:marker', NS)
            symbol = node(marker if marker is not None else node(series, 'marker'), 'symbol')
        symbol.set('val', 'none')
        sp = series.find('c:spPr', NS)
        if sp is None:
            sp = node(series, 'spPr')
        for child in list(sp):
            sp.remove(child)
        ln = ET.SubElement(sp, f'{{{A}}}ln')
        fill = ET.SubElement(ln, f'{{{A}}}solidFill')
        ET.SubElement(fill, f'{{{A}}}srgbClr', {'val': '1B7F5A'})
        for kind, values, fmt in [('xVal', [0, 1000, 2000], '0.0'), ('yVal', [0, 5000, 10000], '0.000' if index == 1 else '0.0')]:
            ref = series.find(f'c:{kind}/c:numRef', NS)
            old = ref.find('c:numCache', NS)
            if old is not None:
                ref.remove(old)
            cache = node(ref, 'numCache')
            node(cache, 'formatCode').text = fmt
            node(cache, 'ptCount', 3)
            for i, value in enumerate(values):
                node(ET.SubElement(cache, f'{{{C}}}pt', {'idx': str(i)}), 'v').text = str(value)
        for is_x, axis_id, cross_id in [(False, y_id, x_id), (True, x_id, y_id)]:
            axis = node(plot, 'valAx')  # 故意先写 Y，再写 X，禁止依赖 XML 子节点顺序。
            node(axis, 'axId', axis_id)
            scaling = node(axis, 'scaling')
            node(scaling, 'orientation', 'minMax' if index == 1 else 'maxMin')
            node(scaling, 'max', 2000 if is_x else 10000)
            node(scaling, 'min', 0)
            node(axis, 'delete', 0 if index == 1 else 1)
            node(axis, 'axPos', ('b' if is_x else 'l') if index == 1 else ('t' if is_x else 'r'))
            if (index == 1 and is_x) or (index == 2 and not is_x):
                node(axis, 'majorGridlines')
            title(axis, ('Elapsed' if is_x else 'Sales') if index == 1 else ('Hidden X' if is_x else 'Hidden Y'))
            ET.SubElement(axis, f'{{{C}}}numFmt', {'formatCode': ('0.0' if is_x else '0.00') if index == 1 else ('0.000' if is_x else '0.0%'), 'sourceLinked': '0'})
            node(axis, 'crossAx', cross_id)
            node(axis, 'crosses', 'autoZero')
            node(axis, 'majorUnit', 1000 if is_x else 5000)
            units = node(axis, 'dispUnits')
            node(units, 'builtInUnit', 'thousands' if index == 1 else ('hundreds' if is_x else 'millions'))
            unit_label = node(units, 'dispUnitsLbl')
            if index == 1 and is_x:
                rich = node(node(unit_label, 'tx'), 'rich')
                ET.SubElement(rich, f'{{{A}}}bodyPr')
                ET.SubElement(rich, f'{{{A}}}lstStyle')
                p = ET.SubElement(rich, f'{{{A}}}p')
                ET.SubElement(ET.SubElement(p, f'{{{A}}}r'), f'{{{A}}}t').text = 'X ONLY UNITS'
        package[name] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    with ZipFile(path, 'w', ZIP_DEFLATED) as z:
        for name, data in package.items():
            z.writestr(name, data)


def verify(source, saved):
    before, after = parts(source), parts(saved)
    assert before.keys() == after.keys()
    changed = [name for name in before if before[name] != after[name]]
    assert changed == ['xl/charts/chart1.xml'], changed
    roots = [ET.fromstring(package['xl/charts/chart1.xml']) for package in (before, after)]
    axis_rows = []
    for root in roots:
        axes = {int(ax.find('c:axId', NS).get('val')): ax for ax in root.findall('.//c:valAx', NS)}
        assert list(axes) == [202, 101]
        axis_rows.append(axes)
    text = lambda parent: ''.join(parent.itertext())
    assert text(roots[1].find('.//c:chart/c:title', NS)) == 'Axes standard draft'
    assert text(axis_rows[1][101].find('c:title', NS)) == 'Elapsed edited'
    assert text(axis_rows[1][202].find('c:title', NS)) == 'Sales edited'
    y = axis_rows[1][202]
    assert y.find('c:scaling/c:min', NS).get('val') == '-5000'
    assert y.find('c:scaling/c:max', NS).get('val') == '15000'
    assert y.find('c:majorGridlines', NS) is not None
    # 只剔除明确请求修改的字段，余下标题/轴范围/网格/单位/系列必须逐元素相等。
    cleaned = [deepcopy(root) for root in roots]
    for root in cleaned:
        chart = root.find('.//c:chart', NS)
        chart.remove(chart.find('c:title', NS))
        for axis in root.findall('.//c:valAx', NS):
            axis.remove(axis.find('c:title', NS))
            if axis.find('c:axId', NS).get('val') == '202':
                for tag in ['majorGridlines']:
                    for child in list(axis.findall(f'c:{tag}', NS)):
                        axis.remove(child)
                scaling = axis.find('c:scaling', NS)
                for tag in ['min', 'max']:
                    for child in list(scaling.findall(f'c:{tag}', NS)):
                        scaling.remove(child)
    def semantic(element):
        return (element.tag, sorted(element.attrib.items()), (element.text or '').strip(), [semantic(child) for child in element])
    assert semantic(cleaned[0]) == semantic(cleaned[1]), '请求范围外的图表/轴/单位/系列发生变化'
    return {'ok': True, 'changedParts': changed, 'unchangedParts': len(before) - 1,
            'axisXmlOrder': [202, 101], 'xAxisOnlyExplicitTitleChanged': True,
            'unitAndNonTargetAxisStatePreserved': True, 'hiddenChartByteIdentical': True}


if __name__ == '__main__':
    if sys.argv[1] == '--verify':
        result = verify(Path(sys.argv[2]), Path(sys.argv[3]))
        Path(sys.argv[4]).write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False))
    else:
        create(Path(sys.argv[1]))
