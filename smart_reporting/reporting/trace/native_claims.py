"""原生格式按整段登记文字复用当前支持状态，不从相同数值猜测语义。"""

import hashlib
import re

from markdown_it import MarkdownIt

from ..delivery.report_runtime.markdown import normalize_cjk_punctuation, normalize_cjk_wording
from ..semantics.models import ClaimSupport
from .claim_semantics import semantic_receipt_status
from .contracts_v1 import canonical_sha256
from .semantic_bindings import statement_fingerprint

_MARKER = re.compile(r'\[\[[^\]\r\n]+\]\]')
_CLAIM = re.compile(r'\[\[claim:([^\]\r\n]+)\]\]')


def _normalized(text):
    return re.sub(r'[\s*]', '', normalize_cjk_punctuation(normalize_cjk_wording(text)))


def native_claim_presentations(index, markdown, supports):
    """只接纳整段被一个登记声明覆盖的文字；相邻未登记句不能搭便车。"""
    current = {}
    for raw in supports:
        item = ClaimSupport.model_validate(raw)
        current[item.subject_id] = item if item.subject_id not in current else None
    subjects = {}
    for item in index.subject_bindings:
        if item.narrative_reference is not None or item.number_reference is not None:
            subjects[item.claim_id] = item if item.claim_id not in subjects else None
    lines, presentations = markdown.splitlines(keepends=True), {}
    tokens = MarkdownIt('commonmark').parse(markdown)
    for position, token in enumerate(tokens):
        if token.type != 'inline' or token.map is None or tokens[position - 1].type != 'paragraph_open':
            continue
        claims = _CLAIM.findall(token.content)
        if len(claims) != 1 or markdown.count(f'[[claim:{claims[0]}]]') != 1:
            continue
        subject = subjects.get(claims[0])
        support = current.get(subject.subject_id) if subject else None
        if support is None:
            continue
        raw = _MARKER.sub('', ''.join(lines[token.map[0]:token.map[1]])).rstrip()
        reference = subject.narrative_reference or subject.number_reference
        receipt = getattr(reference, 'semantic_receipt', None)
        if receipt is not None and (receipt.includes_previous or receipt.includes_section):
            continue
        if subject.narrative_reference is not None and (
                (receipt is not None and semantic_receipt_status(markdown, subject.claim_id, receipt) != 'interpreted')
                or (receipt is None and support.support_status != 'unverified')):
            continue
        fingerprint = (statement_fingerprint(raw + f'[[claim:{subject.claim_id}]]', subject.claim_id) if subject.narrative_reference is not None else
            hashlib.sha256(_normalized(raw.rstrip('。！？；;')).encode()).hexdigest())
        if fingerprint != reference.statement_sha256:
            continue
        key = canonical_sha256(_normalized(_MARKER.sub('', token.content)))
        value = {'subjectId': subject.subject_id, 'claimId': subject.claim_id, 'kind': support.kind,
            'sectionId': subject.locator.section_id,
            'analysisIds': list(dict.fromkeys([*(ref.analysis_id for ref in subject.fact_refs),
                *([reference.analysis_id] if getattr(reference, 'analysis_id', None) else [])])),
            'supportStatus': support.support_status, 'statementSha256': key,
            'sourceSha256': hashlib.sha256(markdown.encode()).hexdigest(),
            'factRefs': list(support.fact_refs), 'evidenceRefs': list(support.evidence_refs)}
        presentations.setdefault(key, []).append(value)
    return presentations


def present_native_summary(text, presentations, *, section_ids=(), analysis_ids=()):
    key = canonical_sha256(_normalized(text))
    candidates = [item for item in presentations.get(key, ())
        if item['sectionId'] in section_ids and set(item['analysisIds']) <= set(analysis_ids)
        and (not analysis_ids or item['analysisIds'])]
    support = candidates[0] if len(candidates) == 1 else None
    if support is None:
        support = {'kind': 'unknown', 'supportStatus': 'unverified', 'statementSha256': key,
            'reason': 'not_registered_as_reviewed_statement'}
        label = '支持关系待核实'
    else:
        support = dict(support)
        label = {'fact': '事实陈述', 'inference': '推断', 'recommendation': '建议'}[support['kind']]
        label += {'supported': '', 'unverified': '，待核实', 'conflicted': '，存在反证'}[support['supportStatus']]
        if support['kind'] == 'fact' and support['supportStatus'] == 'supported':
            label = ''
    return {'text': text + ('（' + label + '）' if label else ''), 'support': support}
