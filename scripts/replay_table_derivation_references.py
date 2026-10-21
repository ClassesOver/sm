#!/usr/bin/env python3
"""Replay immutable attachment bytes through renderer, index and editor restore.

Run with the project Python from any directory. Results and isolated workspace are
written below --output (a new directory); the archive/extraction are read-only.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import tarfile
import zipfile
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from markdown_it import MarkdownIt

from smart_reporting.report_editor import ReportEditorContext, ReportEditorService
from smart_reporting.reporting.data_sources import DatasetHandle
from smart_reporting.reporting.delivery.artifacts_v1 import (
    ArtifactFile,
    DatasetLineage,
    ReportArtifactManifest,
)
from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.trace import semantic_bindings
from smart_reporting.reporting.trace.contracts_v1 import canonical_json_bytes, derive_resource_id
from smart_reporting.reporting.trace.index_builder import build_csv_trace_index, encode_trace_index
from smart_reporting.reporting.trace.semantic_bindings import (
    anchor_bound_numbers,
    render_bound_numbers,
)
from smart_reporting.reporting.trace.subject_builder import build_claim_subject_bindings
from smart_reporting.reporting.trace.table_sources import resolve_table_derivation
from smart_reporting.reporting.workflow.scope import ReportingWorkflowScope, reporting_scope_keys


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read_archive(path):
    """Read bytes only; accept complete workspace tarballs as well as ZIP exports."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            members = {entry.filename: archive.read(entry) for entry in archive.infolist() if not entry.is_dir()}
    else:
        with tarfile.open(path) as archive:
            members = {}
            for entry in archive.getmembers():
                if not entry.isfile():
                    continue
                stream = archive.extractfile(entry)
                assert stream is not None
                members[entry.name] = stream.read()
    workspace_members = {name.removeprefix('workspace/'): raw for name, raw in members.items()
                         if name.startswith('workspace/')}
    if any(name.endswith('/report-revision-1.manifest.json') for name in workspace_members):
        # README/metadata outside workspace are packaging records, not report resources.
        members = workspace_members
    return members


def _discover(members):
    """Locate manifest/index/facts/supplements/chart-inputs in either archive layout.

    Supported layouts: revision artifacts at the run root (facts/, evidence/, analysis/)
    or entirely under revision-2/ with datasets in revision-2/trace-resources/.
    """
    manifests = sorted(name for name in members if name.endswith('/report-revision-1.manifest.json'))
    assert manifests, 'no report manifest in archive'
    root_manifests = [name for name in manifests if '/revision-2/' not in name]
    manifest_name = root_manifests[0] if root_manifests else manifests[0]
    base = manifest_name.rsplit('/', 1)[0]
    root_index = base + '/trace-index-v1.json' if base + '/trace-index-v1.json' in members else None
    rev_index = base + '/revision-2/trace-index-v1.json'
    rev_index_name = rev_index if rev_index in members else (root_index or next(
        name for name in members if name.endswith('/trace-index-v1.json')))
    facts = sorted(name for name in members
                   if name.startswith(base + '/facts/revision-1/') and name.endswith('.json'))
    if not facts:  # layouts that only ship facts beside the revision-2 manifest
        facts = sorted(name for name in members
                       if '/facts/revision-1/' in name and name.endswith('.json'))
    supplements = sorted(name for name in members if name.endswith('/supplement.json'))
    # An export may copy the same chart inputs into revision-2. Prefer those
    # beside the selected manifest rather than registering identical tables twice.
    charts = sorted(name for name in members if name.endswith('.chart-input.json')
                    and name.rsplit('/', 1)[0] == base)
    if not charts:
        charts = sorted(name for name in members if name.endswith('.chart-input.json'))
    assert facts, 'no fact files discovered'
    return manifest_name, (root_index or rev_index_name), rev_index_name, facts, supplements, charts


def identity(path, raw, media='application/json'):
    return ArtifactFile(path=path, mediaType=media, size=len(raw), sha256=sha(raw))


def jsonable(value):
    if hasattr(value, 'model_dump'):
        return value.model_dump(mode='json', by_alias=True)
    return str(value)


_NUMBER_OCCURRENCE = re.compile(r"(?<![\d.,])(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)")


def _reference_kind(ref) -> str:
    if ref.token.startswith('{{tableDerived:'):
        return 'tableDerived'
    if ref.token.startswith('{{derived:'):
        return 'factPairDerived'
    return 'factReference'


def _occurrence_index(plain: str, ref) -> int | None:
    """按渲染后纯文本中第 N 个数字出现定位引用；offset 是锚点在纯文本中的装配偏移。"""
    display = ref.display_text
    if not display or plain[ref.offset - len(display):ref.offset] != display:
        return None
    numeric = re.match(r'[+-]?[\d,]+(?:\.\d+)?', display)
    if numeric is None:
        return None
    suffix = display[numeric.end():]
    for index, occurrence in enumerate(_NUMBER_OCCURRENCE.finditer(plain)):
        if (occurrence['number'] == numeric.group(0)
                and occurrence.end() + len(suffix) == ref.offset
                and plain[occurrence.end():occurrence.end() + len(suffix)] == suffix):
            return index
    return None


def baseline_compare(args):
    """只读反事实对照：同一原始段落、同一核验来源 contents，仅 table_sources=None 重跑 renderer。

    不重复 subject/index/editor/restore 链路；首次回放 results.json 只用于段落清单与来源清单复用。
    对齐键为 (section, 原始段落行号, 段内数字出现序号, 显示文本)，claimId 在两次独立渲染间不可比。
    """
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    first = json.loads(Path(args.baseline_from).read_text())
    extracted = args.extracted.resolve()
    members = _read_archive(args.archive)
    for name, raw in members.items():
        assert (extracted / name).read_bytes() == raw, f'extraction mismatch: {name}'
    _, _, _, facts, supplements, charts = _discover(members)
    first_counts = first['counts']
    assert (len(facts), len(charts), len(supplements)) == (
        first_counts['facts'], first_counts['chartInputs'], first_counts['supplements'])
    source_names = facts + charts + supplements
    inventory = {item['archiveMember']: item for item in first['sourceInventory']}
    for name in source_names:
        item = inventory[name]
        assert item['size'] == len(members[name]) and item['sha256'] == sha(members[name]), name
    sources = {derive_resource_id(name): members[name] for name in source_names}
    contents = [members[name].decode() for name in source_names]
    verdicts = {'baseline': Counter(), 'current': Counter()}
    run_label = ['baseline']
    real_replace = semantic_bindings.replace_unregistered_numbers

    def observed(markdown, contents_arg, **kwargs):
        # on_verdict 仅观测核对结论，不改变替换行为（numeric_text 既有契约）。
        def on_verdict(verdict, _number, _unit, reason):
            verdicts[run_label[0]][f'{verdict}:{reason}'] += 1
        kwargs.setdefault('on_verdict', on_verdict)
        return real_replace(markdown, contents_arg, **kwargs)

    semantic_bindings.replace_unregistered_numbers = observed
    baseline_map, current_map = {}, {}
    baseline_notices, current_notices = Counter(), Counter()
    paragraph_records = []
    reproduced = True
    try:
        for record in first['blocks']:
            key = f"attachment-replay:{record['section']}:{record['originalLine'] - 1}"
            run_label[0] = 'baseline'
            baseline_rendered, baseline_refs, baseline_reviews = render_bound_numbers(
                record['originalText'], contents, key=key, table_sources=None)
            run_label[0] = 'current'
            current_rendered, current_refs, current_reviews = render_bound_numbers(
                record['originalText'], contents, key=key, table_sources=sources)
            reproduced = reproduced and [jsonable(ref) for ref in current_refs] == record['references']
            for ref in baseline_refs:
                baseline_map[(record['section'], record['originalLine'],
                              _occurrence_index(baseline_rendered, ref), ref.display_text)] = ref
            for ref in current_refs:
                current_map[(record['section'], record['originalLine'],
                             _occurrence_index(current_rendered, ref), ref.display_text)] = ref
            baseline_notices.update(item.kind for item in baseline_reviews or ())
            current_notices.update(item.kind for item in current_reviews or ())
            paragraph_records.append({'section': record['section'], 'originalLine': record['originalLine'],
                                      'baselineReferences': [jsonable(ref) for ref in baseline_refs],
                                      'currentReferences': [jsonable(ref) for ref in current_refs],
                                      'baselineRenderedText': baseline_rendered,
                                      'currentRenderedText': current_rendered})
    finally:
        semantic_bindings.replace_unregistered_numbers = real_replace
    added = set(current_map) - set(baseline_map)
    removed = set(baseline_map) - set(current_map)
    retained = set(baseline_map) & set(current_map)

    def detail(keys, mapping):
        return [{'section': key[0], 'originalLine': key[1], 'occurrenceIndex': key[2],
                 'displayText': key[3], 'kind': _reference_kind(mapping[key]),
                 'token': mapping[key].token}
                for key in sorted(keys, key=lambda item: (item[1], item[2] if item[2] is not None else -1, item[3]))]

    counts = {
        'mode': 'renderer-baseline-comparison',
        'baselineFrom': str(args.baseline_from),
        'paragraphsCompared': len(first['blocks']),
        'baselineReferences': len(baseline_map),
        'finalReferences': len(current_map),
        'newlyEnabledTableDerived': sum(_reference_kind(current_map[key]) == 'tableDerived' for key in added),
        'factPairReissued': sum(_reference_kind(current_map[key]) == 'factPairDerived' for key in added),
        'factReferenceReissued': sum(_reference_kind(current_map[key]) == 'factReference' for key in added),
        'retained': len(retained),
        'lost': len(removed),
        'baselineKinds': dict(Counter(_reference_kind(ref) for ref in baseline_map.values())),
        'finalKinds': dict(Counter(_reference_kind(ref) for ref in current_map.values())),
        'firstRunReferencesReproducedExactly': reproduced,
        'unreferencedReasons': {
            'baselineNotices': dict(baseline_notices),
            'currentNotices': dict(current_notices),
            'baselineVerdicts': dict(verdicts['baseline']),
            'currentVerdicts': dict(verdicts['current']),
        },
    }
    result = {'counts': counts, 'output': str(output), 'addedOccurrences': detail(added, current_map),
              'removedOccurrences': detail(removed, baseline_map),
              'retainedOccurrences': detail(retained, current_map), 'paragraphs': paragraph_records,
              'limitations': ['Renderer-only counterfactual: subject binding, index registration and editor validation are not repeated.',
                'occurrenceIndex is the ordinal of the referenced number among number occurrences in the rendered plain paragraph.',
                'Verdict instrumentation uses the existing on_verdict observation hook and does not alter replacement behavior.']}
    (output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=jsonable) + '\n')
    print(json.dumps({'counts': counts, 'results': str(output / 'results.json')}, ensure_ascii=False, indent=2))


async def replay(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    extracted = args.extracted.resolve()
    members = _read_archive(args.archive)
    for name, raw in members.items():
        assert (extracted / name).read_bytes() == raw, f'extraction mismatch: {name}'
    manifest_name, old_index_name, rev_index_name, facts, supplements, charts = _discover(members)
    old_manifest = ReportArtifactManifest.model_validate_json(members[manifest_name])
    old_index = json.loads(members[old_index_name])
    rev_index = json.loads(members[rev_index_name])
    by_digest = {}
    for name, raw in members.items():
        by_digest.setdefault((len(raw), sha(raw)), []).append(name)
    old_file_checks = []
    for entry in old_index['files']:
        exact = entry['path'] in members
        matching = by_digest.get((entry['size'], entry['sha256']), [])
        if exact:
            assert len(members[entry['path']]) == entry['size'] and sha(members[entry['path']]) == entry['sha256']
        assert matching, entry['path']
        old_file_checks.append({**entry, 'exactPathPresent': exact, 'matchingArchiveMembers': matching})
    chart_sources = []
    for name in charts:
        source = json.loads(members[name])['source']
        # Some archives omit the evidence/ tree entirely; record unverifiable chart
        # sources honestly instead of failing the replay.
        raw = members.get(source['path'])
        chart_sources.append({'chartInput': name, 'source': source,
                              'identityVerified': raw is not None and sha(raw) == source['sha256']})
    source_names = facts + charts + supplements
    sources = {derive_resource_id(name): members[name] for name in source_names}
    assert len({sha(raw) for raw in sources.values()}) == len(sources), 'ambiguous duplicate content IDs'
    inventory = [{'archiveMember': name, 'extractedPath': str(extracted / name),
                  'resourceId': derive_resource_id(name), 'size': len(members[name]), 'sha256': sha(members[name])}
                 for name in source_names]
    original = members[old_manifest.markdown.path].decode()
    revision_two_md = next(entry for entry in rev_index['files'] if entry['resourceId'] == rev_index['markdownFileResourceId'])
    assert members[revision_two_md['path']] == original.encode()
    # Remove historical claim markers only in the isolated replay; retain source text.
    clean = re.sub(r'\[\[claim:[^\]\n]+\]\]', '', original)
    lines = clean.splitlines(keepends=True)
    tokens = MarkdownIt('commonmark').enable('table').parse(clean)
    ranges = []
    excluded = Counter()
    for pos, token in enumerate(tokens):
        if token.type != 'paragraph_open' or token.map is None:
            continue
        start, end = token.map
        inline = tokens[pos + 1]
        text = ''.join(lines[start:end]).strip()
        if any(child.type == 'image' for child in (inline.children or [])):
            excluded['imageParagraphs'] += 1
            continue
        if text.startswith('*图表：'):
            excluded['chartCaptions'] += 1
            continue
        if re.fullmatch(r'(?:\[\[[^\]\n]+\]\]\s*)+', text):
            excluded['protocolParagraphs'] += 1
            continue
        if token.level != 0:
            excluded['nestedParagraphs'] += 1
            continue
        ranges.append((start, end))
    artifacts = []
    references = []
    records = []
    replacements = {}
    notices = []
    artifacts_by_section = {}
    contents = [members[name].decode() for name in source_names]
    for block_no, (start, end) in enumerate(ranges):
        preceding = ''.join(lines[:start])
        section_matches = re.findall(r'\[\[section:([^\]]+)\]\]', preceding)
        if not section_matches:
            continue
        section = section_matches[-1]
        before = ''.join(lines[start:end]).rstrip('\n')
        rendered, refs, reviews = render_bound_numbers(before, contents, key=f'attachment-replay:{section}:{start}', table_sources=sources)
        anchored = anchor_bound_numbers(rendered, refs, reviews)
        replacements[start] = (end, anchored + '\n')
        block = ReportDraftBlock(blockId=f'replay-{block_no}', markdown=anchored,
                                 numberReferences=refs, reviewNotices=reviews)
        artifacts_by_section.setdefault(section, []).append(block)
        references.extend(refs)
        notices.extend(reviews or ())
        records.append({'section': section, 'originalLine': start + 1, 'originalText': before,
                        'renderedText': anchored, 'references': [jsonable(ref) for ref in refs],
                        'reviewNotices': [jsonable(item) for item in reviews or ()]})
    new_lines = []
    cursor = 0
    while cursor < len(lines):
        if cursor in replacements:
            end, text = replacements[cursor]
            new_lines.append(text)
            cursor = end
        else:
            new_lines.append(lines[cursor])
            cursor += 1
    markdown = ''.join(new_lines)
    # Transparent block adapter: no invented structured SectionClaim/fact authority.
    artifacts = [SimpleNamespace(section_code=section, blocks=tuple(blocks), claims=())
                 for section, blocks in artifacts_by_section.items()]
    fact_directory = {}
    fact_resources = {}
    fact_files = {}
    for name in facts:
        doc = json.loads(members[name])
        analysis = doc['analysisId']
        fact_resources[analysis] = derive_resource_id(name)
        fact_files[analysis] = identity(name, members[name])
        for array in ('metrics', 'derivedMetrics', 'comparisons', 'reconciliations', 'correlationDetails'):
            for position, item in enumerate(doc.get(array) or []):
                if isinstance(item, dict) and item.get('factId'):
                    fact_directory[item['factId']] = (analysis, f'/{array}/{position}')
    subjects = build_claim_subject_bindings(artifacts, fact_directory, fact_resources)
    recomputed = []
    for ref in references:
        if ref.table_derivation is not None:
            selected = resolve_table_derivation(ref.token, ref.table_derivation, sources)
            recomputed.append({'claimId': ref.claim_id, 'selected': selected, 'success': selected is not None})
    report_id = 'attachment-table-replay'
    keys = reporting_scope_keys(database='attachment-replay', company_id='attachment-replay',
                                user_id='attachment-replay', thread_id='attachment-replay', run_id=report_id)
    scope = ReportingWorkflowScope(run_id=report_id, external_run_id='attachment-replay',
                                   session_id='attachment-replay', caller_thread_id='attachment-replay',
                                   user_id='attachment-replay', database='attachment-replay', company_id='attachment-replay',
                                   thread_lease_key=keys.thread_lease_key, workspace_key=keys.workspace_key)
    registry = ReportingWorkspaceRegistry(output / 'workspace', secret='attachment-replay-local-only-secret')
    workspace = ReportingWorkspaceRouter(registry)
    registry.resolve(scope)
    # Original bytes are copied into a fresh scope; nothing is written to the extraction.
    for name, raw in members.items():
        await workspace.awrite_bytes(scope.workspace_key, name, raw)
    handles, lineage = [], []
    old_files = {entry['resourceId']: entry for entry in old_index['files']}
    dataset_records = []
    for dataset in old_index['datasets']:
        file = old_files[dataset['fileResourceId']]
        raw = members[file['path']]
        handle = DatasetHandle(dataset_id=dataset['datasetId'], source_id='attachment-verified',
                               source_type=dataset['sourceType'], path=file['path'], row_count=dataset['rowCount'],
                               size=len(raw), sha256=sha(raw), requirement_id=dataset['requirementId'],
                               sql_hash=dataset['sqlHash'], filename=dataset.get('filename'),
                               period_roles=tuple(dataset['periodRoles']), query_window_id=dataset['queryWindowId'],
                               materialized_at=dataset.get('materializedAt'), business_label=dataset.get('businessLabel'),
                               query_sql=dataset.get('querySql'))
        handles.append(handle)
        lineage.append(DatasetLineage(datasetId=handle.dataset_id, sourceId=handle.source_id,
                                      sourceType=handle.source_type, requirementId=handle.requirement_id,
                                      sqlHash=handle.sql_hash, rowCount=handle.row_count, size=handle.size,
                                      sha256=handle.sha256, periodRoles=handle.period_roles, queryWindowId=handle.query_window_id))
        dataset_records.append({**dataset, 'verifiedFile': file, 'sourceIdNote': 'replay-local routing identifier; archive index has no sourceId'})
    md_path = 'replay/report.md'
    await workspace.awrite_text(scope.workspace_key, md_path, markdown)
    index = build_csv_trace_index(handles=handles, lineage=lineage, report_id=report_id, revision=1,
                                 workflow_run_id=report_id, markdown_file=identity(md_path, markdown.encode(), 'text/markdown'),
                                 profile_hash=old_manifest.effective_profile_hash, fact_files=fact_files,
                                 chart_trace_files=[identity(name, members[name]) for name in charts],
                                 table_source_files=[identity(name, members[name]) for name in source_names],
                                 subject_bindings=subjects, review_notices=notices)
    index_bytes = encode_trace_index(index)
    index_path = 'replay/trace-index-v1.json'
    await workspace.awrite_bytes(scope.workspace_key, index_path, index_bytes)
    manifest_data = old_manifest.model_dump(mode='json', by_alias=True)
    manifest_data.update(reportId=report_id, revision=1, markdown=jsonable(identity(md_path, markdown.encode(), 'text/markdown')),
                         traceIndex=jsonable(identity(index_path, index_bytes)), tables=[], charts=[])
    manifest = ReportArtifactManifest.model_validate(manifest_data)
    manifest_path = 'replay/report.manifest.json'
    manifest_bytes = canonical_json_bytes(manifest.model_dump(mode='json', by_alias=True))
    await workspace.awrite_bytes(scope.workspace_key, manifest_path, manifest_bytes)
    context = ReportEditorContext(artifactManifest=identity(manifest_path, manifest_bytes), reportId=report_id,
                                  revision=1, jobId='attachment-replay', workflowRunId=report_id,
                                  markdownPath=md_path, job={'jobId': 'attachment-replay', 'status': 'validated'}, scope=scope.as_state())
    state = SimpleNamespace(payload={'reportEditorContexts': {'1': context.model_dump(mode='json', by_alias=True)}})
    async def get_state(*_args, **_kwargs):
        return state
    editor = ReportEditorService(state_repository=SimpleNamespace(get=get_state), workspace_registry=registry, workspace=workspace)
    async def validate(text):
        return await editor.trace.validate(context, text, sha(text.encode()))
    baseline = await validate(markdown)
    mutation_details = []
    # All edits are independent from the baseline and never overwrite its registered file.
    for ref in references:
        marker = f'[[claim:{ref.claim_id}]]'
        assert markdown.count(marker) == 1
        marker_at = markdown.index(marker)
        before = markdown[:marker_at]
        display = ref.display_text
        assert display and before.endswith(display), (display, before[-100:])
        changed = re.sub(r'\d', lambda m: str((int(m[0]) + 1) % 10), display, count=1)
        start = marker_at - len(display)
        edited = markdown[:start] + changed + markdown[marker_at:]
        checked = await validate(edited)
        detail = next(item for item in checked['subjects'] if item.get('claimId') == ref.claim_id)
        restore_text = detail.get('restoreText')
        restored = edited[:start] + restore_text + edited[start + len(changed):] if restore_text is not None else None
        restored_result = await validate(restored) if restored is not None else None
        restored_detail = next((item for item in (restored_result or {}).get('subjects', []) if item.get('claimId') == ref.claim_id), None)
        mutation_details.append({'claimId': ref.claim_id, 'display': display, 'editedDisplay': changed,
                                 'edited': detail, 'restored': restored_detail, 'exactBaselineRestored': restored == markdown})
    final_originals_unchanged = all((extracted / name).read_bytes() == raw for name, raw in members.items())
    assert final_originals_unchanged
    counts = {'archiveFilesVerified': len(members), 'facts': len(facts), 'chartInputs': len(charts), 'supplements': len(supplements),
              'chartSourcesVerified': sum(item['identityVerified'] for item in chart_sources),
              'bodyParagraphsRendered': len(records), 'historicalClaimMarkersRemoved': original.count('[[claim:'),
              'newBodyReferences': len(references), 'tableDerivedReferences': sum(ref.table_derivation is not None for ref in references),
              'subjectsBuilt': len(subjects), 'numberSubjectsIndexed': sum(item.number_reference is not None for item in index.subject_bindings),
              'originalByteRecomputationsSuccessful': sum(item['success'] for item in recomputed),
              'editorBaseline': baseline['summary'], 'editedStale': sum(item['edited']['status'] == 'stale' for item in mutation_details),
              'restoreTextAvailable': sum(item['edited'].get('restoreText') is not None for item in mutation_details),
              'restoredValid': sum(item['restored'] is not None and item['restored']['status'] == 'valid' for item in mutation_details),
              'exactBaselineRestored': sum(item['exactBaselineRestored'] for item in mutation_details),
              'reviewNotices': len(notices), 'excludedParagraphs': dict(excluded)}
    result = {'counts': counts, 'archive': {'path': str(args.archive), 'size': args.archive.stat().st_size,
               'sha256': sha(args.archive.read_bytes())}, 'output': str(output), 'sourceInventory': inventory,
              'oldIndexFileChecks': old_file_checks, 'chartSourceChecks': chart_sources,
              'datasets': dataset_records, 'blocks': records, 'recomputed': recomputed,
              'editorBaseline': baseline, 'mutations': mutation_details, 'originalFilesUnchanged': final_originals_unchanged,
              'manifestIdentity': jsonable(identity(manifest_path, manifest_bytes)),
              'traceIndexIdentity': jsonable(identity(index_path, index_bytes)),
              'limitations': ['Two archive layouts are supported: revision artifacts at the run root or entirely under revision-2/.',
                'Archives may omit the evidence/ tree; chart-input source references are then recorded as unverifiable instead of failing.',
                'Archive may contain multi-attempt chart inputs (e.g. chart-013 with 4 attempts in one sample).',
                'Original Markdown has already replaced some values with 待核实; missing original displays cannot be recovered from this report text.',
                'No supplement is added to factFiles, no fabricated computation or structured claim is created.',
                'Section adapter carries actual renderer blocks, not a full LLM workflow or PDF/Word publication.',
                'Historical references are removed only in the isolated replay; counts are newly issued occurrences, not net historical growth.',
                'Editor restore is exercised through real validate/restoreText plus in-memory display replacement, not browser/UI or HTTP export.']}
    (output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=jsonable) + '\n')
    (output / 'rendered.md').write_text(markdown)
    print(json.dumps({'counts': counts, 'results': str(output / 'results.json')}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=Path('/home/junge/下载/report-revision-2-artifacts.zip'))
    parser.add_argument('--extracted', type=Path, default=Path('/tmp/replay-77'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline-from', type=Path, default=None,
                        help='只读模式：读取首次回放 results.json，仅重跑 renderer 做 table_sources=None 反事实对照')
    args = parser.parse_args()
    if args.baseline_from is not None:
        baseline_compare(args)
        return
    asyncio.run(replay(args))


if __name__ == '__main__':
    main()
