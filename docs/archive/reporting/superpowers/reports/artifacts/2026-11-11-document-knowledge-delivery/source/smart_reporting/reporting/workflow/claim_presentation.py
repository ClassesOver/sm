"""首次交付与新计算修订按当前授权复核解释状态。"""

import hashlib
import json
from functools import partial

import anyio
from loguru import logger

from ..trace.claim_presentation import claim_support_projection
from ..trace.contracts_v1 import RevisionTraceIndexV1, canonical_sha256
from ..trace.quality_bundle import evaluate_quality_bundle
from .runtime.business_evidence import resolve_runtime_knowledge


async def _registered_claim_support(runtime, run_context, manifest):
    scope = runtime._scope(run_context)

    async def read(file):
        if file.size > 16 * 1024 * 1024:
            raise ValueError('claim presentation source exceeds budget')
        data = await runtime.workspace_service.read_limited_regular_file(scope['threadId'], file.path, max_bytes=file.size)
        if len(data) != file.size or hashlib.sha256(data).hexdigest() != file.sha256:
            raise ValueError('claim presentation source identity changed')
        return data

    if manifest.trace_index is None:
        raise ValueError('claim presentation index unavailable')
    index = RevisionTraceIndexV1.model_validate_json(await read(manifest.trace_index))
    if (index.report_id != manifest.report_id or index.revision != manifest.revision
            or index.report_basis_id != manifest.report_basis_id):
        raise ValueError('claim presentation index mismatch')
    registered = next(file for file in index.files if file.resource_id == index.markdown_file_resource_id)
    if (registered.path, registered.size, registered.sha256) != (manifest.markdown.path, manifest.markdown.size, manifest.markdown.sha256):
        raise ValueError('claim presentation markdown mismatch')
    raw = await read(registered)
    sources, budget = {}, 64 * 1024 * 1024
    for file in index.files:
        budget -= file.size
        if budget < 0:
            raise ValueError('claim presentation inputs exceed budget')
        sources[file.resource_id] = await read(file)
    _, knowledge = await resolve_runtime_knowledge(runtime, run_context, index)
    quality = await anyio.to_thread.run_sync(partial(evaluate_quality_bundle, index, raw.decode(), sources,
        authorization_scope_hash=canonical_sha256({key: scope[key] for key in ('userId', 'threadId')}),
        knowledge_evidence=knowledge, heading_numbers=manifest.heading_numbers))
    return index, raw.decode(), quality.claim_support, knowledge


async def registered_claim_support_projection(runtime, run_context, manifest):
    index, _, supports, _ = await _registered_claim_support(runtime, run_context, manifest)
    return claim_support_projection(index, manifest.markdown.sha256, supports)


async def registered_native_claim_presentations(runtime, run_context, manifest):
    from ..trace.native_claims import native_claim_presentations

    index, markdown, supports, _ = await _registered_claim_support(runtime, run_context, manifest)
    return native_claim_presentations(index, markdown, supports)


async def registered_document_presentations(runtime, run_context, manifest):
    """同次身份/授权复核生成解释状态和知识附录，附录失败不丢已核验状态。"""
    from ..business_knowledge.claims import knowledge_source_entries, knowledge_source_presentations

    index, _, supports, knowledge = await _registered_claim_support(runtime, run_context, manifest)
    result = {'claimSupport': claim_support_projection(index, manifest.markdown.sha256, supports), 'traceSources': None}
    try:
        entries = knowledge_source_entries(knowledge_source_presentations(index, supports, knowledge),
            public_base_url=runtime.report_public_base_url, report_id=index.report_id, revision=index.revision)
        if entries:
            payload = {'claims': [], 'tables': [], 'charts': [], 'datasets': {}, 'knowledge': entries}
            if len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) > 16 * 1024:
                raise ValueError('knowledge source appendix exceeds budget')
            result['traceSources'] = payload
    except Exception as error:
        logger.warning('report_knowledge_source_projection_unavailable reason={}', type(error).__name__)
        result['sourceIssue'] = {'code': 'knowledge_source_projection_unavailable', 'status': 'unknown',
            'revision': manifest.revision, 'message': '业务知识来源无法核验，未附原文摘录，已保留下载。'}
    return result
