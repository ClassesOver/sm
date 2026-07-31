"""独立 AgentOS 的官方 JWT 授权配置。"""

from agno.os.config import AuthorizationConfig

from .settings import AgentSettings


def agentos_authorization_config(settings: AgentSettings) -> AuthorizationConfig:
    key = settings.agentos_jwt_verification_key
    if key is None:
        raise ValueError("独立 AgentOS 要求配置 JWT_VERIFICATION_KEY。")
    return AuthorizationConfig(
        verification_keys=[key],
        algorithm=settings.agentos_jwt_algorithm,
        verify_audience=settings.agentos_jwt_audience is not None,
        audience=settings.agentos_jwt_audience,
        user_isolation=True,
    )
