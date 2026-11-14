"""编辑器模板来源白名单；来源缺失只能告警，不影响实际产物签发。"""

from collections.abc import Mapping
from datetime import date
from typing import Annotated, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

Digest = Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
Source = Literal['frozen_revision_preferences', 'editor_design', 'editor_reset', 'unavailable']


class _Identity(BaseModel):
    model_config = ConfigDict(strict=True)
    size: Annotated[int, Field(ge=0)]
    sha256: Digest


class _Template(_Identity):
    filename: Annotated[str, Field(min_length=1, max_length=255)]

    @field_validator('filename')
    @classmethod
    def safe_filename(cls, value):
        if value in {'.', '..'} or any(char in value for char in '/\\') or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError('模板摘要只接受文件名')
        return value


class _Entry(BaseModel):
    model_config = ConfigDict(strict=True)
    artifact: _Identity
    layoutSource: Literal['uploaded_template']
    signatureSource: Literal['frozen_revision_preferences', 'unavailable']
    generatedDate: str | None
    dateFormatSource: Source
    descriptionSource: Source
    placement: Literal['declared_template_slot', 'semantic_template_slot', 'body_end', 'unverified']
    signatureLayoutSource: Literal['template', 'generated_fallback', 'unverified']
    templateSampleStatus: Literal['replaced', 'cleared', 'preserved_for_review', 'no_declared_slot', 'not_assessed']
    signatureReadback: Literal['passed', 'failed', 'unverified']
    bodyReadback: Literal['structure_verified', 'sample_only', 'unverified']

    @field_validator('generatedDate')
    @classmethod
    def frozen_date(cls, value):
        if value is not None and date.fromisoformat(value).isoformat() != value:
            raise ValueError('冻结日期必须为 ISO 日期')
        return value


class _Summary(BaseModel):
    model_config = ConfigDict(strict=True)
    version: Literal[1]
    template: _Template
    contentSha256: Digest
    layoutValidation: Literal['unverified']
    undeclaredSamples: Literal['not_assessed']
    previewSourceFormat: Literal['word'] | None = None
    formats: dict[Literal['word', 'pdf'], _Entry]

    @field_validator('version', mode='before')
    @classmethod
    def actual_version(cls, value):
        if type(value) is not int:
            raise ValueError('来源版本必须为整数')
        return value


def unavailable_issue():
    return {'code': 'report_editor_layout_provenance_unavailable',
        'message': '模板来源摘要未能核验；已生成文件仍可下载，请核对实际内容和版式。'}


def build_template_provenance(*, job, configuration, template, content_sha256, identities, bindings, readbacks):
    """仅记实际生成分支；完整布局和无标记样例一律不推定通过。"""
    preferences = job.get('_formatPreferences') or (configuration or {}).get('resolvedFormats', {})
    generated = job.get('_documentContext', {}).get('generatedDate') or (configuration or {}).get('generatedDate')
    overrides = job.get('_reportDesign') or {}
    entries = {}
    for format, identity in identities.items():
        available = bool(preferences.get(format) and generated)
        signature = overrides.get('signature', {})

        def source(field):
            if not available:
                return 'unavailable'
            if 'signature' in overrides and signature is None:
                return 'editor_reset'
            return 'editor_design' if field in signature else 'frozen_revision_preferences'

        binding = bindings.get(format) or {}
        detail = (readbacks.get(format) or {}).get('templateReadback', {})
        body = detail.get('body', {})
        native = body.get('status') == 'passed' and body.get('coverage') == 'complete'
        sample = body.get('status') == 'sampled' and body.get('coverage') == 'sample'
        entries[format] = {'artifact': identity, 'layoutSource': 'uploaded_template',
            'signatureSource': 'frozen_revision_preferences' if available else 'unavailable',
            'generatedDate': generated if available else None,
            'dateFormatSource': source('dateFormat'), 'descriptionSource': source('description'),
            'placement': binding.get('placement', 'unverified'),
            'signatureLayoutSource': binding.get('layoutSource', 'unverified'),
            'templateSampleStatus': binding.get('templateSampleStatus', 'not_assessed'),
            'signatureReadback': detail.get('signature', {}).get('status', 'unverified'),
            'bodyReadback': 'structure_verified' if native else 'sample_only' if sample else 'unverified'}
    return _Summary.model_validate({'version': 1, 'template': template, 'contentSha256': content_sha256,
        'layoutValidation': 'unverified', 'undeclaredSamples': 'not_assessed', 'formats': entries}
        ).model_dump(exclude={'previewSourceFormat'})


def _project(validation, identities):
    summary = _Summary.model_validate(validation['layoutProvenance'])
    if summary.contentSha256 != validation.get('sourceContentSha256'):
        raise ValueError('正文来源摘要不匹配')
    for format in list(summary.formats):
        identity = identities.get(format)
        if identity is None:
            del summary.formats[format]
        elif summary.formats[format].artifact != _Identity.model_validate(identity):
            raise ValueError('产物来源身份不匹配')
    if not summary.formats:
        raise ValueError('没有本次可下载格式的来源')
    if validation.get('previewSourceFormat') == 'word':
        summary.previewSourceFormat = 'word'
    return summary.model_dump(exclude={'previewSourceFormat'} if summary.previewSourceFormat is None else set())


def public_validation(validation, identities, *, fallback=None):
    """导出、重试及预览统一投影；不返回内部路径、作用域或完整reader。"""
    result = {'ok': False, 'issues': []}
    try:
        validation = {} if validation is None else validation
        fallback = {} if fallback is None else fallback
        if not isinstance(validation, Mapping) or not isinstance(fallback, Mapping):
            raise ValueError('历史验收回执结构损坏')
        issues = validation.get('issues') or []
        if not isinstance(issues, (list, tuple)):
            raise ValueError('历史验收告警结构损坏')
        for issue in issues:
            if not isinstance(issue, Mapping):
                raise ValueError('历史验收告警结构损坏')
            result['issues'].append({key: issue[key] for key in ('code', 'message')
                if isinstance(issue.get(key), str)})
        result['ok'] = validation.get('ok') is True
        # 旧交付回执可能只含当时保存成功的一种格式；重试应从完整原始回执重新筛选。
        source = {**validation, **fallback} if 'layoutProvenance' in fallback else validation
        if 'layoutProvenance' not in source:
            return result
        result['layoutProvenance'] = _project(source, identities)
    except Exception as error:
        logger.warning('editor_layout_provenance_unavailable error_type={}', type(error).__name__)
        result['ok'] = False
        result['issues'].append(unavailable_issue())
    return result
