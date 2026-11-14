"""启动时读取已发布系统值；不修改环境，不影响旧进程持有的设置对象。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from ..management.configuration_catalog import resolve_system_settings
from ..management.configuration_store import configuration_hash
from ..management.data_sources.secrets import CredentialVault
from ..management.models import ManagementError
from ..management.repository import configuration_versions, system_credentials
from ..management.system_configuration import CREDENTIAL_ATTRIBUTES, validate_system_document
from .database import _normalized_database_urls
from .settings import AgentSettings


@dataclass(frozen=True)
class SystemConfigurationState:
    revision: int | None = None
    content_hash: str | None = None
    managed_keys: tuple[str, ...] = ()
    loaded_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    issue: dict | None = None


@dataclass(frozen=True)
class LoadedSystemConfiguration:
    settings: AgentSettings = field(repr=False)
    state: SystemConfigurationState


def load_system_configuration(startup: AgentSettings) -> LoadedSystemConfiguration:
    """旧部署无表时可启动；读取失败准确记录，不误报保存值已生效。"""
    _, _, url = _normalized_database_urls(startup.database_url)
    engine = create_engine(url, connect_args={"connect_timeout": 3}, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            record = (connection.execute(select(configuration_versions).where(
                configuration_versions.c.kind == "system").order_by(
                    configuration_versions.c.revision.desc()).limit(1))).mappings().one_or_none()
        if record is None:
            return LoadedSystemConfiguration(startup, SystemConfigurationState())
        document = record["document"]
        if configuration_hash(document) != record["content_hash"] or validate_system_document(startup, document) != document:
            raise ValueError("configuration identity invalid")
        resolved = resolve_system_settings(startup, document["values"])
        references = document.get('credentials', {})
        if references:
            vault = CredentialVault()
            secrets = {}
            with engine.connect() as connection:
                for key, reference in references.items():
                    credential = (connection.execute(select(system_credentials).where(
                        system_credentials.c.key == key, system_credentials.c.reference == reference))).mappings().one_or_none()
                    if credential is None:
                        raise ManagementError('management_system_credential_invalid', '系统凭据引用无法读取。', 503)
                    secrets[CREDENTIAL_ATTRIBUTES[key]] = vault.decrypt(credential['key_id'], credential['ciphertext'].encode())
            resolved = replace(resolved, **secrets)
        resolved = replace(resolved, managed_system_revision=record["revision"], managed_system_hash=record["content_hash"])
        return LoadedSystemConfiguration(resolved, SystemConfigurationState(
            revision=record["revision"], content_hash=record["content_hash"], managed_keys=tuple(document["values"]) + tuple(references)))
    except ManagementError as error:
        code, message = 'management_configuration_credential_unavailable', '已发布系统凭据无法读取，当前使用部署启动值。请检查加密密钥与凭据版本。'
        logger.warning('system_configuration_load_failed code={} reason={}', code, error.code)
    except SQLAlchemyError as error:
        missing = getattr(error.orig, "sqlstate", None) == "42P01" if hasattr(error, "orig") else False
        code = "management_configuration_schema_missing" if missing else "management_configuration_unavailable"
        message = "系统配置存储尚未迁移，当前使用部署启动值。" if missing else "系统配置读取失败，当前使用部署启动值。"
        logger.warning("system_configuration_load_failed code={} error_type={}", code, type(error).__name__)
    except (TypeError, ValueError) as error:
        code, message = "management_configuration_corrupt", "已发布系统配置校验失败，当前使用部署启动值。"
        logger.warning("system_configuration_load_failed code={} error_type={}", code, type(error).__name__)
    finally:
        engine.dispose()
    return LoadedSystemConfiguration(startup, SystemConfigurationState(issue={"code": code, "message": message}))


def system_application_status(state: SystemConfigurationState | None, published: dict | None) -> dict:
    if state is None:
        return {"canApply": False, "status": "not_connected", "requiresRestart": False,
            "reason": "启动配置读取尚未接通，当前仅维护草稿。", "effectiveRevision": None,
            "publishedRevision": published["revision"] if published else None}
    pending = bool(published and (published["revision"] != state.revision or published["contentHash"] != state.content_hash))
    return {"canApply": True, "status": "load_failed" if state.issue else "restart_required" if pending else "active" if state.revision else "deployment",
        "requiresRestart": pending, "effectiveRevision": state.revision,
        "publishedRevision": published["revision"] if published else None, "loadedAt": state.loaded_at,
        "issue": state.issue, "reason": "系统配置在服务重启后生效，正在运行的任务继续使用原配置。"}
