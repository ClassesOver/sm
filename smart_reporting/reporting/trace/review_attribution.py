"""正文复核：分组排名与数值归属（科室、指标、项目比率排名）。"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ..hospital_operation.deterministic_analysis import DeterministicAnalysisBundle
from .numeric_text import (
    _frozen_number_entries,
    _operand_names,
    _unit_scales,
    budget_comparison_values,
    project_ratio_values,
    supplemental_number_values,
)
from .review_common import _CLAUSE_BREAK, _VALUE, _numeric_literals

_GROUP_HIGH_WORDS = ("最高", "最大", "最多", "居首", "排名第一", "位居第一", "位列第一")


_GROUP_LOW_WORDS = ("最低", "最小", "最少", "垫底", "排名最后", "位列末位")


def _monthly_budget_rate_warnings(text: str, documents: list[dict[str, Any]],
                                  field_definitions: Mapping[str, str] | None = None) -> list[str]:
    """明确单月的预算执行率按指标身份校验，不从其他指标的百分数借依据。"""
    labels: set[str] = set()
    candidates = []
    for document in documents:
        try:
            bundle = DeterministicAnalysisBundle.model_validate(document)
        except ValueError:
            continue
        current = {fact.fact_id: fact for fact in bundle.metrics if "current" in fact.period_roles}
        for comparison in budget_comparison_values(bundle):
            if (comparison["actualFactId"] in current and comparison["percentage"] is not None
                    and ".." not in comparison["period"]):
                fact = current[comparison["actualFactId"]]
                names = {name for name in (fact.display_name, *fact.aliases,
                         (field_definitions or {}).get(fact.field_ref),
                         (field_definitions or {}).get(fact.field)) if name}
                labels.update(names)
                candidates.append((bundle.analysis_id, comparison, names))
    if not labels:
        return []
    pattern = re.compile(
        r"(?P<label>" + "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True)) + r")"
        r"(?:预算)?(?:执行率|完成率)?\s*(?:约为|为|约|达到?|是|[：:=])?\s*"
        r"(?P<number>[+-]?\d+(?:\.\d+)?)\s*%")
    markers = list(re.finditer(r"(?:\[\[analysis:[^\]]+\]\]\s*)+", text))
    warnings = []
    for sentence in re.finditer(r"[^。！？\n]+", text):
        source = sentence[0]
        if not re.search(r"执行率|完成率", source) or re.search(r"\d月?\s*[–—~～至到-]\s*\d{1,2}月", source):
            continue
        months = list(re.finditer(r"(?<!\d)(?:(?P<year>\d{4})年)?(?P<month>\d{1,2})月", source))
        # 并列月份、累计期间、分组范围不明确时不套全院单月分母。
        if len(months) != 1:
            continue
        month = months[0]
        leading = re.sub(r"\[\[analysis:[^\]]+\]\]", "", source[:month.start()])
        if not re.fullmatch(r"\s*(?:全院)?\s*", leading):
            continue
        before = [marker for marker in markers if marker.start() < sentence.end()]
        analyses = set(re.findall(r"\[\[analysis:([^\]]+)\]\]", before[-1][0])) if before else set()
        previous_end = month.end()
        for match in pattern.finditer(source, previous_end):
            if not re.fullmatch(r"[\s，,；;]*(?:(?:全院|的|实际|同期|而|但)\s*)*", source[previous_end:match.start()]):
                break
            previous_end = match.end()
            values = {comparison["percentage"] for analysis, comparison, names in candidates
                      if (not analyses or analysis in analyses)
                      and match["label"] in names
                      and int(comparison["period"][5:7]) == int(month["month"])
                      and (not month["year"] or comparison["period"][:4] == month["year"])}
            if len(values) != 1:
                continue
            written = Decimal(match["number"])
            expected = next(iter(values)).quantize(Decimal(1).scaleb(written.as_tuple().exponent), rounding=ROUND_HALF_UP)
            if written != expected:
                warnings.append(f"预算执行率归属需复核：{month[0]}{match['label']}写为{written}%，"
                                f"同范围冻结实际值/预算值为{expected}%。")
    return list(dict.fromkeys(warnings))


def _project_ratio_value_warnings(text: str, documents: list[dict[str, Any]]) -> list[str]:
    """按分析、项目分组及指标核对比率；未点名分组时才使用同范围总额。"""
    candidates = []
    chart_group_values: dict[tuple[str | None, str, str], set[Decimal]] = {}
    ratio_fields = {"contract_rate": "contract_amount", "contract": "contract_amount",
                    "payment_rate": "payment_amount", "payment": "payment_amount"}
    for document in documents:
        if document.get("schema") != "chart-input/v1":
            continue
        columns, rows = document.get("columns"), document.get("rows")
        metadata = document.get("columnMeta")
        source = document.get("source")
        analysis_id = source.get("analysisId") if isinstance(source, dict) else None
        if isinstance(columns, list) and columns and isinstance(rows, list) and isinstance(metadata, dict):
            for row in rows:
                if not isinstance(row, list) or not row or not isinstance(row[0], str):
                    continue
                for index, column in enumerate(columns[1:], 1):
                    if (column not in ratio_fields or index >= len(row)
                            or not isinstance(row[index], (int, float)) or isinstance(row[index], bool)
                            or not isinstance(metadata.get(column), dict)
                            or metadata[column].get("unit") != "%"
                            or metadata[column].get("isPercent") is not True):
                        continue
                    value = Decimal(str(row[index]))
                    if value.is_finite():
                        key = (analysis_id, row[0], ratio_fields[column])
                        chart_group_values.setdefault(key, set()).add(value)
    for document in documents:
        try:
            bundle = DeterministicAnalysisBundle.model_validate(document)
        except ValueError:
            continue
        metrics = {fact.fact_id: fact for fact in bundle.metrics}
        for ratio in project_ratio_values(bundle):
            candidates.append((bundle.analysis_id, metrics[ratio["numeratorFactId"]], ratio["percentage"]))
    warnings = []
    # 同一标题可连续登记多个分析；以整组标记确定正文的分析范围。
    markers = list(re.finditer(r"(?:\[\[analysis:[^\]]+\]\]\s*)+", text))
    group_names = {group for _, group, _ in chart_group_values if group}
    total_names = {"全院", "全部项目", "所有项目", "项目总体"}
    group_pattern = "|".join(re.escape(group) for group in sorted(group_names | total_names, key=len, reverse=True))
    # 分号连接的后半句可沿用主语；全院等显式主语会覆盖此前的项目组。
    for sentence in re.finditer(r"[^。！？\n]+", text):
        before = [marker for marker in markers if marker.start() < sentence.end()]
        analyses = set(re.findall(r"\[\[analysis:([^\]]+)\]\]", before[-1][0])) if before else set()
        for field, label, amount in (("contract_amount", "签约率", "(?:已签合同|签约)金额"),
                                     ("payment_amount", "付款率", "(?:已)?付款金额")):
            pattern = (rf"(?:{label}\s*(?:为|约|达到?|[：:=])?\s*|"
                       rf"{amount}[^。；%]{{0,100}}?占[^。；%]{{0,30}}?项目预算总额的?\s*)"
                       r"(?P<number>[+-]?\d+(?:\.\d+)?)\s*%")
            for match in re.finditer(pattern, sentence[0]):
                written_number = Decimal(match["number"])
                quantum = Decimal(1).scaleb(written_number.as_tuple().exponent)
                named = list(re.finditer(group_pattern, sentence[0][:match.start()])) if group_pattern else []
                total_scope = bool(named and named[-1][0] in total_names)
                if named and not total_scope:
                    group = named[-1][0]
                    values = {value for (analysis_id, name, metric), registered in chart_group_values.items()
                              if name == group and metric == field
                              and (not analyses or analysis_id is None or analysis_id in analyses)
                              for value in registered}
                    if len(values) == 1:
                        expected = next(iter(values)).quantize(quantum, rounding=ROUND_HALF_UP)
                        if written_number != expected:
                            warnings.append(
                                f"项目比率归属需复核：{group}{label}写为{written_number}%，"
                                f"同范围冻结分组值为{expected}%。")
                    # 分组值缺失或存在冲突时，不借用全院总额作判断。
                    continue
                values = set()
                for analysis_id, fact, value in candidates:
                    if fact.field != field or (analyses and analysis_id not in analyses):
                        continue
                    if any(scope and scope not in sentence[0] for scope in fact.scope.values()):
                        continue
                    # 分组或局部月份的比率不能使用全期总额校验。
                    groups = [item.group for item in (*fact.top_groups, *fact.bottom_groups)]
                    # 分组正文的百分数由 chart-input/v1 逐行登记；全期总额不能覆盖具体项目类型。
                    if not total_scope and any(group and group in sentence[0] for group in groups):
                        continue
                    if re.search(r"\d{1,2}月", sentence[0]):
                        continue
                    years = set(re.findall(r"(\d{4})年", sentence[0]))
                    if years and fact.period_start and years != {fact.period_start[:4]}:
                        continue
                    values.add(value)
                if len(values) != 1:
                    continue
                written = Decimal(match["number"])
                quantum = Decimal(1).scaleb(written.as_tuple().exponent)
                expected = next(iter(values)).quantize(quantum, rounding=ROUND_HALF_UP)
                if written != expected:
                    warnings.append(f"项目比率归属需复核：{label}写为{written}%，同范围冻结总额计算为{expected}%。")
    return list(dict.fromkeys(warnings))


def _group_ranking_tables(documents: list[dict[str, Any]],
                          field_definitions: Mapping[str, str] | None) -> list[dict[str, Any]]:
    """本期指标的冻结分组排名：业务名称、前列、末列与全部已登记分组值。"""
    tables: list[dict[str, Any]] = []
    for document in documents:
        for entry in document.get("metrics") or ():
            if not isinstance(entry, dict) or "current" not in (entry.get("periodRoles") or ()):
                continue
            ranked = {
                side: [(str(item["group"]), Decimal(str(item["value"]))) for item in entry.get(key) or ()
                       if isinstance(item, dict) and item.get("group")
                       and isinstance(item.get("value"), (int, float)) and not isinstance(item.get("value"), bool)]
                for side, key in (("top", "topGroups"), ("bottom", "bottomGroups"))
            }
            values = dict((*ranked["top"], *ranked["bottom"]))
            if len(values) >= 2:
                label = (field_definitions or {}).get(str(entry.get("field", "")), "")
                tables.append({"label": label if isinstance(label, str) else "", **ranked, "values": values})
    return tables


def _clause_ranking_tables(clause: str, tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """分句点名了指标业务名称时只看该指标的分组排名；未点名时所有带分组的指标都是候选。"""
    named = [table for table in tables if len(table["label"]) >= 2 and table["label"] in clause]
    named = [table for table in named
             if not any(table["label"] != other["label"] and table["label"] in other["label"] for other in named)]
    return named or tables


def _expected_groups(results: list[tuple[str, str]]) -> str:
    """各候选指标下的冻结结果；各指标结论一致时不重复列出指标名称。"""
    shown = list(dict.fromkeys(expected for expected, _ in results))
    if len(shown) == 1:
        return shown[0]
    return "；".join(f"{expected}（{label}）" if label else expected for expected, label in dict.fromkeys(results))


def _group_ranking_warnings(text: str, documents: list[dict[str, Any]],
                            field_definitions: Mapping[str, str] | None = None) -> list[str]:
    """“外科收入最高”与冻结分组排名不符时提示复核（软告警）。

    一个分句只点名一个已登记分组、只有一个极值词，且不含月份、比率或否定表述时判定，避免把
    月度极值或占比排名误判为分组总额排名。多个指标带分组排名时，按分句点名的指标业务名称
    取候选；无法确定指向时，只有该说法对所有候选指标都不成立才告警。
    """
    tables = _group_ranking_tables(documents, field_definitions)
    names = {group for table in tables for group in table["values"]}
    warnings: list[str] = []
    for clause in _CLAUSE_BREAK.split(text):
        named = [group for group in names if group in clause]
        # “心内科”同时命中“内科”时只认最长的组名。
        named = [group for group in named if not any(group != other and group in other for other in named)]
        high = [word for word in _GROUP_HIGH_WORDS if word in clause]
        low = [word for word in _GROUP_LOW_WORDS if word in clause]
        if (len(named) != 1 or len(high) + len(low) != 1
                or re.search(r"\d{1,2}月|季度|占比|比重|比例|增长率|增幅|降幅|增速|同比|环比|变化|不是|并非|未必|不能", clause)):
            continue
        group = named[0]
        results: list[tuple[str, str]] = []
        for table in _clause_ranking_tables(clause, tables):
            values = table["values"]
            if group not in values:
                continue
            expected_value = max(values.values()) if high else min(values.values())
            if values[group] == expected_value:
                results = []
                break
            results.append(("、".join(name for name, value in values.items() if value == expected_value), table["label"]))
        if results:
            label = "最高" if high else "最低"
            warnings.append(f"分组排名需复核：{group}被写为{label}，冻结分组结果的{label}为{_expected_groups(results)}。")
    return list(dict.fromkeys(warnings))


def _metric_value_attribution_warnings(text: str, contents: Iterable[str], documents: list[dict[str, Any]],
                                       field_definitions: Mapping[str, str]) -> list[str]:
    """“门诊收入同比增长5.03%”而 5.03% 是住院收入的登记值时提示数值归属（软告警）。

    分句只点名一个指标业务名称时判定：数值只对得上其他指标的登记值，对不上该指标、
    派生指标或补证中的任何登记值。业务名称取字段定义中含汉字、至少两个字符的名称。
    """
    labels_by_fact: dict[str, str] = {}
    for document in documents:
        for array in ("metrics", "comparisons"):
            for entry in document.get(array) or ():
                if not isinstance(entry, dict) or not isinstance(entry.get("factId"), str):
                    continue
                # 不同数据集常共用字段名（收入、成本都叫 indicator_value）：先取完整字段引用或事实
                # 显示名的定义，字段短名只作回退，否则两项指标会得到同一个名称而无法区分。
                display = re.split(r"[，,；;]", str(entry.get("displayName") or ""), maxsplit=1)[0].strip()
                label = (field_definitions.get(str(entry.get("fieldRef", ""))) or display
                         or field_definitions.get(str(entry.get("field", ""))))
                if isinstance(label, str) and len(label) >= 2 and re.search(r"[\u3400-\u9fff]", label):
                    labels_by_fact[entry["factId"]] = label
        # 维度分组是父指标的一部分：其数值归父指标所有，不能作为“不判定归属”的中性登记值。
        for entry in document.get("breakdowns") or ():
            if isinstance(entry, dict) and entry.get("parentFactId") in labels_by_fact:
                labels_by_fact[entry["factId"]] = labels_by_fact[entry["parentFactId"]]
    labels = set(labels_by_fact.values())
    if len(labels) < 2:
        return []
    # 正文常写区分部分（“收入金额”“成本金额”写作“收入”“成本”）：只登记唯一对应一项指标的简称。
    names: dict[str, set[str]] = {label: {label} for label in labels}
    for left in labels:
        for right in labels - {left}:
            for label, written in zip((left, right), _operand_names(left, right), strict=True):
                names.setdefault(written[-1], set()).add(label)
    # 回放：“出院人次”与“出院者占用床日数”去掉共同前缀后只剩单位“人次”，任何“644,217人次”
    # 都被当成点名了出院人次；简称不能是单位，查找名称时也先去掉数值及其单位。
    names = {name: owners for name, owners in names.items()
             if len(owners) == 1 and not _VALUE.fullmatch(f"1{name}")}
    # (业务名称或 None, 单位, 原值)：None 表示派生、对账或补证数值，对上时不判定归属。
    values: list[tuple[str | None, str, Decimal]] = []
    for token, value, unit, _target in _frozen_number_entries(contents):
        if value is not None and unit:
            values.append((labels_by_fact.get(token[2:-2].split(":")[1]), unit, Decimal(str(value))))
    for unit, numbers in supplemental_number_values(contents).items():
        values.extend((None, unit, number) for number in numbers)
    # 按（书写单位, 书写精度）建一次“舍入后绝对值 → 所属指标”索引：逐数字遍历全部登记值是
    # O(数字数×登记值数)，整份报告单次核对约需 9 秒；索引后为查表，判定结果不变。
    owner_index: dict[tuple[str, Decimal], dict[Decimal, set[str | None]]] = {}

    def owners_of(number: Decimal, written_unit: str, quantum: Decimal) -> set[str | None]:
        table = owner_index.get((written_unit, quantum))
        if table is None:
            table = {}
            for label, unit, value in values:
                scales = _unit_scales(unit)
                if unit != written_unit and (scales is None or written_unit not in scales):
                    continue
                converted = value if unit == written_unit else value * scales[unit] / scales[written_unit]
                # 下降幅度常写成正数：变化额、变化率按绝对值核对。
                table.setdefault(abs(converted).quantize(quantum, rounding=ROUND_HALF_UP), set()).add(label)
            owner_index[(written_unit, quantum)] = table
        return table.get(abs(number), set())

    warnings: list[str] = []
    for clause in _CLAUSE_BREAK.split(text):
        wording = _VALUE.sub("，", clause)
        written = [name for name in names if name in wording]
        written = [name for name in written if not any(name != other and name in other for other in written)]
        named = sorted({label for name in written for label in names[name]})
        if len(named) != 1:
            continue
        for match in _VALUE.finditer(clause):
            number = Decimal(match[1].replace(",", ""))
            if number == 0:
                continue
            quantum = Decimal(1).scaleb(-(len(match[1].split(".")[1]) if "." in match[1] else 0))
            owners = owners_of(number, match[2], quantum)
            if len(owners) == 1 and None not in owners and named[0] not in owners:
                warnings.append(f"指标数值归属需复核：{named[0]}名下的{match[0]}是{next(iter(owners))}的登记值。"
                                f"请改用{named[0]}对应的数值引用，或改写主语。")
    return list(dict.fromkeys(warnings))


_CHINESE_COUNTS = {**{word: index for index, word in enumerate("一二三四五六七八九十", 1)}, "两": 2}


# “位列前三”“排名后5位”；“前三季度”“前3个月”等期间写法不是排名。
_GROUP_TOP_N = re.compile(
    r"(?P<side>前|后|末|倒数)\s*(?P<n>[两二三四五六七八九十]|[2-9]|10)\s*(?:名|位)?(?!\s*(?:个|季|月|周|年|天|日|期|次|项|成))"
)


def _group_top_n_warnings(text: str, documents: list[dict[str, Any]],
                          field_definitions: Mapping[str, str] | None = None) -> list[str]:
    """“外科、骨科、儿科位列前三”与冻结分组排名不符时提示复核（软告警）。

    与最高/最低检查同一取候选规则。句中点名的已登记分组数须等于 N，且第 N 名与第 N+1 名
    不并列；月份、比率、同比环比与否定表述不判定；对任一候选指标成立即不告警。
    """
    tables = _group_ranking_tables(documents, field_definitions)
    names = {group for table in tables for group in table["values"]}
    warnings: list[str] = []
    for sentence in re.split(r"[。；\n]", text):
        claim = _GROUP_TOP_N.search(sentence)
        if (claim is None or re.search(r"\d{1,2}月|占比|比重|比例|增长率|增幅|降幅|增速|同比|环比|不是|并非|未进入|未能|未进|不在", sentence)):
            continue
        count = _CHINESE_COUNTS.get(claim["n"]) or int(claim["n"])
        named = [group for group in names if group in sentence]
        named = [group for group in named if not any(group != other and group in other for other in named)]
        if len(named) != count:
            continue
        results: list[tuple[str, str]] = []
        for table in _clause_ranking_tables(sentence, tables):
            items = table["top" if claim["side"] == "前" else "bottom"]
            if len(items) < count or (len(items) > count and items[count - 1][1] == items[count][1]):
                continue
            expected = [group for group, _ in items[:count]]
            if set(named) == set(expected):
                results = []
                break
            results.append(("、".join(expected), table["label"]))
        if results:
            side = "前" if claim["side"] == "前" else "后"
            written = "、".join(sorted(named, key=sentence.index))
            warnings.append(f"分组排名需复核：{written}被写为{side}{claim['n']}名，"
                            f"冻结分组结果的{side}{claim['n']}名为{_expected_groups(results)}。")
    return list(dict.fromkeys(warnings))


# 分句含比较、变化或全院合计语境时，数值不一定是该分组自身的值。
_GROUP_VALUE_CONTEXT = re.compile(
    r"较|比上|同比|环比|增加|减少|增长|下降|相差|差距|高出|低出|多出|少于|超出|全院|合计|共计|累计|总|占"
)


def _group_value_attribution_warnings(text: str, documents: list[dict[str, Any]]) -> list[str]:
    """“内科收入200元”而 200元 是外科的登记分组值时提示数值归属（软告警）。

    分句只点名一个已登记分组、不含比较或合计语境时判定：数值对不上该分组在任何同量纲
    指标中的登记值、也对不上指标本身的其他登记值，却恰好对上同一指标中另一个分组的值。
    """
    tables: list[tuple[str, dict[str, Decimal]]] = []
    # 指标、比较与派生事实中分组结果以外的登记值：对得上其中任何一个时不判定归属。
    registered: list[tuple[str, set[Decimal]]] = []
    for document in documents:
        breakdown_tables: dict[tuple[str, str], dict[str, Decimal]] = {}
        for entry in document.get("breakdowns") or ():
            # 维度分组：同一父指标、同一维度的各组合计就是一张登记分组表。
            if (isinstance(entry, dict) and isinstance(entry.get("unit"), str)
                    and entry.get("parentFactId") and entry.get("breakdownField")
                    and "current" in (entry.get("periodRoles") or ())
                    and isinstance(entry.get("total"), (int, float)) and not isinstance(entry.get("total"), bool)):
                group = (entry.get("scope") or {}).get(entry["breakdownField"])
                if group:
                    breakdown_tables.setdefault((entry["parentFactId"], entry["breakdownField"]), {})[str(group)] = (
                        Decimal(str(entry["total"])))
                    breakdown_tables[(entry["parentFactId"], entry["breakdownField"])]["__unit__"] = entry["unit"]
        for groups in breakdown_tables.values():
            unit = groups.pop("__unit__")
            if len(groups) >= 2:
                tables.append((unit, groups))
        # 分组事实的数值只作为分组表比较，不进“其他登记值”：否则一组的值写在另一组名下时恰好被放行。
        for array in ("metrics", "comparisons", "derivedMetrics", "reconciliations"):
            for entry in document.get(array) or ():
                if not isinstance(entry, dict) or not isinstance(entry.get("unit"), str):
                    continue
                registered.append((entry["unit"], _numeric_literals(
                    {key: value for key, value in entry.items() if key not in {"topGroups", "bottomGroups"}})))
                if array != "metrics" or "current" not in (entry.get("periodRoles") or ()):
                    continue
                groups = {str(item["group"]): Decimal(str(item["value"]))
                          for item in (*(entry.get("topGroups") or ()), *(entry.get("bottomGroups") or ()))
                          if isinstance(item, dict) and item.get("group")
                          and isinstance(item.get("value"), (int, float)) and not isinstance(item.get("value"), bool)}
                if len(groups) >= 2:
                    tables.append((entry["unit"], groups))
    # 编码类组名（“1”“A01”）会在数字中误命中；只认含汉字、至少两个字符的组名。
    names = {group for _, groups in tables for group in groups
             if len(group) >= 2 and re.search(r"[\u3400-\u9fff]", group)}
    warnings: list[str] = []
    for clause in _CLAUSE_BREAK.split(text):
        named = [group for group in names if group in clause]
        named = [group for group in named if not any(group != other and group in other for other in named)]
        if len(named) != 1 or _GROUP_VALUE_CONTEXT.search(clause):
            continue
        group = named[0]
        for match in _VALUE.finditer(clause):
            number = Decimal(match[1].replace(",", ""))
            digits = len(match[1].split(".", 1)[1]) if "." in match[1] else 0
            quantum = Decimal(1).scaleb(-digits)

            def shown(value: Decimal, unit: str, match: re.Match[str] = match, number: Decimal = number,
                      quantum: Decimal = quantum) -> bool:
                scales = _unit_scales(unit)
                if unit != match[2] and (scales is None or match[2] not in scales):
                    return False
                converted = value if unit == match[2] else value * scales[unit] / scales[match[2]]
                return converted.quantize(quantum, rounding=ROUND_HALF_UP) == number

            if (number == 0
                    or any(shown(value, unit) for unit, values in registered for value in values)
                    or any(shown(groups[group], unit) for unit, groups in tables if group in groups)):
                continue
            owners = {other for unit, groups in tables if group in groups
                      for other, value in groups.items() if other != group and shown(value, unit)}
            if len(owners) == 1:
                warnings.append(f"分组数值归属需复核：{group}名下的{match[0]}是{next(iter(owners))}的登记值。"
                                f"请改用{group}对应的数值引用，或改写主语。")
    return list(dict.fromkeys(warnings))


def _project_ratio_ranking_warnings(text: str, documents: list[dict[str, Any]]) -> list[str]:
    warnings = []
    for label, numerator_field in (("签约率", "contract_amount"), ("付款率", "payment_amount")):
        tables: dict[tuple[tuple[str, Decimal], ...], dict[str, Decimal]] = {}
        for document in documents:
            pending = list(document.get("findings", ()))
            while pending:
                finding = pending.pop()
                if isinstance(finding, list):
                    pending.extend(finding)
                    continue
                if not isinstance(finding, dict):
                    continue
                columns, rows, metadata = (finding.get(key) for key in ("columns", "rows", "columnMeta"))
                if not isinstance(columns, list) or not isinstance(rows, list):
                    pending.extend(value for value in finding.values() if isinstance(value, (list, dict)))
                    continue
                fields = ("budget_type", "budget_project_amount", numerator_field)
                if not all(field in columns for field in fields) or not isinstance(metadata, dict):
                    continue
                metas = [metadata.get(field, {}) for field in fields[1:]]
                if (any(meta.get("unit") != "元" for meta in metas)
                        or any(meta.get("periodRole") != "current" for meta in metas)):
                    continue
                indices = [columns.index(field) for field in fields]
                rates: dict[str, set[Decimal]] = {}
                for row in rows:
                    if not isinstance(row, list) or len(row) != len(columns):
                        continue
                    group, denominator, numerator = (row[index] for index in indices)
                    if (not isinstance(group, str) or not group
                            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                                   for value in (denominator, numerator))):
                        continue
                    denominator, numerator = Decimal(str(denominator)), Decimal(str(numerator))
                    if denominator.is_finite() and numerator.is_finite() and denominator > 0:
                        rates.setdefault(group, set()).add(numerator / denominator * 100)
                if len(rates) >= 2 and all(len(values) == 1 for values in rates.values()):
                    values = {group: next(iter(numbers)) for group, numbers in rates.items()}
                    tables[tuple(sorted(values.items()))] = values
        for sentence in re.split(r"[。；\n]", text):
            groups = {group for values in tables.values() for group in values if group in sentence}
            claim = re.search(re.escape(label) + r"[^。；\n]{0,25}?(最高|最低)", sentence)
            if (len(groups) != 1 or claim is None
                    or re.search(r"不是|并非|不能|不可|无法|未必", claim[0])
                    or re.search(r"\d{1,2}月|上年|去年|同期|同比", sentence)):
                continue
            group = next(iter(groups))
            choices = [values for values in tables.values() if group in values]
            if len(choices) != 1:
                continue
            values = choices[0]
            high = claim[1] == "最高"
            contrary = [other for other in values if
                        (values[other] > values[group] if high else values[other] < values[group])]
            if contrary:
                other = (max if high else min)(contrary, key=values.get)
                warnings.append(f"{label}排名需复核：{group}被写为{claim[1]}，同一补证中{other}的{label}为{values[other]:.2f}%，"
                                f"{'高' if high else '低'}于{group}的{values[group]:.2f}%。按同期间合同或付款金额/预算金额复核。")
    return warnings
