from __future__ import annotations

import base64
import hashlib
import os
import json

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import insert, select

from ..models import ManagementError
from ..repository import source_credentials


class CredentialVault:
    def __init__(self, keys: str | None = None):
        raw = keys if keys is not None else os.environ.get('AGENT_MANAGEMENT_CREDENTIAL_KEYS', '')
        entries = [part for part in raw.split(',') if part]
        if not entries:
            self.key_ids = ()
            self.active_key_id = None
            self.fernet = None
            return
        parsed = []
        try:
            for item in entries:
                key_id, value = item.split(':', 1)
                Fernet(value.encode())
                if not key_id or len(key_id) > 32:
                    raise ValueError
                parsed.append((key_id, value))
        except ValueError as error:
            raise ManagementError('management_secrets_invalid', '数据源加密密钥配置无效。', 503) from error
        self.key_ids = tuple(key for key, _ in parsed)
        self.active_key_id = self.key_ids[0]
        self.fernet = MultiFernet([Fernet(value.encode()) for _, value in parsed])

    @staticmethod
    def generate_key() -> str:
        return base64.urlsafe_b64encode(os.urandom(32)).decode()

    def encrypt(self, plaintext: str) -> bytes:
        if self.fernet is None:
            raise ManagementError('management_secrets_unavailable', '未配置数据源加密密钥。', 503)
        return self.fernet.encrypt(plaintext.encode())

    def decrypt(self, key_id: str, ciphertext: bytes) -> str:
        if self.fernet is None or key_id not in self.key_ids:
            raise ManagementError('management_credential_key_missing', '缺少解密历史凭据所需的密钥。', 503)
        try:
            return self.fernet.decrypt(ciphertext).decode()
        except (InvalidToken, UnicodeDecodeError) as error:
            raise ManagementError('management_credential_unavailable', '数据源凭据无法解密。', 503) from error

    async def store(self, connection, scope_id: str, source_id: str, reference: str,
                    revision: int, secret: str) -> None:
        await connection.execute(insert(source_credentials).values(
            scope_id=scope_id, source_id=source_id, credential_ref=reference,
            revision=revision, key_id=self.active_key_id, ciphertext=json.dumps(self.encrypt(secret).decode()),
            secret_hash=hashlib.sha256(secret.encode()).hexdigest()))

    async def resolve(self, connection, scope_id: str, source_id: str, reference: str) -> str:
        row = (await connection.execute(select(source_credentials).where(
            source_credentials.c.scope_id == scope_id, source_credentials.c.source_id == source_id,
            source_credentials.c.credential_ref == reference))).mappings().one_or_none()
        if row is None:
            raise ManagementError('management_credential_not_found', '数据源凭据不存在。', 404)
        return self.decrypt(row['key_id'], json.loads(row['ciphertext']).encode())
