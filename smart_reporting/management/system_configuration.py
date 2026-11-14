"""普通系统配置版本；部署基础项和秘密保留各自的维护边界。"""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import insert, select

from ..preferences.models import PreferenceModel
from ..runtime.settings import AgentSettings
from .configuration_catalog import (
    CONFIGURATION_CATALOG,
    configuration_inventory,
    resolve_system_settings,
    validate_system_values,
)
from .configuration_store import ConfigurationVersionService, document_changes
from .data_sources.secrets import CredentialVault
from .models import ManagementError
from .repository import system_credentials

CREDENTIAL_ATTRIBUTES = {'OPENAI_API_KEY': 'openai_api_key', 'AGENT_REPORT_METADATA_TOKEN': 'report_metadata_token'}


class SystemConfiguration(PreferenceModel):
    schema_version: Literal[1] = 1
    values: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    credentials: dict[str, str] = Field(default_factory=dict)


def validate_system_document(startup: AgentSettings, document) -> dict:
    parsed = SystemConfiguration.model_validate(document)
    for key, reference in parsed.credentials.items():
        if key not in CREDENTIAL_ATTRIBUTES or str(UUID(reference)) != reference:
            raise ValueError('system credential reference invalid')
    values = validate_system_values(parsed.values)
    resolve_system_settings(startup, values)
    result = SystemConfiguration(values=values, credentials=parsed.credentials).model_dump(mode="json", by_alias=True)
    if not result['credentials']:
        result.pop('credentials')
    return result


class SystemConfigurationService(ConfigurationVersionService):
    def __init__(self, auth, startup: AgentSettings):
        self.startup = startup
        inventory = {item["key"]: item for item in configuration_inventory(startup)}
        initial = {"values": {item.key: inventory[item.key]["value"]
            for item in CONFIGURATION_CATALOG if item.activation == "restart" and not item.sensitive
            and not inventory[item.key]["redacted"] and (inventory[item.key]["configured"] or item.nullable)}}
        super().__init__(auth, initial, kind="system", validator=self.validate_document,
            action_prefix="system_configuration", invalid_code="management_system_configuration_invalid")

    def validate_document(self, document):
        return validate_system_document(self.startup, document)

    async def detail(self, raw_session):
        payload = await super().detail(raw_session)
        before = payload['effective']['document'] if payload['effective'] else payload['initial']
        payload['changes'] = document_changes({'credentials': {}, **before},
            {'credentials': {}, **payload['draft']['document']})
        return payload

    async def _save(self, connection, row, document, action, **details):
        for key, reference in document.get('credentials', {}).items():
            found = (await connection.execute(select(system_credentials.c.reference).where(
                system_credentials.c.key == key, system_credentials.c.reference == reference))).scalar_one_or_none()
            if found is None:
                raise ManagementError('management_system_credential_invalid', '凭据引用不存在，请重新替换。', 422)
        return await super()._save(connection, row, document, action, **details)

    async def replace_credential(self, raw_session, key, secret, expected_version):
        if key not in CREDENTIAL_ATTRIBUTES or not isinstance(secret, str) or not secret.strip() or len(secret) > 8192 or any(ord(char) < 32 or ord(char) == 127 for char in secret):
            raise ManagementError('management_system_credential_invalid', '请选择可替换凭据并填写有效内容。', 422)
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, raw_session, self.auth.clock())
            row = await self._draft(connection)
            self._expected(row, expected_version)
            vault = CredentialVault()
            ciphertext = vault.encrypt(secret).decode()
            reference = str(uuid4())
            await connection.execute(insert(system_credentials).values(reference=reference, key=key,
                key_id=vault.active_key_id, ciphertext=ciphertext, created_at=self.auth.clock()))
            document = {**row['document'], 'credentials': {**row['document'].get('credentials', {}), key: reference}}
            return await self._save(connection, row, document, 'system_configuration_credential_replaced', key=key)

    def resolve_document(self, document) -> AgentSettings:
        parsed = self.validate_document(document)
        return resolve_system_settings(self.startup, parsed["values"])
