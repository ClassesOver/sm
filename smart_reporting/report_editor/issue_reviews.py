"""从服务端已授权修订和追溯索引绑定反馈，不接受客户端声明组织或对象集合。"""

from ..management.models import ManagementError, ManagementScope
from ..management.report_issue_reviews import ReportIssueReviewService
from .trace_retention import source_lifecycle_lock


async def report_issue_reviews(editor, expected, *, submission=None, issue_id=None, limit=50, after=None):
    editor._require_lineage_feature('panel')
    async with source_lifecycle_lock(editor, expected, exclusive=False):
        context = await editor._restore(expected)
        source = await editor._source_context(context)
        index = await editor.trace.require_index(source)
        bases = editor.trace.report_basis_service
        if bases is None or not index.report_basis_id:
            raise ManagementError('management_issue_unavailable', '该报告缺少可信计算依据，反馈服务暂不可用。', 503)
        service = ReportIssueReviewService(bases)
        scope = source.scope
        binding = dict(run_id=source.workflow_run_id,
            scope=ManagementScope(scope['database'], scope['companyId']),
            user_id=scope['userId'], thread_id=scope['callerThreadId'], basis_id=index.report_basis_id,
            report_id=context.report_id, revision=context.revision)
        if submission is None:
            return await service.report_list(**binding, issue_id=issue_id, limit=limit, after=after)
        return await service.submit(**binding, payload=submission.model_dump(mode='json', by_alias=True),
            allowed_object_refs=(index.report_basis_id, *(item.subject_id for item in index.subject_bindings)))
