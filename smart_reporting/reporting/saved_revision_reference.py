"""刷新任务拥有的已保存参考；只用于理解文件，不能登记业务事实。"""
import hashlib
from typing import Literal

from pydantic import Field, model_serializer, model_validator

from .contract import SHA256_PATTERN, ReportFileInput, StrictModel
from .models import ReportingError

BINARY_MEDIA = {
    'pdf': 'application/pdf',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
}


class NativeRevisionSelection(StrictModel):
    """服务器从已认证 native 修订恢复，不能用原报告身份代替分支身份。"""
    document_id: str = Field(alias='documentId', min_length=1, max_length=256)
    revision: int = Field(ge=1)
    context_sha256: str = Field(alias='contextSha256', pattern=SHA256_PATTERN)
    format: Literal['pdf', 'docx']


class OfficeReportSource(StrictModel):
    """服务端耐久保存的原正式来源指针，不包含人工改值。"""
    workflow_run_id: str = Field(alias='workflowRunId', min_length=1)
    report_id: str = Field(alias='reportId', min_length=1)
    revision: int = Field(ge=1)
    context_sha256: str = Field(alias='contextSha256', pattern=SHA256_PATTERN)


class OfficeRevisionSelection(StrictModel):
    editor: Literal['workbook', 'slides']
    revision: int = Field(ge=1)
    context_sha256: str = Field(alias='contextSha256', pattern=SHA256_PATTERN)
    format: Literal['xlsx', 'pptx']
    calculation_source: OfficeReportSource = Field(alias='calculationSource')

    @model_validator(mode='after')
    def editor_format(self):
        if self.format != {'workbook': 'xlsx', 'slides': 'pptx'}[self.editor]:
            raise ValueError('Office 保存来源与编辑器格式不一致')
        return self


class SavedRevisionReference(StrictModel):
    task_id: str = Field(alias='taskId', pattern=r'^recalc-[0-9a-f]{32}$')
    context_sha256: str = Field(alias='contextSha256', pattern=SHA256_PATTERN)
    source: Literal['markdown_editor', 'native_editor', 'workbook_editor', 'slides_editor'] = 'markdown_editor'
    native_source: NativeRevisionSelection | None = Field(default=None, alias='nativeSource')
    office_source: OfficeRevisionSelection | None = Field(default=None, alias='officeSource')
    workflow_run_id: str = Field(alias='workflowRunId', min_length=1)
    report_id: str = Field(alias='reportId', min_length=1)
    revision: int = Field(ge=1)
    format: Literal['md', 'pdf', 'docx', 'xlsx', 'pptx'] = 'md'
    file: ReportFileInput
    role: Literal['reference'] = 'reference'
    business_facts_allowed: Literal[False] = Field(default=False, alias='businessFactsAllowed')

    @model_serializer(mode='wrap')
    def legacy_serialization(self, handler):
        payload = handler(self)
        if self.native_source is None:
            payload.pop('nativeSource', None)
            payload.pop('native_source', None)
        if self.office_source is None:
            payload.pop('officeSource', None)
            payload.pop('office_source', None)
        return payload

    @model_validator(mode='after')
    def owned_snapshot(self):
        media = {'md': 'text/markdown', **BINARY_MEDIA}
        selection = self.native_source or self.office_source
        expected_source = ('native_editor' if self.native_source else
            self.office_source.editor + '_editor' if self.office_source else 'markdown_editor')
        if (self.native_source is not None and self.office_source is not None
                or self.source != expected_source
                or self.format != (selection.format if selection is not None else 'md')):
            raise ValueError('保存参考格式与明确来源选择不一致')
        if self.office_source is not None and (self.office_source.revision != self.revision
                or self.office_source.context_sha256 != self.context_sha256):
            raise ValueError('Office 参考必须绑定当前保存修订')
        if (not self.file.path.endswith(f'/editor-inputs/{self.task_id}/current.{self.format}')
                or self.file.filename != f'current.{self.format}' or self.file.media_type != media[self.format]):
            raise ValueError('保存参考必须属于任务派生的不可变副本')
        return self

    def require_context(self, context, task_id):
        if (self.task_id != task_id or self.context_sha256 != context.digest()
                or self.workflow_run_id != context.workflow_run_id or self.report_id != context.report_id
                or self.revision != context.revision
                or self.file.path != snapshot_path(context, task_id, self.format)):
            raise ReportingError('report_editor_scope_mismatch', '保存参考不属于当前报告任务。')


class SavedRevisionExecutionBinding(StrictModel):
    task_id: str = Field(alias='taskId', pattern=r'^recalc-[0-9a-f]{32}$')
    input_hash: str = Field(alias='inputHash', pattern=SHA256_PATTERN)
    context_sha256: str = Field(alias='contextSha256', pattern=SHA256_PATTERN)
    reference: SavedRevisionReference


def snapshot_path(context, task_id, format="md"):
    return context.markdown_path.rsplit('/', 1)[0] + f'/editor-inputs/{task_id}/current.{format}'


async def freeze_saved_revision_reference(editor, context, task_id, request):
    from .workflow.runtime.analysis import RuntimeAnalysisMixin

    path, _, _ = await editor._read_revision_markdown(context)
    # 读取实际文件字节，不能让文本解码/换行转换替代保存身份。
    raw = await editor.workspace.read_limited_regular_file(context.scope['threadId'], path, max_bytes=50 * 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != request.expected_sha256:
        raise ReportingError('report_editor_conflict', '已保存正文发生变化，请保存并核对后重新发起。')
    artifacts = RuntimeAnalysisMixin()
    artifacts.workspace_service = editor.workspace
    identity = await artifacts._write_immutable_artifact(context.scope['threadId'], snapshot_path(context, task_id), raw)
    return SavedRevisionReference(taskId=task_id, contextSha256=context.digest(),
        workflowRunId=context.workflow_run_id, reportId=context.report_id, revision=context.revision,
        file=ReportFileInput(**identity.model_dump(), filename='current.md', mediaType='text/markdown'))


async def freeze_binary_revision_reference(editor, context, task_id, request, raw):
    from .workflow.runtime.analysis import RuntimeAnalysisMixin

    if raw is None or hashlib.sha256(raw).hexdigest() != request.expected_binary_sha256:
        raise ReportingError('report_editor_conflict', '当前原生保存稿身份无法核验。')
    selection = request.native_source or request.office_source
    format = selection.format
    media = BINARY_MEDIA
    artifacts = RuntimeAnalysisMixin()
    artifacts.workspace_service = editor.workspace
    identity = await artifacts._write_immutable_artifact(context.scope['threadId'],
        snapshot_path(context, task_id, format), raw)
    return SavedRevisionReference(taskId=task_id, contextSha256=context.digest(), source=('native_editor' if request.native_source else request.office_source.editor + '_editor'),
        nativeSource=request.native_source, officeSource=request.office_source, format=format, workflowRunId=context.workflow_run_id,
        reportId=context.report_id, revision=context.revision,
        file=ReportFileInput(**identity.model_dump(), filename=f'current.{format}', mediaType=media[format]))


async def read_saved_revision_reference(runtime, workspace_key, reference):
    """独立使用既有五格式 reader；不更改父运行材料或占用附件名额。"""
    from types import SimpleNamespace

    from agno.workflow.types import StepInput

    from .workflow.checkpoint import FileIdentity
    from .workflow.runtime.reference_materials import prepare_reference_materials

    identity = FileIdentity.model_validate(reference.file.model_dump(include={'path', 'size', 'sha256'}))
    # 身份失败须在解析前明确拒绝，不能由 reader 的软解析告警吞掉或回退可变稿。
    raw = await runtime._read_identity_bytes(workspace_key, identity, max_bytes=50 * 1024 * 1024)
    async def reader(_file):
        return raw
    result = await prepare_reference_materials(StepInput(), SimpleNamespace(session_state={}),
        file_inputs=(reference.file,), registered_reader=reader)
    return {'binding': reference.model_dump(mode='json', by_alias=True),
        'reference': next(iter(result.content['references']), None), 'issues': result.content['issues']}
