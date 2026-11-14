"""偏好验收恢复正式运行时复用的完整授权身份校验。"""

from ..reporting.models import ReportingError


def require_office_run(scope, registered):
    expected = {'report_run_id': scope.run_id, 'external_run_id': scope.external_run_id,
        'agno_run_id': scope.run_id, 'agno_session_id': scope.session_id,
        'thread_id': scope.caller_thread_id, 'owner_user_id': scope.user_id}
    if any(registered.get(key) != value for key, value in expected.items()):
        raise ReportingError('report_editor_scope_mismatch', '正式来源耐久运行登记与完整授权身份不一致。')
