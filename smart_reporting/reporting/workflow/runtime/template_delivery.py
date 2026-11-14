"""报告模板交付；读取冻结稿，独立回读实际文件并保留失败产物。"""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any

from loguru import logger

from ...contract import ReportFileInput
from ...delivery.artifacts_v1 import ReportArtifactManifest
from ...delivery.office_engine import run_office_engine
from ...delivery.template_body import TEMPLATE_BODY_RESTORE_VERSIONS
from ...delivery.template_body_resources import bind_template_images, resource_issue
from ...delivery.templates import fill_report_template
from ..checkpoint import FileIdentity, ReportingCheckpoint
from ..state import ReportingCommand
from .reference_materials import REPORT_TEMPLATE_INPUT_STATE_KEY, _parse


def _file_identity(value: Any) -> FileIdentity:
    return FileIdentity.model_validate({key: value[key] for key in ("path", "size", "sha256")})


async def _existing_template_bytes(workspace, thread_id, path):
    """真实工作区先确认缺失；读取异常不能当作允许覆盖的缺失。"""
    if hasattr(workspace, 'apath_exists') and not await workspace.apath_exists(thread_id, path):
        return None
    try:
        content, _media = await workspace.afile_bytes(thread_id, path)
        return content
    except (FileNotFoundError, KeyError):
        return None


def _semantic_history_output(candidates, durable, request_identity, *, run_id, revision, delivery_format,
        restore_only=False):
    """只恢复当前全部输入重新算得的精确路径；判断记录损坏不能抹去已核产物。"""
    label = 'word' if delivery_format == 'docx' else delivery_format
    identities = [request_identity]
    if restore_only:
        identities.extend({**request_identity, 'bodyProjection': {
            **request_identity['bodyProjection'], 'version': version}}
            for version in TEMPLATE_BODY_RESTORE_VERSIONS)
    for candidate in candidates:
        try:
            if not isinstance(candidate, dict) or candidate.get('revision') != revision:
                continue
            readback = candidate['validation']['readback']
            semantic = readback['semanticSignature']
            if readback['format'] != delivery_format or semantic['status'] != 'resolved':
                continue
            file = FileIdentity(path=candidate[label + 'Path'], size=candidate[label + 'Size'], sha256=candidate[label + 'Sha256'])
            for base_identity in identities:
                identity = {**base_identity, 'signatureSemantics': {
                    'review': semantic['review'], 'preparedTemplateSha256': semantic['preparedTemplateSha256']}}
                digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                path = f'报表/智能分析/{run_id}/template/revision-{revision}/{digest[:20]}/report.{delivery_format}'
                if (file.path == path and readback['identity'] == file.model_dump()
                        and file.model_dump() in durable.payload.get('artifacts', ())):
                    return file, semantic
        except (KeyError, TypeError, ValueError):
            continue
    return None, None


def _template_signature_binding(binding, candidates, *, readback, frozen):
    """新生成回执来自绑定分支；历史文件不凭正文推断其模板槽。"""
    if binding is not None:
        return binding, []
    keys = ('placement', 'layoutSource', 'templateSampleStatus', 'undeclaredSamples', 'issueCodes')
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get('validation'), dict):
            continue
        validation = candidate['validation']
        previous = validation.get('readback')
        if not isinstance(previous, dict) or previous.get('ok') is not True:
            continue
        if any(previous.get(key) != readback.get(key)
                for key in ('identity', 'format', 'templateSha256', 'sourceContentSha256')):
            continue
        signature = previous.get('signature')
        if (not isinstance(signature, dict) or signature.get('bindingStatus') != 'recorded'
                or any(signature.get(key) != value for key, value in frozen.items())
                or any(key not in signature for key in keys)):
            continue
        if (signature['placement'] not in {'declared_template_slot', 'semantic_template_slot', 'body_end', 'declared_named_range',
                    'signature_sheet', 'declared_textbox', 'ending_slide'}
                or signature['layoutSource'] not in {'template', 'generated_fallback'}
                or signature['templateSampleStatus'] not in {'replaced', 'cleared', 'preserved_for_review', 'no_declared_slot'}
                or signature['undeclaredSamples'] != 'not_assessed'
                or not isinstance(signature['issueCodes'], list)
                or any(not isinstance(code, str) for code in signature['issueCodes'])):
            continue
        restored = {key: signature[key] for key in (*keys, 'sheetName', 'cellRange', 'slideNumber') if key in signature}
        retained = [{'code': issue['code'], 'message': issue['message']}
            for issue in validation.get('issues', ()) if isinstance(issue, dict)
            and issue.get('code') in signature['issueCodes'] and isinstance(issue.get('message'), str)]
        return restored, retained
    return None, []


async def _template_values(runtime, run_context, result, outline, delivery_format,
        *, durable=None, thread_id=None, report_id=None, output_root=None, basis_id=None,
        resource_identities=None):
    """只从本运行已登记、实际身份可核验的冻结成稿读取内容。"""
    thread_id = thread_id or runtime._scope(run_context)["threadId"]
    durable = durable or await runtime.state_repository.get(str(run_context.run_id))
    report_id = report_id or str(run_context.run_id)
    if delivery_format == "pptx" and not result.get("artifactManifest"):
        from ...hospital_operation.findings import FindingGraph
        from .slides import SlideOutline, build_slide_outline

        checkpoint = ReportingCheckpoint.model_validate(durable.payload["workflowCheckpoint"])
        manifest = checkpoint.evidence_manifest
        slide_file, graph_file = checkpoint.slide_outline_file, checkpoint.finding_graph_file
        if (checkpoint.revision != result["revision"] or manifest is None
                or slide_file is None or graph_file is None):
            raise ValueError("幻灯片模板缺少当前修订冻结证据")
        slides = await runtime._read_identity_model(thread_id, slide_file, SlideOutline)
        graph = await runtime._read_identity_model(thread_id, graph_file, FindingGraph)
        facts = {key: await runtime._read_identity_bytes(thread_id, file, max_bytes=file.size)
            for key, file in checkpoint.deterministic_fact_files.items()}
        if (slides.snapshot_hash != checkpoint.finding_graph_hash
                or graph.snapshot_hash != checkpoint.finding_graph_hash
                or slides != build_slide_outline(graph, manifest, title=outline.title,
                    fact_contents=facts, analysis_summaries=slides.analysis_summaries)):
            raise ValueError("幻灯片模板正文与冻结证据不一致")
        paragraphs = [text for slide in slides.slides for text in (slide.title, *slide.bullets)]
        paragraphs.extend(block.markdown for summary in slides.analysis_summaries for block in summary.blocks)
        return {"report_title": outline.title, "report_content": "\n\n".join(paragraphs)}, slide_file, {}, []
    registered = {_file_identity(item).path: _file_identity(item)
        for item in durable.payload.get("artifacts", ())}
    manifest_file = _file_identity(result["artifactManifest"])
    if output_root is not None and not PurePosixPath(manifest_file.path).is_relative_to(output_root):
        raise ValueError("模板成稿清单不属于本执行目录")
    if registered.get(manifest_file.path) != manifest_file:
        raise ValueError("模板成稿清单未登记到当前运行")
    manifest = await runtime._read_identity_model(thread_id, manifest_file, ReportArtifactManifest)
    if (manifest.report_id != report_id or manifest.revision != result["revision"]
            or manifest.markdown.path != result["markdownPath"]
            or basis_id is not None and manifest.report_basis_id != basis_id):
        raise ValueError("模板成稿身份与当前报告修订不一致")
    markdown_file = _file_identity(manifest.markdown.model_dump())
    if output_root is not None and not PurePosixPath(markdown_file.path).is_relative_to(output_root):
        raise ValueError("模板成稿正文不属于本执行目录")
    if registered.get(markdown_file.path) != markdown_file:
        raise ValueError("模板成稿正文未登记到当前运行")
    raw = await runtime._read_identity_bytes(thread_id, markdown_file, max_bytes=markdown_file.size)
    markdown = raw.decode('utf-8')
    resources, issues = {}, []
    if delivery_format in {'docx', 'pdf'}:
        bindings, issues = bind_template_images(markdown, markdown_file.path,
            [item.model_dump() for item in manifest.charts])
        if resource_identities is not None:
            resource_identities.update({source: {key: identity[key] for key in ('size', 'sha256')}
                for source, identity in bindings.items()})
        for source, identity in bindings.items():
            try:
                file = _file_identity(identity)
                if registered.get(file.path) != file:
                    raise ValueError('template image not registered to this run')
                resources[source] = await runtime._read_identity_bytes(thread_id, file, max_bytes=file.size)
            except Exception:
                logger.warning('report_template_body_resource_read_failed')
                issues.append(resource_issue())
    return {"report_title": outline.title, "report_content": markdown}, markdown_file, resources, issues


async def render_template_delivery(
    runtime,
    run_context,
    result: dict[str, Any],
    outline,
    delivery_format: str,
    *,
    execution=None,
    restore_only: bool = False,
) -> dict[str, Any]:
    """生成单个目标文件；布局未验收时保持明确失败状态和可读实际身份。

    新修订与政策采纳只使用其耐久冻结材料，不读取原运行的会话模板状态。
    """
    state = runtime._state(run_context)
    thread_id = runtime._scope(run_context)["threadId"]
    result = dict(result)
    previous_result = state.get('report_workflow_result')
    issues = []
    path = None
    generated = None
    readback = {"ok": False}
    label = "word" if delivery_format == "docx" else delivery_format
    target_context, execution_options = run_context, {}
    for other in ("pdf", "word", "xlsx", "pptx"):
        for suffix in ("Path", "Size", "Sha256"):
            result.pop(f"{other}{suffix}", None)
    try:
        if execution is None:
            registered_template = ReportFileInput.model_validate(
                state[REPORT_TEMPLATE_INPUT_STATE_KEY]["identity"])
            if registered_template != runtime._envelope(run_context).template_input:
                raise ValueError("模板登记与本次请求不一致")
            durable = await runtime.state_repository.get(str(run_context.run_id))
            materials = durable.payload.get("requestMaterials")
            if materials is not None and registered_template != ReportFileInput.model_validate(materials["templateInput"]):
                raise ValueError("模板身份与耐久冻结材料不一致")
            run_id, report_id, output_root, basis_id = str(run_context.run_id), str(run_context.run_id), None, None
        else:
            from ..policy_adoption import (
                PolicyAdoptionExecution,
                policy_adoption_run_context,
                require_policy_adoption_execution,
            )
            from ..revision_execution import require_revision_execution

            if isinstance(execution, PolicyAdoptionExecution):
                durable = await require_policy_adoption_execution(runtime, run_context, execution)
                target_context = policy_adoption_run_context(execution)
                run_id = report_id = execution.scope.run_id
                thread_id = execution.scope.workspace_key
            else:
                durable = await require_revision_execution(runtime, run_context, execution, revision=result["revision"])
                run_id, report_id = execution.execution_run_id, execution.source_scope.run_id
                thread_id = execution.source_scope.workspace_key
                execution_options = {"execution": execution}
            if execution.requested_outputs != (delivery_format,) or result["revision"] != execution.output_revision:
                raise ValueError("模板目标与已登记修订交付格式不一致")
            registered_template = ReportFileInput.model_validate(durable.payload["requestMaterials"]["templateInput"])
            output_root, basis_id = PurePosixPath(f"报表/智能分析/{run_id}"), execution.basis_id
        template_file = _file_identity(registered_template.model_dump())
        raw = await runtime._read_identity_bytes(thread_id, template_file, max_bytes=template_file.size)
        resource_identities = {}
        values, source_file, body_resources, resource_issues = await _template_values(runtime, run_context, result, outline, delivery_format,
            durable=durable, thread_id=thread_id, report_id=report_id, output_root=output_root, basis_id=basis_id,
            resource_identities=resource_identities)
        template_format = PurePosixPath(registered_template.filename).suffix.lower().lstrip(".")
        signature = None
        if template_format in {'docx', 'xlsx', 'pptx'}:
            from ....preferences.markdown_adapter import strip_signature
            from ....preferences.runtime import (
                REPORT_CONFIGURATION_SNAPSHOT_KEY,
                execution_preferences,
            )
            from ....preferences.workbook_adapter import displayed_date

            configuration = (state.get(REPORT_CONFIGURATION_SNAPSHOT_KEY) if execution is None
                else await execution_preferences(runtime, execution))
            if configuration is not None:
                resolved = configuration['resolvedFormats']['pdf' if delivery_format == 'pdf' and template_format == 'docx'
                    else 'word' if template_format == 'docx' else template_format]
                signature = {'signer': resolved['common']['signer'],
                    'date': displayed_date(configuration['generatedDate'], resolved['common']['dateFormat']),
                    'description': resolved['signature']['description']}
                values = {**values, 'report_content': strip_signature(values['report_content'])}

        request_identity = {"template": template_file.model_dump(),
            "source": source_file.model_dump(), "values": values, "format": delivery_format,
            **({"signature": signature} if signature is not None else {})}
        legacy_hash = hashlib.sha256(json.dumps(request_identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if template_format == 'docx':
            from ...delivery.template_body import TEMPLATE_BODY_VERSION

            issues.extend(resource_issues)
            request_identity['bodyProjection'] = {'version': TEMPLATE_BODY_VERSION,
                'resources': resource_identities}
        semantic_receipt = None
        prepared_template = raw
        if template_format == 'docx' and signature is not None:
            from .template_semantics import prepare_runtime_signature

            base_hash = hashlib.sha256(json.dumps(request_identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            base_path = f'报表/智能分析/{run_id}/template/revision-{result["revision"]}/{base_hash[:20]}/report.{delivery_format}'
            baseline_exists = (any(item.get('path') == base_path for item in durable.payload.get('artifacts', ()))
                or bool(await _existing_template_bytes(runtime.workspace_service, thread_id, base_path)))
            if not baseline_exists:
                prepared_template, semantic_receipt, semantic_issues = await prepare_runtime_signature(runtime, target_context, raw,
                    durable=durable, run_id=run_id, thread_id=thread_id, target_context=target_context,
                    execution_options=execution_options, allow_review=not restore_only)
                issues.extend(semantic_issues)
            if semantic_receipt is not None and semantic_receipt['status'] == 'resolved':
                request_identity['signatureSemantics'] = {
                    'review': semantic_receipt['review'],
                    'preparedTemplateSha256': semantic_receipt['preparedTemplateSha256']}
        request_hash = hashlib.sha256(json.dumps(request_identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        path = (f"报表/智能分析/{run_id}/template/revision-{result['revision']}/"
            f"{request_hash[:20]}/report.{delivery_format}")
        registered_output = next((_file_identity(item) for item in durable.payload.get("artifacts", ())
            if item.get("path") == path), None)
        if (registered_output is None and template_format == 'docx' and signature is not None
            and not await _existing_template_bytes(runtime.workspace_service, thread_id, path)):
            recovered, prior_semantic = _semantic_history_output(
                [previous_result, durable.payload.get('result', {}).get('renderedTemplate')],
                durable, request_identity, run_id=run_id, revision=result['revision'], delivery_format=delivery_format,
                restore_only=restore_only)
            if recovered is not None:
                registered_output, path = recovered, recovered.path
                if semantic_receipt is None:
                    semantic_receipt = {**prior_semantic, 'currentReviewStatus': 'unavailable'}
        restored_legacy = False
        if restore_only and registered_output is None and template_format == 'docx':
            current_content = await _existing_template_bytes(runtime.workspace_service, thread_id, path)
            if not current_content:
                # 旧投影和原literal路径均由同一冻结身份精确计算；不扫描可读路径。
                previous_hashes = []
                for version in TEMPLATE_BODY_RESTORE_VERSIONS:
                    previous_identity = {**request_identity, 'bodyProjection': {
                        **request_identity['bodyProjection'], 'version': version}}
                    previous_hashes.append((hashlib.sha256(json.dumps(previous_identity,
                        ensure_ascii=False, sort_keys=True).encode()).hexdigest(), False))
                for candidate_hash, literal in (*previous_hashes, (legacy_hash, True)):
                    candidate = (f"报表/智能分析/{run_id}/template/revision-{result['revision']}/"
                        f"{candidate_hash[:20]}/report.{delivery_format}")
                    registered = next((_file_identity(item) for item in durable.payload.get('artifacts', ())
                        if item.get('path') == candidate), None)
                    if registered is not None:
                        registered_output, path, restored_legacy = registered, candidate, literal
                        break
                    candidate_content = await _existing_template_bytes(runtime.workspace_service, thread_id, candidate)
                    if candidate_content:
                        path, restored_legacy = candidate, literal
                        break
        modified_parts, signature_binding = [], None
        if registered_output is not None:
            actual = registered_output
        else:
            existing = await _existing_template_bytes(runtime.workspace_service, thread_id, path)
            if existing:
                actual = FileIdentity(path=path, size=len(existing), sha256=hashlib.sha256(existing).hexdigest())
                issues.append({"code": "report_template_registration_unavailable",
                    "message": "恢复了当前模板和冻结稿对应路径的实际文件，原耐久登记缺失，未标记验收通过。"})
            else:
                if restore_only:
                    raise ValueError("模板尚无可恢复实际文件")
                filled = await run_office_engine(fill_report_template, prepared_template,
                    template_format=template_format, delivery_format=delivery_format, values=values,
                    **({'body_resources': body_resources} if template_format == 'docx' else {}),
                    **({"signature": signature} if signature is not None else {}))
                issues.extend(filled.issues)
                modified_parts = list(filled.modified_parts)
                signature_binding = filled.signature_binding
                if (signature_binding is not None and semantic_receipt is not None
                        and semantic_receipt['status'] == 'resolved'
                        and signature_binding.get('placement') == 'declared_template_slot'):
                    signature_binding = {**signature_binding, 'placement': 'semantic_template_slot'}
                generated = filled.content
                actual = await runtime._write_immutable_artifact(thread_id, path, generated)
        stored = await runtime._read_identity_bytes(thread_id, actual, max_bytes=actual.size)
        result.update({f"{label}Path": actual.path, f"{label}Size": actual.size,
            f"{label}Sha256": actual.sha256})
        try:
            parsed = await run_office_engine(_parse, SimpleNamespace(
                filename=f"report.{delivery_format}", content=stored))
            text = "".join(parsed["content"].split())
            if delivery_format == 'docx':
                import io

                from docx import Document

                document = Document(io.BytesIO(stored))
                # python-docx 的 paragraphs 不包含正文内容控件内的段落。
                text = ''.join(''.join(document._element.body.xpath('.//w:t/text()')).split())
            required = [values['report_title'], *((signature or {}).values())]
            body = None
            if template_format == 'docx' and not restored_legacy:
                from ...delivery.template_body_readback import (
                    expected_body_text,
                    read_template_body,
                )

                if delivery_format == 'docx':
                    try:
                        body = await run_office_engine(read_template_body, stored, values['report_content'], body_resources,
                            original=prepared_template, report_title=values['report_title'])
                    except Exception as error:
                        logger.warning('report_template_body_readback_failed error_type={}', type(error).__name__)
                        body = {'status': 'failed', 'coverage': 'unverified', 'issues': [{
                            'code': 'report_template_readback_failed',
                            'message': '正文独立回读不可用，实际模板文件仍保留供核对与下载。'}]}
                    issues.extend(body['issues'])
                else:
                    required.append(expected_body_text(values['report_content']))
                    body = {'status': 'sampled', 'coverage': 'sample', 'issues': [],
                        'layoutValidation': 'unverified'}
            else:
                required.append(values['report_content'])
                if restored_legacy:
                    body = {'status': 'unverified', 'coverage': 'unverified',
                        'representation': 'historical_literal_markdown', 'issues': []}
            if any("".join(value.split()) not in text for value in required if value):
                raise ValueError("实际模板输出未包含完整的冻结标题或正文")
            readback = {"ok": body is None or body['status'] in {'passed', 'sampled'} or restored_legacy,
                "format": delivery_format, "identity": actual.model_dump(),
                "templateSha256": template_file.sha256, "sourceContentSha256": source_file.sha256,
                "modifiedParts": modified_parts, 'templateLayout': {'source': 'uploaded_template',
                    'scope': ('outside_semantic_and_declared_binding_targets'
                        if semantic_receipt is not None and semantic_receipt['status'] == 'resolved'
                        else 'outside_declared_binding_targets'), 'globalDefaults': 'not_applied',
                    'layoutValidation': 'unverified'}}
            if body is not None:
                readback['body'] = body
            if semantic_receipt is not None:
                readback['semanticSignature'] = semantic_receipt
            if signature is not None:
                frozen = {'source': 'frozen_run_preferences', 'configurationHash': configuration.get('contentHash'),
                    'contentSha256': hashlib.sha256(json.dumps(signature, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                    'generatedDate': configuration['generatedDate']}
                try:
                    binding, binding_issues = _template_signature_binding(signature_binding,
                        [result, previous_result, durable.payload.get('result', {}).get('renderedTemplate')],
                        readback=readback, frozen=frozen)
                    issues.extend(binding_issues)
                except Exception as error:
                    logger.warning('report_template_binding_receipt_failed error_type={}', type(error).__name__)
                    binding = None
                if binding is None:
                    issue = {'code': 'report_template_binding_receipt_unavailable',
                        'message': '模板实际文件身份可读，但缺少匹配的落款位置来源回执，未推断位置或样例清理状态；文件仍可下载。'}
                    issues.append(issue)
                    binding = {'placement': 'unverified', 'layoutSource': 'unverified',
                        'templateSampleStatus': 'not_assessed', 'undeclaredSamples': 'not_assessed',
                        'issueCodes': [issue['code']], 'bindingStatus': 'unavailable'}
                else:
                    binding = {**binding, 'bindingStatus': 'recorded'}
                readback['signature'] = {**frozen, **binding}
        except Exception as error:
            logger.warning("report_template_readback_failed error_type={}", type(error).__name__)
            issues.append({"code": "report_template_readback_failed",
                "message": "模板实际文件回读未能确认完整冻结内容，已保留文件供核对。"})
        try:
            await runtime._apply_durable_command(target_context, ReportingCommand(name="record_artifact",
                commandId=f"rendered-template:{result['revision']}:{actual.sha256}",
                payload={"artifact": actual.model_dump(mode="json", by_alias=True)}), **execution_options)
        except Exception as error:
            logger.warning("report_template_checkpoint_failed error_type={}", type(error).__name__)
            issues.append({"code": "report_template_checkpoint_failed",
                "message": "模板文件已生成，但耐久产物登记未确认，实际可读文件已保留。"})
        issues.append({"code": "report_template_layout_unverified",
            "message": "模板已按占位符填充并保留其他对象；版式、保留内容及图表布局需独立复核，未标记验收通过。"})
    except Exception as error:
        logger.warning("report_template_generation_failed error_type={}", type(error).__name__)
        issues.append({"code": "report_template_generation_failed",
            "message": "模板身份、冻结稿或生成步骤未能核验，未改用其他格式交付。"})
        if path is not None and generated is not None:
            try:
                stored, _media = await runtime.workspace_service.afile_bytes(thread_id, path)
                if stored == generated:
                    result.update({f"{label}Path": path, f"{label}Size": len(stored),
                        f"{label}Sha256": hashlib.sha256(stored).hexdigest()})
            except Exception:
                pass
    result.update({"status": "validation_failed", "deliveryFormat": delivery_format,
        "validation": {"ok": False, "issues": issues, "readback": readback},
        "validationIssues": issues})
    if execution is None:
        state["report_workflow_result"] = result
    return result
