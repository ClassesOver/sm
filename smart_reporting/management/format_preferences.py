"""全局格式偏好的版本服务；执行器接通前不注册应用 HTTP 入口。"""

from ..preferences.capabilities import unsupported_preference_reason
from ..preferences.models import FormatPreferences
from ..reporting.models import ReportingError
from .configuration_store import ConfigurationVersionService, document_changes
from .models import ManagementError


class FormatPreferenceService(ConfigurationVersionService):
    def __init__(self, auth, initial: FormatPreferences):
        super().__init__(auth, initial.model_dump(mode="json", by_alias=True), kind="preferences",
            validator=lambda document: FormatPreferences.model_validate(document).model_dump(mode="json", by_alias=True),
            action_prefix="format_preferences", invalid_code="management_preferences_invalid")
        self.approval_service = None

    async def publish(self, raw_session, expected_version):
        await self.auth.authenticate(raw_session)
        raise ManagementError('management_preference_approval_required', '全局偏好必须先完成当前草稿的验收批准。', 409)

    async def apply_approved(self, raw_session, *, expected_version, expected_hash,
        expected_effective_revision, approval_id, expected_approval_hash):
        if self.approval_service is None:
            await self.auth.authenticate(raw_session)
            raise ManagementError('management_preference_approval_unavailable', '偏好批准服务尚未就绪。', 503)
        try:
            return await self.approval_service.apply(raw_session, expected_version=expected_version,
                expected_hash=expected_hash, expected_effective_revision=expected_effective_revision,
                approval_id=approval_id, expected_approval_hash=expected_approval_hash)
        except ReportingError as error:
            raise ManagementError(error.code, error.message, 403) from None

    async def save_draft(self, raw_session, document, expected_version):
        document = self._document(document)
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, raw_session, self.auth.clock())
            row = await self._draft(connection)
            self._expected(row, expected_version)
            # 只检查原始字段的新修改；共享默认解析后的继承变化不是格式私有修改。
            for change in document_changes(row["document"], document):
                path = change["path"]
                if reason := unsupported_preference_reason(path.split(".", 1)[0], path):
                    raise ManagementError("management_preferences_unsupported_change",
                        f"字段 {path} 尚未接入实际生成，不能保存本次修改。{reason}", 422)
            return await self._save(connection, row, document, f"{self.action_prefix}_saved")
