"""Company-admin BYOK configuration with encrypted, write-only API keys."""

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from pydantic import ValidationError

from ..management.models import ManagementError
from .provider_catalog import CAPABILITIES, ProviderInput, catalog_for, defaults
from .provider_runtime import ProviderRuntime
from .repository import OfficeError
from .schema import provider_settings


class OfficeProviders:
    def __init__(self, office, vault):
        self.office, self.vault = office, vault
        self.runtime = ProviderRuntime()

    async def _read(self, actor, capability, *, admin=False):
        if capability not in CAPABILITIES:
            raise OfficeError("office_provider_capability_invalid", "不支持的能力。", 422)
        async with self.office.transaction(actor) as conn:
            if admin:
                await self.office._user(conn, actor, admin=True)
            row = (
                (
                    await conn.execute(
                        select(provider_settings).where(
                            provider_settings.c.company == actor.tenant,
                            provider_settings.c.capability == capability,
                        )
                    )
                )
                .mappings()
                .first()
            )
        return (
            {**row["document"], "version": row["version"]}
            if row
            else {**defaults(capability), "version": 0}
        )

    @staticmethod
    def public(value):
        return {
            **{key: value[key] for key in ("enabled", "provider", "model", "baseUrl", "version")},
            "hasKey": bool(value.get("ciphertext")),
        }

    async def catalog(self, actor):
        values = {
            cap: self.public(await self._read(actor, cap, admin=True)) for cap in CAPABILITIES
        }
        return {
            "settings": values,
            "catalog": {cap: catalog_for(cap) for cap in CAPABILITIES},
            "credentialStorageAvailable": bool(self.vault and self.vault.active_key_id),
        }

    async def _prepare(self, actor, capability, document):
        old = await self._read(actor, capability, admin=True)
        try:
            body = ProviderInput.model_validate(document)
        except ValidationError:
            raise OfficeError(
                "office_provider_config_invalid", "提供商配置格式无效。", 422
            ) from None
        if body.expectedVersion != old["version"]:
            raise OfficeError("office_provider_conflict", "配置已在其他窗口修改，请重新加载。", 409)
        allowed = {item["id"] for item in catalog_for(capability)}
        if body.provider not in allowed or (
            capability != "webSearch" and body.enabled and not body.model
        ):
            raise OfficeError(
                "office_provider_config_invalid", "请选择支持该能力的提供商并填写模型。", 422
            )
        value = body.model_dump(exclude={"apiKey", "expectedVersion"})
        # Never carry an old vendor key across provider OR endpoint changes.
        same = (old["provider"], old["baseUrl"]) == (body.provider, body.baseUrl)
        if body.apiKey is None and same and old.get("ciphertext"):
            value.update(ciphertext=old["ciphertext"], keyId=old["keyId"])
        elif body.apiKey:
            if not self.vault or not self.vault.active_key_id:
                raise OfficeError(
                    "office_provider_vault_unavailable",
                    "请先配置 AGENT_MANAGEMENT_CREDENTIAL_KEYS 以加密保存 API Key。",
                    503,
                )
            try:
                value.update(
                    ciphertext=self.vault.encrypt(body.apiKey).decode(),
                    keyId=self.vault.active_key_id,
                )
            except ManagementError:
                raise OfficeError(
                    "office_provider_vault_unavailable", "API Key 加密存储不可用。", 503
                ) from None
        if value["enabled"] and not value.get("ciphertext"):
            raise OfficeError(
                "office_provider_key_required", "启用前请填写此提供商的 API 密钥。", 422
            )
        return value, old["version"]

    async def save(self, actor, capability, document):
        value, version = await self._prepare(actor, capability, document)
        try:
            async with self.office.transaction(actor) as conn:
                await self.office._user(conn, actor, admin=True)
                if version == 0:
                    await conn.execute(
                        insert(provider_settings).values(
                            company=actor.tenant, capability=capability, version=1, document=value
                        )
                    )
                else:
                    result = await conn.execute(
                        update(provider_settings)
                        .where(
                            provider_settings.c.company == actor.tenant,
                            provider_settings.c.capability == capability,
                            provider_settings.c.version == version,
                        )
                        .values(version=version + 1, document=value)
                    )
                    if result.rowcount != 1:
                        raise OfficeError(
                            "office_provider_conflict", "配置已在其他窗口修改，请重新加载。", 409
                        )
                await self.office._audit(
                    conn, actor, "provider.configure", capability=capability, version=version + 1
                )
        except IntegrityError:
            raise OfficeError(
                "office_provider_conflict", "配置已在其他窗口修改，请重新加载。", 409
            ) from None
        return self.public({**value, "version": version + 1})

    def _key(self, value):
        try:
            if not self.vault or not value.get("ciphertext"):
                raise ValueError
            return self.vault.decrypt(value["keyId"], value["ciphertext"].encode())
        except (ManagementError, ValueError):
            raise OfficeError(
                "office_provider_key_unavailable",
                "提供商密钥不可用，请管理员检查加密密钥及配置。",
                503,
            ) from None

    async def enabled(self, actor):
        return [cap for cap in CAPABILITIES if (await self._read(actor, cap))["enabled"]]

    async def _active(self, actor, capability):
        value = await self._read(actor, capability)
        if not value["enabled"]:
            raise OfficeError("office_provider_disabled", "管理员尚未启用此能力。", 403)
        return value

    async def _unchanged(self, actor, capability, before):
        after = await self._active(actor, capability)
        if after["version"] != before["version"]:
            raise OfficeError("office_provider_changed", "任务期间提供商配置已变化，请重试。", 409)

    async def chat_model(self, actor):
        from .provider_models import native_chat_model

        value = await self._read(actor, "chatModel")
        if value["version"] == 0:
            return None
        value = await self._active(actor, "chatModel")

        async def guard():
            await self._unchanged(actor, "chatModel", value)

        return native_chat_model(
            value, self._key(value), guard, transport=self.runtime.http.transport
        )

    async def generate(self, actor, prompt):
        from .provider_images import generate_image

        value = await self._active(actor, "imageGeneration")
        result = await generate_image(self.runtime, value, self._key(value), prompt)
        await self._unchanged(actor, "imageGeneration", value)
        return result

    async def search(self, actor, query, limit=6):
        value = await self._active(actor, "webSearch")
        result = await self.runtime.search(value, self._key(value), query, limit)
        await self._unchanged(actor, "webSearch", value)
        return result

    async def analyze(self, actor, media_urls, requirements):
        # Reauthorize before fetching media; only request bodies/public HTTPS are accepted.
        enabled = await self.enabled(actor)
        if not any(cap in enabled for cap in ("imageAnalysis", "videoAnalysis")):
            raise OfficeError("office_provider_disabled", "管理员尚未启用媒体分析。", 403)
        media = await self.runtime.load_media(media_urls)
        capability = (
            "videoAnalysis"
            if any(mime.startswith("video/") for mime, _ in media)
            else "imageAnalysis"
        )
        value = await self._active(actor, capability)
        result = await self.runtime.analyze(value, self._key(value), media, requirements)
        await self._unchanged(actor, capability, value)
        return result

    async def test(self, actor, capability, document, media=None):
        value, version = await self._prepare(actor, capability, document)
        key = self._key(value)
        if capability == "chatModel":
            from agno.agent import Agent
            from .provider_models import native_chat_model
            from ..reporting.agent_events import run_owned_agent_with_events

            async def guard():
                current = await self._read(actor, capability, admin=True)
                if current["version"] != version:
                    raise OfficeError("office_provider_conflict", "配置已变化，请重新测试。", 409)

            model = native_chat_model(value, key, guard, transport=self.runtime.http.transport)
            try:
                answer = await run_owned_agent_with_events(
                    Agent(model=model, telemetry=False, retries=0), "Reply with OK."
                )
                if not isinstance(answer.content, str) or not answer.content.strip():
                    raise ValueError
            except OfficeError:
                raise
            except Exception:
                raise OfficeError(
                    "office_model_test_failed",
                    "模型未返回有效响应，请检查模型、服务地址、密钥及配额。",
                    502,
                ) from None
        elif capability == "imageGeneration":
            from .provider_images import generate_image

            await generate_image(
                self.runtime, value, key, "A simple white square on a blue background."
            )
        elif capability == "webSearch":
            result = await self.runtime.search(value, key, "GenOffice", 1)
            if not result["results"]:
                raise OfficeError(
                    "office_provider_test_empty",
                    "提供商未返回可用的搜索结果，无法确认连接有效。",
                    502,
                )
        else:
            if not media:
                raise OfficeError(
                    "office_provider_test_media_required",
                    "请选择一张图片或一段短视频以验证实际分析能力。",
                    422,
                )
            loaded = await self.runtime.load_media(media)
            actual = (
                "videoAnalysis"
                if any(m.startswith("video/") for m, _ in loaded)
                else "imageAnalysis"
            )
            if actual != capability:
                raise OfficeError(
                    "office_provider_test_media_invalid", "测试文件与当前能力不匹配。", 422
                )
            await self.runtime.analyze(value, key, loaded, "Briefly describe the supplied media.")
        current = await self._read(actor, capability, admin=True)
        if current["version"] != version:
            raise OfficeError("office_provider_conflict", "配置已变化，请重新测试。", 409)
        return {"ok": True, "message": "提供商已返回有效结果；测试未保存配置。"}
