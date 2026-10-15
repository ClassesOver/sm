"""按补证表的分组、指标和单位复核正文；范围有歧义时不猜测。"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from .numeric_text import _unit_scales
from .review_common import _VALUE


def _tables(documents):
    for document in documents:
        pending = [document] if document.get('schema') == 'chart-input/v1' else list(document.get('findings', ()))
        while pending:
            item = pending.pop()
            if isinstance(item, list):
                pending.extend(item)
            elif isinstance(item, dict):
                columns, rows, metadata = (item.get(key) for key in ('columns', 'rows', 'columnMeta'))
                if isinstance(columns, list) and isinstance(rows, list) and isinstance(metadata, dict):
                    rows = [row for row in rows if isinstance(row, list) and len(row) == len(columns)]
                    yield columns, rows, metadata
                else:
                    pending.extend(value for value in item.values() if isinstance(value, (dict, list)))


def _converted(value, unit, target):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = Decimal(str(value))
    if not value.is_finite():
        return None
    if unit == target:
        return value
    scales = _unit_scales(unit)
    return value * scales[unit] / scales[target] if scales and target in scales else None


def supplemental_attribution_warnings(text, documents, field_definitions):
    # 补证表未携带分析身份时，不能在多分析装配稿中跨章节借用同名组。
    # 此检查用于生成阶段已按章节选择的证据；完整报告由既有带身份引用校验负责。
    if '[[analysis:' in text:
        return []
    tables = list(_tables(documents))
    warnings = []
    # 保留千分位逗号；一个句子可以并列多个组，每个数字只归属于其前方最近的组名。
    candidates = {}
    for columns, rows, metadata in tables:
        dimensions = [i for i in range(len(columns)) if rows and all(isinstance(row[i], str) for row in rows)]
        if len(dimensions) != 1:
            continue
        dimension = dimensions[0]
        names = [row[dimension] for row in rows]
        for row in rows:
            name = row[dimension]
            if name in {'合计', '总计', '全部', '总额', '全院'} or len(name) < 2 or not re.search(r'[\u3400-\u9fff]', name) or names.count(name) != 1:
                continue
            candidates.setdefault(name, []).append((columns, metadata, row))
    if not candidates:
        return []
    pattern = '|'.join(re.escape(name) for name in sorted(candidates, key=len, reverse=True))
    for clause in re.split(r'[。！？；;\n]', text):
        if (re.search(r'(?<![\d—至到~～-])\d{1,2}月(?![—至到~～-])|\d{4}-\d{2}-\d{2}', clause)
                or re.search(r'交叉|下钻|单笔|明细组|极值行', clause)):
            continue
        groups = list(re.finditer(pattern, clause))
        for position, group in enumerate(groups):
            end = groups[position + 1].start() if position + 1 < len(groups) else len(clause)
            local = clause[group.end():end]
            # 只核对紧随组名的直接陈述，不能跨逗号把后续指标或局部期间借给该组。
            for match in list(_VALUE.finditer(local))[:1]:
                if not re.fullmatch(r'[\s|（(]*(?:(?:为|是|约|约为|金额|成本|收入|合计|累计|为最高|最高)|[：:，,])*[\s]*', local[:match.start()]):
                    continue
                if match[2] == '%':
                    continue  # 占比分母与维度需要单独声明，不能从金额列推断。
                expected = set()
                for columns, metadata, row in candidates[group[0]]:
                    values = []
                    for i, column in enumerate(columns):
                        unit = metadata.get(column, {}).get('unit')
                        value = _converted(row[i], unit, match[2])
                        if value is not None:
                            label = field_definitions.get(column, column)
                            values.append((label, value))
                    # 多个同量纲指标时必须有明确指标名；单指标表可直接使用组名。
                    named = [value for label, value in values if label and label in clause]
                    selected = named if named else [value for _, value in values] if len(values) == 1 else []
                    expected.update(selected)
                if len(expected) != 1:
                    continue
                written = Decimal(match[1].replace(',', ''))
                value = next(iter(expected)).quantize(Decimal(1).scaleb(written.as_tuple().exponent), rounding=ROUND_HALF_UP)
                if value != written:
                    warnings.append(f'补证分组数值需复核：{group[0]}写为{match[0]}，同分组登记汇总为{value}{match[2]}。'
                                    '不能把多维明细或单行值当作该分组累计；若期间不同须明确范围并补充对应证据。')
    # 分号常用于同一预算断言下的并列项，保留其共同的断言上下文。
    for paragraph in re.split(r'[。！？\n]', text):
        zero_claim = re.search(r'(?:全部|均|皆)[^。；]{0,20}预算(?:侧|支出|金额)?(?:为|是|等于)\s*0', paragraph)
        difference_claim = re.search(r'正向(?:超支|偏差)|占总体差额', paragraph)
        if not zero_claim and not difference_claim:
            continue
        for columns, rows, metadata in tables:
            budgets = [i for i, column in enumerate(columns) if re.search(r'budget|预算', column, re.I)
                       and metadata.get(column, {}).get('unit') in {'元', '万元', '亿元'}]
            if len(budgets) != 1:
                continue
            for row in rows:
                names = [value for value in row if isinstance(value, str) and len(value) >= 2 and value in paragraph]
                if len(names) != 1:
                    continue
                name = names[0]
                budget = _converted(row[budgets[0]], metadata[columns[budgets[0]]]['unit'], '元')
                if zero_claim and budget is not None and budget != 0:
                    warnings.append(f'零预算断言需复核：{name}的登记预算为{budget}元，并非0；不能归入无预算基准类别。')
                differences = [i for i, column in enumerate(columns) if column in {'difference', '差额'}]
                match = re.search(re.escape(name) + r'\s*(' + _VALUE.pattern + ')', paragraph)
                if difference_claim and len(differences) == 1 and match:
                    amount = _VALUE.search(match[0])
                    unit = metadata.get(columns[differences[0]], {}).get('unit')
                    delta = _converted(row[differences[0]], unit, amount[2])
                    written = Decimal(amount[1].replace(',', ''))
                    if delta is not None and delta.quantize(Decimal(1).scaleb(written.as_tuple().exponent), rounding=ROUND_HALF_UP) != written:
                        warnings.append(f'偏差金额需复核：{name}的登记差额为{delta}{amount[2]}，不能用实际金额{amount[0]}表示超支或差额贡献。')
    return list(dict.fromkeys(warnings))
