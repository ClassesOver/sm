"""用户个人报告设计模板，生产环境由 PostgreSQL 持久化。"""
from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import Column, MetaData, String, Table, delete, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ..reporting.delivery.report_design import ReportDesign, template_design

_metadata = MetaData()
_templates = Table(
    "report_editor_design_templates_v1", _metadata,
    Column("user_id", String(256), primary_key=True),
    Column("template_id", String(64), primary_key=True),
    Column("name", String(100), nullable=False),
    Column("design", JSONB, nullable=False),
)


def _payload(template_id: str, name: str, design: ReportDesign) -> dict[str, Any]:
    return {"templateId": template_id, "name": name,
            "design": template_design(design).model_dump(mode="json", by_alias=True)}


class SqlAlchemyDesignTemplateRepository:
    def __init__(self, engine: AsyncEngine):
        self.engine = engine

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(_metadata.create_all)

    async def list(self, user_id: str) -> list[dict[str, Any]]:
        async with self.engine.connect() as connection:
            result = await connection.execute(select(_templates).where(_templates.c.user_id == user_id).order_by(_templates.c.name, _templates.c.template_id))
            return [{"templateId": row["template_id"], "name": row["name"], "design": row["design"]} for row in result.mappings()]

    async def save(self, user_id: str, template_id: str, name: str, design: ReportDesign) -> dict[str, Any]:
        item = _payload(template_id, name, design)
        statement = insert(_templates).values(user_id=user_id, template_id=template_id, name=name, design=item["design"])
        async with self.engine.begin() as connection:
            await connection.execute(statement.on_conflict_do_update(index_elements=[_templates.c.user_id, _templates.c.template_id], set_={"name": name, "design": item["design"]}))
        return item

    async def delete(self, user_id: str, template_id: str) -> bool:
        async with self.engine.begin() as connection:
            result = await connection.execute(delete(_templates).where(_templates.c.user_id == user_id, _templates.c.template_id == template_id))
            return result.rowcount > 0


class InMemoryDesignTemplateRepository:
    def __init__(self):
        self.items: dict[tuple[str, str], dict[str, Any]] = {}

    async def list(self, user_id: str) -> list[dict[str, Any]]:
        return copy.deepcopy(sorted([item for (owner, _), item in self.items.items() if owner == user_id], key=lambda item: (item["name"], item["templateId"])))

    async def save(self, user_id: str, template_id: str, name: str, design: ReportDesign) -> dict[str, Any]:
        item = _payload(template_id, name, design)
        self.items[(user_id, template_id)] = copy.deepcopy(item)
        return item

    async def delete(self, user_id: str, template_id: str) -> bool:
        return self.items.pop((user_id, template_id), None) is not None
