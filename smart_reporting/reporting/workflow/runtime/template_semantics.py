"""模板语义判断的既有工作区冻结桥；历史只读，不另建持久化体系。"""

import hashlib
import json
from contextlib import nullcontext

from loguru import logger

from ...delivery.office_engine import run_office_engine
from ...delivery.template_signature_semantics import (
    bind_semantic_signature_slot,
    inspect_signature_candidates,
)
from ...template_semantic_review import native_record, semantic_issue, validate_frozen_review
from ..checkpoint import FileIdentity
from ..state import ReportingCommand


def semantic_review_path(run_id, raw):
    return f'报表/智能分析/{run_id}/template/semantics/{hashlib.sha256(raw).hexdigest()}/signature-v1.json'


def semantic_review_reference(record):
    content = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return {'version': 1, 'ruleVersion': record['ruleVersion'], 'templateSha256': record['templateSha256'],
        'recordSha256': hashlib.sha256(content).hexdigest()}


async def load_frozen_template_review(workspace, *, thread_id, run_id, raw, artifacts):
    """只读取当前材料运行登记的精确文件；未登记文件不能授权语义改写。"""
    path = semantic_review_path(run_id, raw)
    matches = [item for item in artifacts if isinstance(item, dict) and item.get('path') == path]
    if not matches:
        return None
    # artifacts可能包含同一身份的重复登记，不接受相同路径的冲突身份。
    identities = [FileIdentity.model_validate(item) for item in matches]
    identity = identities[0]
    if any(item != identity for item in identities) or identity.size > 512 * 1024:
        raise ValueError('语义冻结文件身份不唯一或超限')
    content, _ = await workspace.afile_bytes(thread_id, path)
    if len(content) != identity.size or hashlib.sha256(content).hexdigest() != identity.sha256:
        raise ValueError('语义冻结文件实际身份变化')
    return validate_frozen_review(raw, json.loads(content))


async def freeze_template_review(runtime, run_context, raw, *, durable, run_id, thread_id,
        target_context, execution_options, allow_review):
    """复用现有跨进程锁；锁内重读，不能用调用前快照覆盖已登记判断。"""
    try:
        lock = getattr(runtime.state_repository, 'workflow_thread_lifecycle_lock', None)
        key = f'template-signature:{run_id}:{hashlib.sha256(raw).hexdigest()}'
        async with lock(key) if lock is not None else nullcontext():
            current = await runtime.state_repository.get(run_id)
            return await _freeze_template_review(runtime, run_context, raw,
                durable=current, run_id=run_id, thread_id=thread_id, target_context=target_context,
                execution_options=execution_options, allow_review=allow_review)
    except Exception as error:
        logger.warning('template_signature_freeze_lock_unavailable error_type={}', type(error).__name__)
        return None, [semantic_issue('unavailable')]


async def _freeze_template_review(runtime, run_context, raw, *, durable, run_id, thread_id,
        target_context, execution_options, allow_review):
    """先耐久保存并读回登记，再允许消费者使用；失败退回保留原文。"""
    try:
        if inspect_signature_candidates(raw)['declared']:
            return None, []
        record = await load_frozen_template_review(runtime.workspace_service, thread_id=thread_id,
            run_id=run_id, raw=raw, artifacts=durable.payload.get('artifacts', ()))
        if record is not None:
            return record, []
        if not allow_review or getattr(runtime, 'template_signature_reviewer', None) is None:
            return None, [semantic_issue('unavailable')]
        path = semantic_review_path(run_id, raw)
        if await runtime.workspace_service.apath_exists(thread_id, path):
            # 前次写入后登记失败或并发未完成，不能覆盖，也不能再次询问后采用另一个判断。
            raise ValueError('语义记录已有未登记文件')
        record = validate_frozen_review(raw,
            await runtime.template_signature_reviewer.review(raw, run_context=run_context))
        content = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        identity = await runtime._write_immutable_artifact(thread_id, path, content)
        await runtime._apply_durable_command(target_context, ReportingCommand(name='record_artifact',
            commandId=f'template-signature-semantic:{identity.sha256}',
            payload={'artifact': identity.model_dump(mode='json', by_alias=True)}), **execution_options)
        saved = await runtime.state_repository.get(run_id)
        loaded = await load_frozen_template_review(runtime.workspace_service, thread_id=thread_id,
            run_id=run_id, raw=raw, artifacts=saved.payload.get('artifacts', ()))
        if loaded != record:
            raise ValueError('语义冻结登记未确认')
        return loaded, []
    except Exception as error:
        logger.warning('template_signature_freeze_unavailable error_type={}', type(error).__name__)
        return None, [semantic_issue('unavailable')]


def prepare_semantic_template(raw, record):
    """明确声明不被模型覆盖；坏历史记录只告警，仍用原模板生成。"""
    try:
        if inspect_signature_candidates(raw)['declared']:
            return raw, None, []
        if record is None:
            return raw, None, [semantic_issue('unavailable')]
        record = validate_frozen_review(raw, record)
        if record['status'] != 'resolved':
            return raw, {'status': record['status'], 'templateSha256': record['templateSha256']}, [semantic_issue(record['status'])]
        prepared, receipt = bind_semantic_signature_slot(raw, native_record(record))
        return prepared, receipt, [semantic_issue('resolved')]
    except Exception as error:
        logger.warning('template_signature_prepare_unavailable error_type={}', type(error).__name__)
        return raw, None, [semantic_issue('unavailable')]


async def prepare_runtime_signature(runtime, run_context, raw, **binding):
    """预处理和独立回读都可失败；这类失败只放弃语义改写。"""
    try:
        record, issues = await freeze_template_review(runtime, run_context, raw, **binding)
        prepared, receipt, more = prepare_semantic_template(raw, record)
        issues.extend(issue for issue in more if issue not in issues)
        if receipt is not None:
            receipt['review'] = semantic_review_reference(record)
        if receipt is not None and receipt['status'] == 'resolved':
            from ...delivery.template_signature_readback import read_semantic_preparation

            independent = await run_office_engine(read_semantic_preparation, raw, prepared, record, receipt)
            receipt['preparationReadback'] = independent
            if independent['status'] != 'passed' or independent['coverage'] != 'complete':
                issues.extend(independent['issues'])
                issues.append(semantic_issue('unavailable'))
                prepared = raw
                receipt['status'] = 'unavailable'
        return prepared, receipt, issues
    except Exception as error:
        logger.warning('template_signature_runtime_unavailable error_type={}', type(error).__name__)
        return raw, None, [semantic_issue('unavailable')]
