"""旧业务Profile仅保留鉴权后的固定停用响应，不读写归档数据。"""

from fastapi import APIRouter

from .api import create_protected_router
from .models import ManagementError
from .scopes import ScopeService


def create_profile_router(scopes: ScopeService) -> APIRouter:
    router = create_protected_router(scopes.auth, 'management-profiles-retired')

    @router.api_route('/management/api/v1/profiles', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
    @router.api_route('/management/api/v1/profiles/{retired_path:path}',
                      methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
    async def retired():
        raise ManagementError('management_profile_retired',
            '业务Profile已停用，请分别登记指标、统计口径和知识依据。旧配置不自动转换。', 410)

    return router
