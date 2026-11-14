"""兼容旧导入路径：授权与会话存储已迁至 smart_reporting.office.editor_grant_repository。"""

from ..office.editor_grant_repository import (  # noqa: F401
    SqlAlchemyReportEditorRepository,
    report_editor_grants_v1,
    report_editor_sessions_v1,
)
