"""受审原生落款内容检查到生产字段证据的窄映射。"""

import math
import re
from copy import deepcopy

from ..preferences.approval_contract import _valid_artifact, _valid_binding, approval_contract_hash
from .preference_preflight_readback import (
    CHART_IMAGE_DPI_EVIDENCE,
    TERMINAL_SIGNATURE_CONTENT_EVIDENCE,
)

PPTX_INDENT_EVIDENCE = 'pptx_native_indent_fields_v1'
_PPTX_INDENTS = {'pptx.' + local for local in ('signature.indent', 'footerStyle.indent',
    'typography.body.indent', 'typography.h1.indent', 'typography.table.indent', 'typography.caption.indent')}
_CHART_IMAGE_DPI = {format + '.charts.imageDpi' for format in ('pptx', 'pdf', 'word')}


def map_native_chart_image_dpi_evidence(result, contract, runtime_binding, retained):
    """Map complete per-image DPI readback to native evidence for this retained draft."""
    binding = result.get('binding', {})
    if (binding.get('valid') is not True or binding.get('artifactAccessAuthorized') is not True
        or not _valid_binding(runtime_binding)
        or runtime_binding['contractHash'] != approval_contract_hash(contract)
        or type(result.get('draftVersion')) is not int or result['draftVersion'] != runtime_binding['draftVersion']
        or result.get('contentHash') != runtime_binding['draftHash']):
        return []
    registered = {field['path']: field for field in contract.get('fields', [])}
    evidence = []
    for requirement in contract['requirements']:
        for field in requirement['checks']:
            format, path = field.get('format'), field.get('path')
            registration = registered.get(path, {})
            if (path not in _CHART_IMAGE_DPI or field.get('scenario') != 'configured_field'
                or 'native' not in field['dimensions'] or registration.get('support') != 'implemented'
                or registration.get('editable') is not True or registration.get('semanticRole') != field.get('role')
                or requirement['id'] not in registration.get('requirementIds', [])
                or 'native' not in registration.get('evidenceDimensions', [])):
                continue
            entry = result.get('formats', {}).get(format, {})
            inline = entry.get('artifact') or {}
            reference = retained.get('formats', {}).get(format, {}).get('artifact') or {}
            artifact = {'sizeBytes': inline.get('size'), 'sha256': inline.get('sha256')}
            if (not _valid_artifact(artifact) or type(reference.get('size')) is not int
                or reference['size'] != artifact['sizeBytes'] or reference.get('sha256') != artifact['sha256']
                or any(issue.get('format') == format and issue.get('role') in (None, 'artifact')
                    for issue in retained.get('issues', []))):
                continue
            checks = [item for item in entry.get('readback', {}).get('checks', []) if item.get('path') == path]
            marked = [item for item in checks if item.get('evidenceKind') == CHART_IMAGE_DPI_EVIDENCE]
            if not marked:
                continue
            failed = any(item.get('passed') is False for item in checks)
            capabilities = [item for item in entry.get('capabilities', []) if item.get('path') == path]
            complete = (len(checks) == 1 and len(marked) == 1 and len(capabilities) == 1
                and checks[0].get('passed') is True and checks[0].get('actual') is True
                and checks[0].get('expected') is True and checks[0].get('coverage') == 'complete'
                and capabilities[0].get('status') == 'verified')
            objects = marked[0].get('evidenceObjects') or {}
            target = objects.get('targetDpi')
            valid_target = type(target) in (int, float) and math.isfinite(target)
            if (not valid_target or capabilities and capabilities[0].get('value') != target):
                complete = False
            expected, read = objects.get('expectedImages'), objects.get('readImages')
            images = objects.get('images')
            complete = complete and type(expected) is int and expected > 0 and type(read) is int and read == expected
            complete = complete and isinstance(images, list) and len(images) == expected
            if isinstance(images, list):
                for image in images:
                    effective = image.get('effectiveDpi') if isinstance(image, dict) else None
                    media_hash = image.get('mediaSha256') if isinstance(image, dict) else None
                    if (not isinstance(media_hash, str) or re.fullmatch('[0-9a-f]{64}', media_hash) is None
                        or not isinstance(effective, dict)):
                        complete = False
                        continue
                    for axis in ('x', 'y'):
                        value = effective.get(axis)
                        if (not valid_target or type(value) not in (int, float) or not math.isfinite(value)
                            or value <= 0 or value > target + .05):
                            complete = False
            if failed or complete:
                evidence.append({'requirementId': requirement['id'], 'format': format,
                    'role': field['role'], 'scenario': 'configured_field', 'path': path, 'dimension': 'native',
                    'status': 'failed' if failed else 'passed',
                    'objectScope': 'complete' if complete else 'partial', 'authorized': True,
                    'binding': deepcopy(runtime_binding), 'artifact': deepcopy(artifact),
                    'sourceArtifact': {'format': format, 'role': 'artifact'},
                    'readerGroup': CHART_IMAGE_DPI_EVIDENCE,
                    'readbackCheckIndexes': [index for index, item in enumerate(
                        entry.get('readback', {}).get('checks', [])) if item.get('path') == path],
                    'message': '全部登记图表图片的实际有效DPI回读通过。' if complete
                        else '图表图片有效DPI回读未通过或覆盖不完整。'})
    return evidence


def map_native_pptx_indent_evidence(result, contract, runtime_binding, retained):
    """六角色完整原生段落缩进；不把采样或空角色提升为验收证据。"""
    binding = result.get('binding', {})
    if (binding.get('valid') is not True or binding.get('artifactAccessAuthorized') is not True
        or not _valid_binding(runtime_binding)
        or runtime_binding['contractHash'] != approval_contract_hash(contract)
        or type(result.get('draftVersion')) is not int or result['draftVersion'] != runtime_binding['draftVersion']
        or result.get('contentHash') != runtime_binding['draftHash']):
        return []
    entry = result.get('formats', {}).get('pptx', {})
    inline = entry.get('artifact') or {}
    reference = retained.get('formats', {}).get('pptx', {}).get('artifact') or {}
    artifact = {'sizeBytes': inline.get('size'), 'sha256': inline.get('sha256')}
    if (not _valid_artifact(artifact) or type(reference.get('size')) is not int
        or reference['size'] != artifact['sizeBytes'] or reference.get('sha256') != artifact['sha256']
        or any(issue.get('format') == 'pptx' and issue.get('role') in (None, 'artifact')
            for issue in retained.get('issues', []))):
        return []
    registered = {field['path']: field for field in contract.get('fields', [])}
    indexed = list(enumerate(entry.get('readback', {}).get('checks', [])))
    evidence = []
    for requirement in contract['requirements']:
        for field in requirement['checks']:
            path = field.get('path')
            registration = registered.get(path, {})
            if (path not in _PPTX_INDENTS or field.get('format') != 'pptx'
                or field.get('scenario') != 'configured_field' or 'native' not in field['dimensions']
                or registration.get('support') != 'implemented' or registration.get('editable') is not True
                or registration.get('semanticRole') != field.get('role')
                or requirement['id'] not in registration.get('requirementIds', [])
                or 'native' not in registration.get('evidenceDimensions', [])):
                continue
            checks = [(index, item) for index, item in indexed if item.get('path') == path]
            if not checks or not any(item.get('evidenceKind') == PPTX_INDENT_EVIDENCE for _, item in checks):
                continue
            failed = any(item.get('passed') is False for _, item in checks)
            complete = True
            for _, item in checks:
                actual, expected = item.get('actual'), item.get('expected')
                counts = item.get('evidenceObjects') or {}
                complete = complete and (item.get('evidenceKind') == PPTX_INDENT_EVIDENCE
                    and item.get('coverage') == 'complete' and item.get('passed') is True
                    and isinstance(actual, list) and isinstance(expected, list) and bool(actual)
                    and actual == expected and all(type(value) is int for value in [*actual, *expected])
                    and all(type(counts.get(key)) is int for key in ('nativeObjects', 'checkedNativeObjects', 'paragraphs'))
                    and counts['nativeObjects'] > 0 and counts['checkedNativeObjects'] == counts['nativeObjects']
                    and counts['paragraphs'] == len(actual))
            if not failed and not complete:
                continue
            evidence.append({'requirementId': requirement['id'], 'format': 'pptx', 'role': field['role'],
                'scenario': 'configured_field', 'path': path, 'dimension': 'native',
                'status': 'failed' if failed else 'passed', 'objectScope': 'complete' if complete else 'partial',
                'authorized': True, 'binding': deepcopy(runtime_binding), 'artifact': deepcopy(artifact),
                'sourceArtifact': {'format': 'pptx', 'role': 'artifact'}, 'readerGroup': PPTX_INDENT_EVIDENCE,
                'readbackCheckIndexes': [index for index, _ in checks],
                'message': '全部原生角色首行缩进逐段回读通过。' if complete else '原生角色首行缩进回读未通过。'})
    return evidence


def map_native_signature_evidence(result, contract, runtime_binding, retained):
    """只消费服务端reader结果与独立留存身份；总体passed不能替代逐项检查。"""
    binding = result.get('binding', {})
    if (binding.get('valid') is not True or binding.get('artifactAccessAuthorized') is not True
        or not _valid_binding(runtime_binding)
        or runtime_binding['contractHash'] != approval_contract_hash(contract)
        or type(result.get('draftVersion')) is not int or result['draftVersion'] != runtime_binding['draftVersion']
        or result.get('contentHash') != runtime_binding['draftHash']):
        return []
    evidence = []
    registered = {field['path']: field for field in contract.get('fields', [])}
    for requirement in contract['requirements']:
        if requirement['id'] != 'signature-content-and-layout':
            continue
        for field in requirement['checks']:
            format, path = field.get('format'), field.get('path')
            if (format not in ('md', 'word', 'pptx') or field.get('scenario') != 'configured_field'
                or field.get('role') != 'terminal_signature' or 'native' not in field['dimensions']
                or path not in {format + '.' + key for key in (
                    'common.signer', 'common.dateFormat', 'signature.description')}):
                continue
            registration = registered.get(path, {})
            if (registration.get('support') != 'implemented' or registration.get('editable') is not True
                or registration.get('semanticRole') != field['role']
                or requirement['id'] not in registration.get('requirementIds', [])
                or 'native' not in registration.get('evidenceDimensions', [])):
                continue
            entry = result.get('formats', {}).get(format, {})
            inline = entry.get('artifact') or {}
            reference = retained.get('formats', {}).get(format, {}).get('artifact') or {}
            artifact = {'sizeBytes': inline.get('size'), 'sha256': inline.get('sha256')}
            if (not _valid_artifact(artifact) or type(reference.get('size')) is not int
                or reference['size'] != artifact['sizeBytes'] or reference.get('sha256') != artifact['sha256']
                or any(issue.get('format') == format and issue.get('role') in (None, 'artifact')
                    for issue in retained.get('issues', []))):
                continue
            checks = [item for item in entry.get('readback', {}).get('checks', []) if item.get('path') == path]
            if not any(item.get('evidenceKind') == TERMINAL_SIGNATURE_CONTENT_EVIDENCE for item in checks):
                continue
            failed = any(item.get('passed') is False for item in checks)
            complete = all(item.get('coverage') == 'complete' for item in checks)
            if not failed and not (complete and all(item.get('passed') is True for item in checks)):
                continue
            evidence.append({'requirementId': requirement['id'], 'format': format,
                'role': field['role'], 'scenario': 'configured_field', 'path': path, 'dimension': 'native',
                'status': 'failed' if failed else 'passed', 'objectScope': 'complete' if complete else 'partial',
                'authorized': True, 'binding': deepcopy(runtime_binding),
                'sourceArtifact': {'format': format, 'role': 'artifact'}, 'artifact': artifact,
                'message': '严格末尾落款内容逐字段回读未通过。' if failed else '严格末尾落款内容逐字段回读通过。'})
    return evidence
