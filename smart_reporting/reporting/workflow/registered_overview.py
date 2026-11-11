"""正式指标总览：事实身份与问题完成状态分别保留，不重新汇总。"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field

from ..contract import SHA256_PATTERN
from ..semantics.models import Identity, MetricResult, SemanticModel
from ..semantics.planning_contracts import MetricPlanningContext
from ..semantics.presentation import semantic_issue_message
from .management_overview import MAX_OVERVIEW_BYTES, MAX_OVERVIEW_ROWS


class RegisteredOverviewFact(SemanticModel):
    metric_name: str
    result: MetricResult
    subject_ids: tuple[Identity, ...] = Field(min_length=1)


class RegisteredOverviewRow(SemanticModel):
    question_id: Identity
    question: str
    status: Literal['answered', 'partial', 'unavailable']
    facts: tuple[RegisteredOverviewFact, ...] = ()
    issue_codes: tuple[Identity, ...] = ()


class RegisteredManagementOverview(SemanticModel):
    report_basis_id: Identity
    input_sha256: str = Field(pattern=SHA256_PATTERN)
    markdown_sha256: str = Field(pattern=SHA256_PATTERN)
    status: Literal['evaluated', 'unavailable']
    rows: tuple[RegisteredOverviewRow, ...] = ()
    issue_codes: tuple[Identity, ...] = ()


def build_registered_management_overview(quality, documents) -> RegisteredManagementOverview:
    """documents必须来自本次质量边界重新核验的来源；不能读取自报的通过结论。"""
    base = dict(report_basis_id=quality.report_basis_id, input_sha256=quality.input_sha256,
                markdown_sha256=quality.markdown_sha256)
    contexts = [document['metricContext'] for document in documents.values() if document.get('metricContext')]
    context = MetricPlanningContext.model_validate(contexts[0]) if contexts else None
    valid = bool(context and context.basis_id == quality.report_basis_id and all(item == contexts[0] for item in contexts))
    specs = {item.question_id: item.text for item in quality.question_specs.questions} if quality.question_specs else {}
    if valid:
        specs.update({item.id: item.text for item in context.request.questions})
    definitions = {(item.id, item.revision): item for item in context.metrics} if valid else {}
    results = {result.fact_id: result for calculation in context.calculations for result in calculation.results} if valid else {}
    supports = {item.subject_id: item for item in quality.claim_support if item.support_status == 'supported' and item.kind == 'fact'}
    rows = []
    for coverage in quality.registered_question_coverage:
        fact_subjects = {}
        for subject_id in coverage.subject_ids:
            support = supports.get(subject_id)
            for fact_id in support.fact_refs if support else ():
                fact_subjects.setdefault(fact_id, []).append(subject_id)
        facts = []
        for fact_id, subject_ids in fact_subjects.items():
            result = results.get(fact_id)
            definition = definitions.get((result.metric_version.metric_id, result.metric_version.revision)) if result else None
            if result and definition and result.status == 'computed' and not result.issue_codes:
                facts.append(RegisteredOverviewFact(metric_name=definition.name, result=result, subject_ids=tuple(subject_ids)))
        rows.append(RegisteredOverviewRow(question_id=coverage.question_id, question=specs.get(coverage.question_id, coverage.question_id),
            status=coverage.status, facts=tuple(facts), issue_codes=coverage.issue_codes))
    result = RegisteredManagementOverview(**base, status='evaluated' if rows else 'unavailable', rows=tuple(rows),
        issue_codes=() if rows else ('registered_question_sources_unavailable',))
    if len(rows) > MAX_OVERVIEW_ROWS or len(result.model_dump_json(by_alias=True).encode()) > MAX_OVERVIEW_BYTES:
        return RegisteredManagementOverview(**base, status='unavailable', issue_codes=('overview_budget_exceeded',))
    return result


def registered_overview_projection(overview: RegisteredManagementOverview, markdown_sha256: str, presentations=None) -> dict:
    if overview.markdown_sha256 != markdown_sha256:
        raise ValueError('overview does not belong to the rendered Markdown')

    def cell(value):
        return re.sub(r'([\\`*_{}\[\]()<>|#])', r'\\\1', ' '.join(str(value).splitlines()))

    citations = {}
    for item in presentations if isinstance(presentations, list) else ():
        if isinstance(item, dict) and isinstance(item.get('citationId'), str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', item['citationId']):
            citations[item.get('subjectId') or item['citationId']] = item['citationId']
    lines = ['事实核验与问题回答分别列示。期间采用起始日包含、结束日不包含的范围；不据此推断经营原因。', '',
        '| 管理问题 | 当前已核验事实 | 回答状态与缺项 |', '| --- | --- | --- |']
    for row in overview.rows:
        fragments, markers = [], []
        for fact in row.facts:
            result = fact.result
            scope = '；'.join(f'{item.dimension_id}={item.value}' for item in result.dimensions)
            fragments.append(f'{fact.metric_name}（版本{result.metric_version.revision}）：{result.value} {result.unit}；'
                f'{result.period.start} 至 {result.period.end}（不含结束日）' + ('；' + scope if scope else ''))
            markers.extend(citations[subject] for subject in fact.subject_ids if subject in citations)
        state = {'answered': '已回答', 'partial': '部分回答', 'unavailable': '尚无法回答'}[row.status]
        reasons = '；'.join(semantic_issue_message(code) for code in row.issue_codes)
        lines.append('| ' + cell(row.question) + ' | ' + cell('；'.join(fragments) or '暂不列示数值')
            + ''.join('[[citation:' + value + ']]' for value in dict.fromkeys(markers))
            + ' | ' + cell(state + ('；' + reasons if reasons else '')) + ' |')
    lines += ['', '事实通过核验不代表整份报告业务验收通过；未回答事项仍需补充证据。', '']
    return {'version': 'management-overview-render/1', 'sourceSha256': markdown_sha256,
        'qualityInputSha256': overview.input_sha256, 'status': overview.status, 'markdown': '\n'.join(lines)}
