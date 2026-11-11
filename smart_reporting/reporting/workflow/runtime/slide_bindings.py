"""正式幻灯片摘要与数值引用同源生成；不推断自由叙述的业务含义。"""

from hashlib import sha256

from ...delivery.draft_v1 import ReportDraftBlock
from ...delivery.report_runtime.markdown import normalize_cjk_punctuation, normalize_cjk_wording
from ...models import ReportingError
from ...trace.claim_semantics import freeze_interpretation
from ...trace.fact_index import fact_entry_from_pointer
from ...trace.fact_service import read_fact_document
from ...trace.semantic_bindings import (
    NumberReferenceResolver,
    anchor_bound_numbers,
    render_bound_numbers,
    statement_fingerprint,
)


def registered_slide_summary(card, fact_contents):
    """仅按明确登记的来源指针投影；不从摘要中搜索相同数值。"""
    registered = [ref for ref in card.source_refs if ref.pointer.startswith('/metricContext/')]
    if not registered or fact_contents is None:
        return None
    if len(registered) != 1 or len(card.fact_refs) != 1:
        raise ReportingError('report_slide_evidence_invalid', '正式幻灯片摘要需要唯一的结果来源。')
    source = registered[0]
    raw = fact_contents.get(source.analysis_id)
    if raw is None or sha256(raw).hexdigest() != source.file_sha256:
        raise ReportingError('report_slide_evidence_invalid', '幻灯片正式结果来源身份不一致。')
    document = read_fact_document(raw)
    try:
        kind, result = fact_entry_from_pointer(document, source.pointer)
    except KeyError as error:
        raise ReportingError('report_slide_evidence_invalid', '幻灯片正式结果位置不存在。') from error
    if (document['analysisId'] != source.analysis_id or kind != 'metric'
            or result.get('factId') != card.fact_refs[0]
            or [item.model_dump(by_alias=True) for item in card.metric_versions] != [result.get('metricVersion')]):
        raise ReportingError('report_slide_evidence_invalid', '幻灯片引用与正式结果不一致。')
    if result['status'] != 'computed':
        return None
    token = '{{value:' + result['factId'] + ':value:' + result['unit'] + '}}'
    selected = NumberReferenceResolver((raw.decode(),)).resolve(token)
    if selected is None:
        raise ReportingError('report_slide_evidence_invalid', '幻灯片正式结果无法解析。')
    metric = selected['metric_definition']
    period = f"[{selected['period']['start']}, {selected['period']['end']})"
    scope = tuple((field, value, f'{field}={value}') for field, value in selected['scope'].items())
    statistic = '比率' if metric['kind'] == 'ratio' else '合计'
    prefix = f"- 期间{period}内，" + ('范围' + '、'.join(item[2] for item in scope) + '，' if scope else '')
    prefix += metric['name'] + statistic + '为'
    # 复核器把日期转为中文显示；原文片段与投影使用同一规范化，避免原文依据失配。
    def evidence(text):
        return normalize_cjk_punctuation(normalize_cjk_wording(text))

    prefix = evidence(prefix)
    # 原值由既有格式化器渲染；日期、维度身份来自服务器，不经过模型自由数字清理。
    value, numbers, notices = render_bound_numbers(token, (raw.decode(),), key=card.finding_id)
    if len(numbers) != 1 or notices:
        raise ReportingError('report_slide_evidence_invalid', '幻灯片正式数值未能绑定。')
    markdown = prefix + value + '。'
    number = numbers[0].model_copy(update={'offset': numbers[0].offset + len(prefix)})
    anchored = anchor_bound_numbers(markdown, (number,))
    receipt = freeze_interpretation(anchored, number.claim_id, {
        'claimId': number.claim_id, 'period': selected['period'],
        'periodEvidence': [evidence(selected['period']['start']), evidence(selected['period']['end'])],
        'scope': [{'field': field, 'value': value, 'status': 'resolved', 'evidence': [evidence(label)]}
            for field, value, label in scope],
        'claimKind': 'fact', 'kindEvidence': [evidence(metric['name'] + statistic)],
        'metricVersion': result['metricVersion'], 'metricEvidence': [evidence(metric['name'])],
        'statistic': 'other' if metric['kind'] == 'ratio' else 'period_total',
        'statisticEvidence': [statistic],
    }, reference=selected)
    if receipt is None:
        raise ReportingError('report_slide_evidence_invalid', '幻灯片正式投影无法登记。')
    receipt = receipt.model_copy(update={'method': 'registered_result_projection_v1'})
    number = number.model_copy(update={'statement_sha256': statement_fingerprint(anchored, number.claim_id),
        'semantic_receipt': receipt})
    return ReportDraftBlock(blockId=card.finding_id, markdown=markdown, numberReferences=(number,), reviewNotices=())
