"""声明支持状态只作来源绑定的展示提示，不认证业务结论。"""

from __future__ import annotations

import re

_SECTION = re.compile(r'\[\[section:([^\]\r\n]+)\]\]')
_CLAIM = re.compile(r'\[\[claim:([^\]\r\n]+)\]\]')
_LIMITATION = '> 解释与建议的支持状态未能核验，请勿据此推断经营原因。'


def insert_claim_support(markdown, payload, source_sha256):
    """同一声明必须在其登记章节唯一出现；不使用失配或自造的状态。"""
    try:
        if (not isinstance(payload, dict) or set(payload) != {'version', 'sourceSha256', 'claims'}
                or payload['version'] != 'claim-support-render/1' or payload['sourceSha256'] != source_sha256
                or not isinstance(payload['claims'], list) or len(payload['claims']) > 400):
            raise ValueError('claim support payload invalid')
        entries = {}
        for item in payload['claims']:
            if (not isinstance(item, dict) or set(item) != {'sectionId', 'claimId', 'kind', 'supportStatus'}
                    or item['kind'] not in {'fact', 'inference', 'recommendation'}
                    or item['supportStatus'] not in {'supported', 'unverified', 'conflicted'}
                    or any(not isinstance(item[key], str) or not 1 <= len(item[key]) <= 256
                           for key in ('sectionId', 'claimId'))):
                raise ValueError('claim support entry invalid')
            key = (item['sectionId'], item['claimId'])
            if key in entries:
                raise ValueError('claim support entry duplicated')
            entries[key] = item
        sections = list(_SECTION.finditer(markdown))

        def key_for(match):
            previous = [section[1] for section in sections if section.start() < match.start()]
            return (previous[-1] if previous else None, match[1])

        matches = list(_CLAIM.finditer(markdown))
        if any(sum(key_for(match) == key for match in matches) != 1 for key in entries):
            raise ValueError('claim support location unavailable')

        def replace(match):
            entry = entries.get(key_for(match))
            if entry is None:
                return match[0]
            label = {'fact': '事实陈述', 'inference': '推断', 'recommendation': '建议'}[entry['kind']]
            label += {'supported': '', 'unverified': '，待核实', 'conflicted': '，存在反证'}[entry['supportStatus']]
            return match[0] + '（' + label + '）'

        return _CLAIM.sub(replace, markdown), {'status': 'verified', 'reason': 'source_bound_claim_support'}
    except Exception:
        first = _SECTION.search(markdown)
        offset = first.start() if first else len(markdown)
        return markdown[:offset] + '\n\n' + _LIMITATION + '\n\n' + markdown[offset:], {
            'status': 'unknown', 'reason': 'claim_support_projection_unavailable'}
