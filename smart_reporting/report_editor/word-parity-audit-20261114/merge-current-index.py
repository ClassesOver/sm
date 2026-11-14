"""Rebuild the current scoped ledger from adjacent historical evidence and overlays.

Run from any directory; no external packages or product tests are required.
"""
import copy
import hashlib
import json
from pathlib import Path
base=Path(__file__).resolve().parent
raw=(base/'command-index.json').read_bytes()
overlay_raw=(base/'remediation-index.json').read_bytes()
baseline=json.loads(raw)
overlays=json.loads(overlay_raw)
assert len(baseline['rows'])==844
assert len({r['id'] for r in baseline['rows']})==844
by_id={entry['id']:entry for entry in overlays['entries']}
assert len(by_id)==len(overlays['entries'])
assert set(by_id)<=set(r['id'] for r in baseline['rows'])
result=copy.deepcopy(baseline)
result['note']='Mechanically merged scoped current ledger. Original status/detail/section fields remain historical baseline evidence. Read effectiveStatus together with scope and evidence for current findings. Rows are command/field audit units, not independent defects or a completion percentage. A partial overlay never closes unstated targets or combinations.'
result['sourceCommit']=overlays['sourceCommit']
result['inputs']={'baseline':{'path':'command-index.json','sha256':hashlib.sha256(raw).hexdigest()},'scopedRemediation':{'path':'remediation-index.json','sha256':hashlib.sha256(overlay_raw).hexdigest()}}
result['sectionStatisticsMeaning']='The preserved sections statistics describe historical baseline statuses only; they are not current completion totals.'
result['verificationBoundary']='Evidence is limited to each batch and build scope recorded below; browser acceptance never closes unstated targets or combinations.'
result['batches']=copy.deepcopy(overlays.get('batches',[]))
result['coverageGroups']=copy.deepcopy(overlays.get('coverageGroups',[]))
result['remainingPriorities']=copy.deepcopy(overlays.get('remainingPriorities',[]))
result['sourceLimitedExclusions']=copy.deepcopy(overlays.get('sourceLimitedExclusions',[]))
for row,original in zip(result['rows'],baseline['rows'],strict=True):
    detail=original['detail']
    ledger=original['section']+'.md'
    finding=detail[4] if original['section']=='review-ai' else detail[5]
    source=detail[1] if original['section']=='review-ai' else detail[2]
    local=detail[2] if original['section']=='review-ai' else detail[3]
    row['baselineStatus']=original['status']
    row['baselineEvidence']={'ledger':ledger,'source':source,'local':local,'finding':finding,**({'locations':detail[6]} if original['section']=='objects' else {})}
    entry=by_id.get(row['id'])
    row['hasScopedRemediation']=entry is not None
    row['effectiveStatus']=entry['effectiveStatus'] if entry else original['status']
    row['scope']=entry['scope'] if entry else finding
    row['evidence']=entry['evidence'] if entry else ledger
    if entry:row['remediation']=copy.deepcopy(entry)
    for key,value in original.items():assert row[key]==value, (row['id'],key)
    if original['status']=='source-limited':assert row['effectiveStatus']=='source-limited'
assert len(result['rows'])==844 and len({r['id'] for r in result['rows']})==844
(base/'current-command-index.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('Merged 844 unique rows; all original row fields preserved; source-limited statuses unchanged.')
