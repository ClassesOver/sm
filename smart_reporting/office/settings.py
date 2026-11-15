"""Company defaults and per-user settings, always keyed by authenticated Office identity."""

import hashlib
import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

from agno.skills import Skills
from agno.skills.loaders.base import SkillLoader
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from .repository import OfficeError
from .schema import settings as settings_table

DEFAULT_GLOBAL = {
    "modelId": "",
    "imageModel": "",
    "searchEnabled": True,
    "integrationsEnabled": True,
}


@lru_cache(maxsize=1)
def skill_sources():
    from .ai_skills import office_skills

    return tuple(office_skills().get_all_skills())


@lru_cache(maxsize=1)
def skill_catalog():
    path = Path(__file__).parent / "vendor/genoffice/skills/recommended/locales/zh.json"
    translated = json.loads(path.read_text())
    return tuple(
        {
            "id": skill.name,
            "name": skill.name,
            "description": translated.get(skill.name, skill.description),
        }
        for skill in skill_sources()
    )


class SnapshotLoader(SkillLoader):
    def __init__(self, skills):
        self.skills = skills

    def load(self):
        return deepcopy(list(self.skills))


class OfficeSkills(Skills):
    def _get_skill_script(self, skill_name: str, script_path: str, execute: bool = False) -> str:
        # Imported desktop CLI guidance must never bypass native edit/accept authority.
        if execute:
            return json.dumps(
                {
                    "error": "Office skills are reference-only. Use the current document tools; script execution is unavailable."
                }
            )
        return super()._get_skill_script(skill_name, script_path, execute=False)


class OfficeSettings:
    def __init__(self, office):
        self.office = office

    async def _read(self, actor, *, global_settings=False, require_admin=False):
        owner = "*" if global_settings else "user:" + actor.user
        async with self.office.transaction(actor) as connection:
            if require_admin:
                await self.office._user(connection, actor, admin=True)
            row = (
                (
                    await connection.execute(
                        select(settings_table).where(
                            settings_table.c.company == actor.tenant,
                            settings_table.c.owner == owner,
                        )
                    )
                )
                .mappings()
                .first()
            )
        defaults = DEFAULT_GLOBAL if global_settings else {"theme": "system", "enabledSkills": []}
        return {
            "version": row["version"] if row else 0,
            **defaults,
            **(row["document"] if row else {}),
        }

    async def personal(self, actor):
        value = await self._read(actor)
        enabled = set(value.pop("enabledSkills"))
        return {
            **value,
            "scope": hashlib.sha256((actor.tenant + ":" + actor.user).encode()).hexdigest(),
            "skills": [dict(skill, enabled=skill["id"] in enabled) for skill in skill_catalog()],
        }

    async def global_settings(self, actor, *, require_admin=True):
        return await self._read(actor, global_settings=True, require_admin=require_admin)

    async def save(self, actor, document, version, *, global_settings=False):
        owner = "*" if global_settings else "user:" + actor.user
        if not global_settings and not set(document.get("disabledSkills", [])) <= {
            skill["id"] for skill in skill_catalog()
        }:
            raise OfficeError("office_skill_unknown", "Skill列表已变化，请重新打开设置。", 422)
        if not global_settings:
            document = {
                "theme": document["theme"],
                "enabledSkills": sorted(
                    {skill["id"] for skill in skill_catalog()}
                    - set(document.get("disabledSkills", []))
                ),
            }
        try:
            async with self.office.transaction(actor) as connection:
                if global_settings:
                    await self.office._user(connection, actor, admin=True)
                if version == 0:
                    await connection.execute(
                        insert(settings_table).values(
                            company=actor.tenant, owner=owner, version=1, document=document
                        )
                    )
                else:
                    result = await connection.execute(
                        update(settings_table)
                        .where(
                            settings_table.c.company == actor.tenant,
                            settings_table.c.owner == owner,
                            settings_table.c.version == version,
                        )
                        .values(version=version + 1, document=document)
                    )
                    if result.rowcount != 1:
                        raise OfficeError(
                            "office_settings_conflict", "设置已在其他窗口修改，请重新打开。", 409
                        )
                await self.office._audit(
                    connection,
                    actor,
                    "settings.global" if global_settings else "settings.personal",
                    version=version + 1,
                )
        except IntegrityError:
            raise OfficeError(
                "office_settings_conflict", "设置已在其他窗口修改，请重新打开。", 409
            ) from None
        return await self.global_settings(actor) if global_settings else await self.personal(actor)

    async def skills(self, actor):
        enabled = {item["id"] for item in (await self.personal(actor))["skills"] if item["enabled"]}
        values = [skill for skill in skill_sources() if skill.name in enabled]
        return OfficeSkills(loaders=[SnapshotLoader(values)]) if values else None

    async def model(self, actor, fallback):
        model = deepcopy(fallback)
        configured = await self.global_settings(actor, require_admin=False)
        if configured["modelId"] and model is not None:
            model.id = configured["modelId"]
        return model


async def native_settings():
    from .native_access import current
    from .repository import Identity

    session, authorize = current()
    documents = getattr(authorize, "__self__", None)
    if session is None or getattr(documents, "office", None) is None:
        return None
    await documents.authorize(session)
    value = session.capabilities["office"]
    return OfficeSettings(documents.office), Identity(
        value["database"], value["company"], value["user"], value["version"], value["session"]
    )


async def native_model(fallback):
    context = await native_settings()
    return await context[0].model(context[1], fallback) if context else deepcopy(fallback)


async def attach_personal_skills(agent):
    context = await native_settings()
    if context:
        agent.skills = await context[0].skills(context[1])


async def configure_office_agent(agent, *, update_model=False):
    from .ai_skills import attach_office_skills

    attach_office_skills(agent)
    context = await native_settings()
    if context is None:
        return
    await attach_personal_skills(agent)
    from .provider_tools import attach_provider_tools

    await attach_provider_tools(agent)
    if update_model:
        agent.model = await context[0].model(context[1], agent.model)
    config = await context[0].global_settings(context[1], require_admin=False)
    if config["integrationsEnabled"]:
        from .ai_sources import attach_office_sources

        attach_office_sources(agent)
