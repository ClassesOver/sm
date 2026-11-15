from __future__ import annotations

import hashlib
import json
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from .schema import (
    audit, companies, credentials, files, file_preferences, file_search_text, folders, members, initialize_schema, sessions, source_grants,
    source_member_limits, spaces, users, knowledge_turns, knowledge_deleted,
)


class OfficeError(ValueError):
    def __init__(self, code: str, message: str, status: int = 403):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


_RECENT_HIDDEN = -1  # A subsequent open replaces it with the usual millisecond timestamp.


@dataclass(frozen=True)
class Identity:
    database: str
    company: str
    user: str
    session_version: int | None = None
    session_reference: str | None = None

    def __post_init__(self):
        if not all(isinstance(value, str) and 0 < len(value) <= 256
                   for value in (self.database, self.company, self.user)):
            raise OfficeError("office_identity_invalid", "账号身份无效。")

    @property
    def tenant(self) -> str:
        value = json.dumps([self.database, self.company], ensure_ascii=False)
        return hashlib.sha256(value.encode()).hexdigest()


def _name(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
        raise OfficeError("office_name_invalid", "名称须为 1–200 个字符。", 422)
    return value.strip()


def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class OfficeRepository:
    def __init__(self, engine: AsyncEngine, *, clock=time.time):
        self.engine, self.clock = engine, clock

    async def create_schema(self):
        async with self.engine.begin() as connection:
            await connection.run_sync(initialize_schema)

    @asynccontextmanager
    async def transaction(self, actor: Identity):
        async with self.engine.begin() as connection:
            # Serialize company policy changes with resource operations on PostgreSQL.
            row = (await connection.execute(select(companies).where(
                companies.c.id == actor.tenant).with_for_update())).first()
            if row is None:
                raise OfficeError("office_company_missing", "公司尚未开通 Office。")
            await self._user(connection, actor)
            yield connection

    async def _user(self, connection, actor: Identity, *, admin=False):
        row = (await connection.execute(select(users).where(
            users.c.company == actor.tenant, users.c.user == actor.user,
        ))).mappings().first()
        if row is None or not row["enabled"]:
            if actor.session_reference is not None:
                raise OfficeError("office_session_invalid", "Office 会话已失效。", 401)
            raise OfficeError("office_user_disabled", "Office 账号未开通或已停用。")
        if actor.session_version is not None and actor.session_version != row["version"]:
            raise OfficeError("office_session_invalid", "权限已更新，请重新登录。", 401)
        if actor.session_reference is not None:
            active = await connection.scalar(select(sessions.c.token).where(
                sessions.c.token == actor.session_reference, sessions.c.company == actor.tenant,
                sessions.c.user == actor.user, sessions.c.version == row["version"],
                sessions.c.expires > int(self.clock()),
            ))
            if active is None:
                raise OfficeError("office_session_invalid", "Office 会话已失效。", 401)
        if admin and row["role"] != "admin":
            raise OfficeError("office_admin_required", "需要公司管理员权限。")
        return dict(row)

    async def _audit(self, connection, actor: Identity, action: str, **details):
        await connection.execute(insert(audit).values(
            id=str(uuid4()), company=actor.tenant, user=actor.user,
            action=action, details=details, created=int(self.clock()),
        ))

    async def _provision(self, connection, actor: Identity, name: str, role: str):
        await connection.execute(insert(users).values(
            company=actor.tenant, user=actor.user, name=_name(name),
            role=role, enabled=True, version=1,
        ))
        space_id = str(uuid4())
        await connection.execute(insert(spaces).values(
            id=space_id, company=actor.tenant, name="个人空间",
            personal_user=actor.user, archived=False,
        ))
        await connection.execute(insert(members).values(
            space=space_id, user=actor.user, role="owner",
        ))

    async def bootstrap(self, actor: Identity, name: str, *, password_hash=None):
        """Deployment-only initializer; no HTTP route may expose it."""
        async with self.engine.begin() as connection:
            dialect = connection.dialect.name
            if dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as dialect_insert
            elif dialect == "sqlite":
                from sqlalchemy.dialects.sqlite import insert as dialect_insert
            else:
                raise RuntimeError("Office requires PostgreSQL; SQLite is supported for tests.")
            await connection.execute(dialect_insert(companies).values(
                id=actor.tenant, database=actor.database, company=actor.company,
            ).on_conflict_do_nothing(index_elements=["id"]))
            await connection.execute(select(companies).where(
                companies.c.id == actor.tenant).with_for_update())
            existing = (await connection.execute(select(users).where(
                users.c.company == actor.tenant))).first()
            if existing is not None:
                raise OfficeError("office_already_initialized", "公司已经初始化。", 409)
            await self._provision(connection, actor, name, "admin")
            if password_hash is not None:
                await connection.execute(insert(credentials).values(company=actor.tenant, user=actor.user, password_hash=password_hash))
            await self._audit(connection, actor, "company_initialized")

    async def provision(self, actor: Identity, user: str, name: str, *, password_hash=None):
        target = Identity(actor.database, actor.company, user)
        async with self.transaction(actor) as connection:
            await self._user(connection, actor, admin=True)
            existing = await connection.scalar(select(users.c.user).where(
                users.c.company == actor.tenant, users.c.user == user))
            if existing:
                raise OfficeError("office_user_exists", "用户已开通。", 409)
            await self._provision(connection, target, name, "user")
            if password_hash is not None:
                await connection.execute(insert(credentials).values(company=actor.tenant, user=user, password_hash=password_hash))
            await self._audit(connection, actor, "user_provisioned", target=user)

    async def list_users(self, actor: Identity):
        async with self.transaction(actor) as connection:
            await self._user(connection, actor, admin=True)
            rows = (await connection.execute(select(users).where(
                users.c.company == actor.tenant).order_by(users.c.name))).mappings()
            return [dict(row) for row in rows]

    async def me(self, actor: Identity):
        async with self.transaction(actor) as connection:
            return await self._user(connection, actor)

    async def update_user(self, actor: Identity, user: str, *, role=None, enabled=None):
        if role is not None and role not in {"admin", "user"}:
            raise OfficeError("office_role_invalid", "角色无效。", 422)
        async with self.transaction(actor) as connection:
            await self._user(connection, actor, admin=True)
            target = (await connection.execute(select(users).where(
                users.c.company == actor.tenant, users.c.user == user,
            ))).mappings().first()
            if target is None:
                raise OfficeError("office_user_missing", "用户不存在。", 404)
            next_role = role if role is not None else target["role"]
            next_enabled = enabled if enabled is not None else target["enabled"]
            if target["role"] == "admin" and target["enabled"] and (
                next_role != "admin" or not next_enabled
            ):
                replacement = await connection.scalar(select(users.c.user).where(
                    users.c.company == actor.tenant, users.c.user != user,
                    users.c.enabled.is_(True), users.c.role == "admin",
                ))
                if replacement is None:
                    raise OfficeError("office_last_admin", "请先指定另一名有效管理员。", 409)
            if not next_enabled:
                owned = (await connection.execute(select(members.c.space).join(
                    spaces, spaces.c.id == members.c.space).where(
                    spaces.c.company == actor.tenant, spaces.c.personal_user.is_(None),
                    members.c.user == user, members.c.role == "owner",
                ))).scalars().all()
                for space_id in owned:
                    await self._require_other_owner(connection, actor, space_id, user)
            await connection.execute(update(users).where(
                users.c.company == actor.tenant, users.c.user == user,
            ).values(role=next_role, enabled=next_enabled, version=target["version"] + 1))
            await self._audit(connection, actor, "user_updated", target=user,
                              role=next_role, enabled=next_enabled)

    async def reset_password(self, actor: Identity, user: str, password_hash: str):
        async with self.transaction(actor) as connection:
            await self._user(connection, actor, admin=True)
            target = (await connection.execute(update(users).where(
                users.c.company == actor.tenant, users.c.user == user,
            ).values(version=users.c.version + 1).returning(users.c.user))).first()
            if target is None:
                raise OfficeError("office_user_missing", "用户不存在。", 404)
            await connection.execute(delete(credentials).where(
                credentials.c.company == actor.tenant, credentials.c.user == user))
            await connection.execute(insert(credentials).values(
                company=actor.tenant, user=user, password_hash=password_hash))
            await self._audit(connection, actor, "password_reset", target=user)

    async def login(self, actor: Identity, password: str):
        from asyncio import to_thread
        from pwdlib import PasswordHash

        passwords = PasswordHash.recommended()
        async with self.engine.connect() as conn:
            row = (await conn.execute(select(credentials.c.password_hash, users.c.version, users.c.enabled)
                .join(users, (credentials.c.company == users.c.company) & (credentials.c.user == users.c.user))
                .where(credentials.c.company == actor.tenant, credentials.c.user == actor.user))).first()
        if row is None:
            await to_thread(passwords.hash, password)
        elif await to_thread(passwords.verify, password, row.password_hash) and row.enabled:
            return await self.create_session(Identity(actor.database, actor.company, actor.user, row.version))
        raise OfficeError("office_login_invalid", "账号或密码不正确。", 401)

    async def create_session(self, actor: Identity, *, lifetime=3600):
        raw = secrets.token_urlsafe(32)
        async with self.transaction(actor) as connection:
            account = await self._user(connection, actor)
            await connection.execute(insert(sessions).values(
                token=_token_hash(raw), company=actor.tenant, user=actor.user,
                version=account["version"], expires=int(self.clock()) + lifetime,
            ))
        return raw

    async def authenticate(self, raw: str) -> Identity:
        if not raw or len(raw) > 256:
            raise OfficeError("office_session_invalid", "请登录 Office。", 401)
        async with self.engine.connect() as connection:
            row = (await connection.execute(select(
                sessions, companies.c.database, companies.c.company.label("company_id"),
            ).join(companies, companies.c.id == sessions.c.company).where(
                sessions.c.token == _token_hash(raw),
                sessions.c.expires > int(self.clock()),
            ))).mappings().first()
            if row is None:
                raise OfficeError("office_session_invalid", "Office 会话已失效。", 401)
            actor = Identity(row["database"], row["company_id"], row["user"], row["version"], row["token"])
            await self._user(connection, actor)
            return actor

    async def logout(self, raw: str):
        async with self.engine.begin() as connection:
            await connection.execute(delete(sessions).where(sessions.c.token == _token_hash(raw)))

    async def revoke_sessions(self, actor: Identity, user: str):
        async with self.transaction(actor) as connection:
            await self._user(connection, actor, admin=True)
            await connection.execute(update(users).where(
                users.c.company == actor.tenant, users.c.user == user,
            ).values(version=users.c.version + 1))
            await self._audit(connection, actor, "sessions_revoked", target=user)

    async def _space(self, connection, actor: Identity, space_id: str, *, write=False, owner=False):
        row = (await connection.execute(select(spaces, members.c.role).join(
            members, members.c.space == spaces.c.id).where(
                spaces.c.company == actor.tenant, spaces.c.id == space_id,
                members.c.user == actor.user,
        ))).mappings().first()
        if row is None:
            raise OfficeError("office_space_missing", "工作区不存在或无访问权限。", 404)
        if owner and row["role"] != "owner":
            raise OfficeError("office_owner_required", "需要工作区负责人权限。")
        if write and (row["archived"] or row["role"] not in {"owner", "editor"}):
            raise OfficeError("office_space_readonly", "当前工作区只读。")
        return dict(row)

    async def space_access(self, actor: Identity, space_id: str, *, write=False):
        async with self.transaction(actor) as connection:
            return await self._space(connection, actor, space_id, write=write)

    async def spaces(self, actor: Identity):
        async with self.transaction(actor) as connection:
            rows = (await connection.execute(select(spaces, members.c.role).join(
                members, members.c.space == spaces.c.id).where(
                    spaces.c.company == actor.tenant, members.c.user == actor.user,
                ).order_by(spaces.c.name))).mappings()
            return [dict(row) for row in rows]

    async def company_spaces(self, actor: Identity):
        async with self.transaction(actor) as connection:
            await self._user(connection, actor, admin=True)
            rows = (await connection.execute(select(spaces).where(
                spaces.c.company == actor.tenant).order_by(spaces.c.name))).mappings()
            return [dict(row) for row in rows]

    async def limit_source_member(self, actor: Identity, space_id: str, source: str,
                                  user: str, tables: list[str] | None):
        async with self.transaction(actor) as connection:
            await self._space(connection, actor, space_id, owner=True)
            target = Identity(actor.database, actor.company, user)
            await self._user(connection, target)
            await self._space(connection, target, space_id)
            granted = await connection.scalar(select(source_grants.c.tables).where(
                source_grants.c.space == space_id, source_grants.c.source == source))
            if tables is not None and not set(tables).issubset(granted or []):
                raise OfficeError("office_source_table_denied", "成员范围须在工作区授权范围内。", 422)
            await connection.execute(delete(source_member_limits).where(
                source_member_limits.c.space == space_id, source_member_limits.c.source == source,
                source_member_limits.c.user == user))
            if tables is not None:
                await connection.execute(insert(source_member_limits).values(
                    space=space_id, source=source, user=user, tables=sorted(set(tables))))
            await self._audit(connection, actor, "source_member_limited",
                              space=space_id, source=source, target=user, tables=tables)

    async def create_space(self, actor: Identity, name: str, owner: str):
        async with self.transaction(actor) as connection:
            await self._user(connection, actor, admin=True)
            await self._user(connection, Identity(actor.database, actor.company, owner))
            value = dict(id=str(uuid4()), company=actor.tenant, name=_name(name),
                         personal_user=None, archived=False)
            await connection.execute(insert(spaces).values(**value))
            await connection.execute(insert(members).values(space=value["id"], user=owner, role="owner"))
            await self._audit(connection, actor, "space_created", space=value["id"], owner=owner)
            return value

    async def _require_other_owner(self, connection, actor: Identity, space_id: str, user: str):
        other = await connection.scalar(select(members.c.user).join(users,
            (users.c.user == members.c.user) & (users.c.company == actor.tenant),
        ).where(members.c.space == space_id, members.c.role == "owner",
                members.c.user != user, users.c.enabled.is_(True)))
        if other is None:
            raise OfficeError("office_last_owner", "请先将工作区移交给另一名有效负责人。", 409)

    async def set_member(self, actor: Identity, space_id: str, user: str, role: str | None):
        if role not in {None, "owner", "editor", "viewer"}:
            raise OfficeError("office_role_invalid", "角色无效。", 422)
        async with self.transaction(actor) as connection:
            space = await self._space(connection, actor, space_id, owner=True)
            if space["personal_user"] is not None:
                raise OfficeError("office_personal_members", "个人空间通过文件分享授权。")
            if role is not None:
                await self._user(connection, Identity(actor.database, actor.company, user))
            previous = await connection.scalar(select(members.c.role).where(
                members.c.space == space_id, members.c.user == user))
            if previous == "owner" and role != "owner":
                await self._require_other_owner(connection, actor, space_id, user)
            await connection.execute(delete(members).where(
                members.c.space == space_id, members.c.user == user))
            if role is not None:
                await connection.execute(insert(members).values(space=space_id, user=user, role=role))
            await self._audit(connection, actor, "membership_changed", space=space_id, target=user, role=role)

    async def list_members(self, actor: Identity, space_id: str):
        async with self.transaction(actor) as connection:
            await self._space(connection, actor, space_id, owner=True)
            rows = (await connection.execute(select(members.c.user, members.c.role, users.c.name).join(
                users, (users.c.user == members.c.user) & (users.c.company == actor.tenant),
            ).where(members.c.space == space_id))).mappings()
            return [dict(row) for row in rows]

    async def update_space(self, actor: Identity, space_id: str, *, name=None, archived=None):
        async with self.transaction(actor) as connection:
            space = await self._space(connection, actor, space_id, owner=True)
            if space["personal_user"] is not None:
                raise OfficeError("office_personal_settings", "个人空间不支持归档或重命名。")
            values = {}
            if name is not None:
                values["name"] = _name(name)
            if archived is not None:
                values["archived"] = bool(archived)
            if values:
                await connection.execute(update(spaces).where(spaces.c.id == space_id).values(**values))
                await self._audit(connection, actor, "space_updated", space=space_id, **values)

    async def grant_source(self, actor: Identity, space_id: str, source: str, tables: list[str]):
        if not source or len(source) > 64 or len(tables) > 10000 or any(
            not isinstance(table, str) or not table or len(table) > 256 for table in tables
        ):
            raise OfficeError("office_source_grant_invalid", "数据源授权范围无效。", 422)
        async with self.transaction(actor) as connection:
            await self._user(connection, actor, admin=True)
            exists = await connection.scalar(select(spaces.c.id).where(
                spaces.c.id == space_id, spaces.c.company == actor.tenant))
            if exists is None:
                raise OfficeError("office_space_missing", "工作区不存在。", 404)
            await connection.execute(delete(source_grants).where(
                source_grants.c.space == space_id, source_grants.c.source == source))
            if tables:
                await connection.execute(insert(source_grants).values(
                    space=space_id, source=source, tables=sorted(set(tables))))
            await self._audit(connection, actor, "source_granted" if tables else "source_revoked",
                              space=space_id, source=source, tables=tables)

    async def source_grant(self, actor: Identity, space_id: str, source: str):
        async with self.transaction(actor) as connection:
            await self._user(connection, actor, admin=True)
            exists = await connection.scalar(select(spaces.c.id).where(
                spaces.c.id == space_id, spaces.c.company == actor.tenant))
            if exists is None:
                raise OfficeError("office_space_missing", "工作区不存在。", 404)
            tables = await connection.scalar(select(source_grants.c.tables).where(
                source_grants.c.space == space_id, source_grants.c.source == source))
            return {"tables": tables or []}

    async def source_member_limits(self, actor: Identity, space_id: str, source: str):
        async with self.transaction(actor) as connection:
            await self._space(connection, actor, space_id, owner=True)
            granted = await connection.scalar(select(source_grants.c.tables).where(
                source_grants.c.space == space_id, source_grants.c.source == source))
            rows = (await connection.execute(select(source_member_limits.c.user,
                source_member_limits.c.tables).where(source_member_limits.c.space == space_id,
                source_member_limits.c.source == source))).mappings()
            return {"tables": granted or [], "items": [dict(row) for row in rows]}

    async def source_tables(self, actor: Identity, space_id: str, source: str):
        async with self.transaction(actor) as connection:
            return await self._source_tables(connection, actor, space_id, source)

    async def _source_tables(self, connection, actor: Identity, space_id: str, source: str):
        await self._space(connection, actor, space_id)
        granted = await connection.scalar(select(source_grants.c.tables).where(
            source_grants.c.space == space_id, source_grants.c.source == source))
        limit = await connection.scalar(select(source_member_limits.c.tables).where(
            source_member_limits.c.space == space_id, source_member_limits.c.source == source,
            source_member_limits.c.user == actor.user))
        effective = set(granted or [])
        if limit is not None:
            effective.intersection_update(limit)
        if not effective:
            raise OfficeError("office_source_denied", "没有此数据源的可用表权限。")
        return sorted(effective)

    async def _folder(self, connection, space_id: str, folder_id: str | None):
        if folder_id is None:
            return None
        row = (await connection.execute(select(folders).where(
            folders.c.id == folder_id, folders.c.space == space_id,
        ))).mappings().first()
        if row is None:
            raise OfficeError("office_folder_missing", "文件夹不存在。", 404)
        return dict(row)

    async def _unique_folder(self, connection, space_id, parent, name, exclude=None):
        existing = await connection.scalar(select(folders.c.id).where(
            folders.c.space == space_id, folders.c.parent == parent,
            folders.c.name == name, folders.c.id != (exclude or ""),
        ))
        if existing:
            raise OfficeError("office_folder_exists", "同一位置已存在同名文件夹。", 409)

    async def create_folder(self, actor: Identity, space_id: str, parent: str | None, name: str):
        name = _name(name)
        async with self.transaction(actor) as connection:
            await self._space(connection, actor, space_id, write=True)
            await self._folder(connection, space_id, parent)
            await self._unique_folder(connection, space_id, parent, name)
            value = dict(id=str(uuid4()), space=space_id, parent=parent, name=name)
            await connection.execute(insert(folders).values(**value))
            await self._audit(connection, actor, "folder_created", folder=value["id"], space=space_id)
            return value

    async def update_folder(self, actor: Identity, space_id: str, folder_id: str, **changes):
        if not changes.keys() <= {"name", "parent"}:
            raise OfficeError("office_input_invalid", "文件夹操作无效。", 422)
        async with self.transaction(actor) as connection:
            await self._space(connection, actor, space_id, write=True)
            folder = await self._folder(connection, space_id, folder_id)
            parent = changes.get("parent", folder["parent"])
            current = parent
            while current is not None:
                if current == folder_id:
                    raise OfficeError("office_folder_cycle", "无法移动到自身或子文件夹。", 409)
                current = (await self._folder(connection, space_id, current))["parent"]
            name = _name(changes.get("name", folder["name"]))
            await self._unique_folder(connection, space_id, parent, name, folder_id)
            await connection.execute(update(folders).where(folders.c.id == folder_id).values(
                parent=parent, name=name))
            await self._audit(connection, actor, "folder_updated", folder=folder_id)

    async def register_file(self, actor: Identity, space_id: str, folder: str | None,
                            name: str, format: str, document: str, revision: int, scope: dict, *, follow_existing=False,
                            copy_source: tuple[str, int] | None = None):
        """Only the trusted native importer may provide document identity and scope."""
        if format not in {"docx", "xlsx", "pptx", "pdf"} or revision < 1:
            raise OfficeError("office_file_invalid", "文件类型或修订无效。", 422)
        if scope.get("database") != actor.database or str(scope.get("companyId")) != actor.company:
            raise OfficeError("office_file_scope_invalid", "文件与当前公司不一致。")
        async with self.transaction(actor) as connection:
            existing = (await connection.execute(select(files).where(
                files.c.document == document))).mappings().first()
            if existing is not None:
                if follow_existing:
                    if existing["scope"] != scope or existing["format"] != format:
                        raise OfficeError("office_file_scope_invalid", "报告与已登记文件身份不一致。")
                    return await self._file(connection, actor, existing["id"])
                await self._space(connection, actor, space_id, write=True)
                await self._folder(connection, space_id, folder)
                if existing["space"] != space_id:
                    raise OfficeError("office_file_exists", "文件已登记在另一个空间。", 409)
                return dict(existing)
            await self._space(connection, actor, space_id, write=True)
            await self._folder(connection, space_id, folder)
            if copy_source:
                source = await self._file(connection, actor, copy_source[0], write=True)
                if (source['space'], source['folder'], source['version'], source['format']) != (
                        space_id, folder, copy_source[1], format):
                    raise OfficeError('office_version_conflict', '源文件已变化，请刷新后重试。', 409)
                existing_names = await connection.scalars(select(files.c.name).where(
                    files.c.space == space_id, files.c.folder == folder, files.c.deleted.is_(False),
                ))
                occupied = {item.casefold() for item in existing_names}
                stem = source['name'].rsplit('.', 1)[0]
                number = 1
                while True:
                    suffix = f' 副本{f" {number}" if number > 1 else ""}.{format}'
                    name = stem[:200 - len(suffix)] + suffix
                    if name.casefold() not in occupied:
                        break
                    number += 1
            value = dict(id=str(uuid4()), space=space_id, folder=folder, name=_name(name),
                         format=format, document=document, revision=revision, scope=scope,
                         version=1, deleted=False, created_by=actor.user)
            await connection.execute(insert(files).values(**value))
            await self._audit(connection, actor, "file_registered", file=value["id"], space=space_id)
            return value

    async def delete_folder(self, actor: Identity, space_id: str, folder_id: str):
        async with self.transaction(actor) as connection:
            await self._space(connection, actor, space_id, write=True)
            await self._folder(connection, space_id, folder_id)
            rows = (await connection.execute(select(folders.c.id, folders.c.parent).where(
                folders.c.space == space_id))).all()
            removed = {folder_id}
            while True:
                children = {row.id for row in rows if row.parent in removed} - removed
                if not children:
                    break
                removed.update(children)
            affected = (await connection.execute(select(files.c.id).where(
                files.c.space == space_id, files.c.folder.in_(removed), files.c.deleted.is_(False),
            ))).scalars().all()
            if affected:
                await connection.execute(delete(file_search_text).where(file_search_text.c.file.in_(affected)))
                await connection.execute(update(files).where(files.c.id.in_(affected)).values(
                    deleted=True, version=files.c.version + 1))
            await connection.execute(delete(folders).where(
                folders.c.space == space_id, folders.c.id.in_(removed)))
            await self._audit(connection, actor, "folder_deleted", space=space_id,
                              folder=folder_id, folders=len(removed), files=len(affected))
            return {"folders": len(removed), "files": len(affected)}

    async def _file(self, connection, actor: Identity, file_id: str, *, write=False):
        row = (await connection.execute(select(files).where(
            files.c.id == file_id, files.c.deleted.is_(False)))).mappings().first()
        if row is None:
            raise OfficeError("office_file_missing", "文件不存在。", 404)
        await self._space(connection, actor, row["space"], write=write)
        return dict(row)

    async def file(self, actor: Identity, file_id: str, *, write=False):
        async with self.transaction(actor) as connection:
            return await self._file(connection, actor, file_id, write=write)

    async def owns_document(self, document: str) -> bool:
        """Internal guard: even deleted Office files must reject unscoped native grants."""
        async with self.engine.connect() as connection:
            return await connection.scalar(select(files.c.id).where(files.c.document == document)) is not None

    async def library(self, actor: Identity, space_id: str):
        async with self.transaction(actor) as connection:
            await self._space(connection, actor, space_id)
            folder_rows = (await connection.execute(select(folders).where(
                folders.c.space == space_id).order_by(folders.c.name))).mappings()
            folder_list = [dict(row) for row in folder_rows]
            file_rows = (await connection.execute(select(
                files, file_preferences.c.starred, file_preferences.c.seen, file_preferences.c.favorite_group,
            ).outerjoin(file_preferences,
                (files.c.id == file_preferences.c.file) & (file_preferences.c.user == actor.user),
            ).where(files.c.space == space_id, files.c.deleted.is_(False)))).mappings()
            entries = []
            for row in file_rows:
                value = dict(row)
                value.pop("scope")
                value["starred"] = bool(value["starred"])
                value["favoriteGroup"] = value.pop("favorite_group")
                value["recentHidden"] = value["seen"] == _RECENT_HIDDEN
                value["seen"] = 0 if value["recentHidden"] else (value["seen"] or 0)
                entries.append(value)
            return {"folders": folder_list, "files": entries}

    async def search_batch(self, actor: Identity, space: str, after: str, limit: int, *, file_ids=None):
        async with self.transaction(actor) as connection:
            await self._space(connection, actor, space)
            statement = (select(files.c.id, files.c.revision, files.c.format, files.c.name,
                                                   files.c.folder, file_search_text.c.body)
                .outerjoin(file_search_text, (file_search_text.c.file == files.c.id)
                           & (file_search_text.c.revision == files.c.revision))
                .where(files.c.space == space, files.c.deleted.is_(False), files.c.id > after)
                .order_by(files.c.id).limit(limit))
            if file_ids is not None:
                statement = statement.where(files.c.id.in_(file_ids))
            rows = await connection.execute(statement)
            entries = [dict(row) for row in rows.mappings()]
            if not any(entry['folder'] for entry in entries):
                return entries
            tree = {row.id: (row.name, row.parent) for row in await connection.execute(select(
                folders.c.id, folders.c.name, folders.c.parent,
            ).where(folders.c.space == space))}
            for entry in entries:
                names, seen = [], set()
                folder = entry['folder']
                while folder in tree and folder not in seen:
                    seen.add(folder)
                    name, folder = tree[folder]
                    names.append(name)
                entry['folder_path'] = '/'.join(reversed(names))
            return entries

    async def record_search_text(self, actor: Identity, space: str, file_id: str, revision: int, body: str):
        async with self.transaction(actor) as connection:
            entry = await self._file(connection, actor, file_id)
            if entry['space'] != space or entry['revision'] != revision:
                return
            indexed = await connection.scalar(select(file_search_text.c.revision).where(file_search_text.c.file == file_id))
            if indexed == revision:
                return
            await connection.execute(delete(file_search_text).where(file_search_text.c.file == file_id))
            await connection.execute(insert(file_search_text).values(file=file_id, revision=revision, body=body))

    async def search_revisions(self, actor: Identity, space: str, file_ids: list[str]):
        async with self.transaction(actor) as connection:
            await self._space(connection, actor, space)
            rows = await connection.execute(select(files.c.id, files.c.revision).where(
                files.c.space == space, files.c.deleted.is_(False), files.c.id.in_(file_ids),
            ))
            return dict(rows.tuples().all())

    async def _preference(self, connection, actor: Identity, file_id: str, **values):
        previous = (await connection.execute(select(file_preferences).where(
            file_preferences.c.file == file_id, file_preferences.c.user == actor.user,
        ))).mappings().first()
        if previous:
            await connection.execute(update(file_preferences).where(
                file_preferences.c.file == file_id, file_preferences.c.user == actor.user,
            ).values(**values))
        else:
            initial = dict(file=file_id, user=actor.user, starred=False, seen=0)
            initial.update(values)
            await connection.execute(insert(file_preferences).values(**initial))

    async def favorite(self, actor: Identity, file_id: str, starred: bool):
        async with self.transaction(actor) as connection:
            await self._file(connection, actor, file_id)
            values = {"starred": starred}
            if not starred:
                values["favorite_group"] = None
            await self._preference(connection, actor, file_id, **values)

    async def bulk_files(self, actor: Identity, space: str, versions: dict[str, int], action: str,
                         *, destination: str | None = None, folder: str | None = None, group: str | None = None):
        if action not in {'star', 'unstar', 'delete', 'move', 'hide_recent', 'group'} or (action == 'move' and not destination):
            raise OfficeError('office_input_invalid', '批量操作无效。', 422)
        if group is not None:
            group = group.strip()
            if action != 'group' or not 1 <= len(group) <= 80:
                raise OfficeError('office_input_invalid', '收藏分组名称无效。', 422)
        async with self.transaction(actor) as connection:
            await self._space(connection, actor, space, write=action in {'delete', 'move'})
            rows = await connection.execute(select(files.c.id, files.c.version).where(
                files.c.space == space, files.c.deleted.is_(False), files.c.id.in_(versions),
            ))
            if dict(rows.tuples().all()) != versions:
                raise OfficeError('office_version_conflict', '所选文件已变化，请刷新后重试。', 409)
            if action == 'delete':
                await connection.execute(delete(file_search_text).where(file_search_text.c.file.in_(versions)))
                await connection.execute(update(files).where(files.c.id.in_(versions)).values(
                    deleted=True, version=files.c.version + 1))
                await self._audit(connection, actor, 'files_deleted', files=list(versions), space=space)
            elif action == 'move':
                await self._space(connection, actor, destination, write=True)
                await self._folder(connection, destination, folder)
                await connection.execute(update(files).where(files.c.id.in_(versions)).values(
                    space=destination, folder=folder, version=files.c.version + 1))
                await self._audit(connection, actor, 'files_moved', files=list(versions), space=space,
                                  destination=destination, folder=folder)
            elif action == 'group':
                result = await connection.execute(update(file_preferences).where(
                    file_preferences.c.file.in_(versions), file_preferences.c.user == actor.user,
                    file_preferences.c.starred.is_(True),
                ).values(favorite_group=group))
                if result.rowcount != len(versions):
                    raise OfficeError('office_favorites_changed', '所选收藏已变化，请刷新后重试。', 409)
            else:
                preferences = {'seen': _RECENT_HIDDEN} if action == 'hide_recent' else {'starred': action == 'star'}
                if action == 'unstar':
                    preferences['favorite_group'] = None
                for file_id in versions:
                    await self._preference(connection, actor, file_id, **preferences)
            return {'count': len(versions)}

    async def touch(self, actor: Identity, file_id: str):
        async with self.transaction(actor) as connection:
            await self._file(connection, actor, file_id)
            await self._preference(connection, actor, file_id, seen=int(self.clock() * 1000))

    async def update_file(self, actor: Identity, file_id: str, *, expected_version: int, **changes):
        if not changes.keys() <= {"name", "folder", "deleted", "space"}:
            raise OfficeError("office_input_invalid", "文件操作无效。", 422)
        async with self.transaction(actor) as connection:
            value = await self._file(connection, actor, file_id, write=True)
            if value["version"] != expected_version:
                raise OfficeError("office_version_conflict", "文件已变化，请刷新后重试。", 409)
            if "name" in changes:
                changes["name"] = _name(changes["name"])
            destination = changes.get("space", value["space"])
            if destination != value["space"]:
                await self._space(connection, actor, destination, write=True)
                changes.setdefault("folder", None)
            if "folder" in changes:
                await self._folder(connection, destination, changes["folder"])
            await connection.execute(update(files).where(files.c.id == file_id).values(
                **changes, version=expected_version + 1))
            if changes.get('deleted'):
                await connection.execute(delete(file_search_text).where(file_search_text.c.file == file_id))
            await self._audit(connection, actor, "file_updated", file=file_id, changes=changes)

    async def record_revision(self, actor: Identity, file_id: str, document: str, revision: int):
        async with self.transaction(actor) as connection:
            entry = await self._file(connection, actor, file_id, write=True)
            if entry["document"] != document:
                raise OfficeError("office_document_mismatch", "文件修订身份不一致。")
            if revision > entry["revision"]:
                await connection.execute(delete(file_search_text).where(file_search_text.c.file == file_id))
                await connection.execute(update(files).where(files.c.id == file_id).values(
                    revision=revision, version=files.c.version + 1))
                await self._audit(connection, actor, "revision_saved", file=file_id, revision=revision)
                return {**entry, 'revision': revision}
            return entry

    async def knowledge_conversations(self, actor: Identity, space_id: str):
        async with self.transaction(actor) as connection:
            await self._space(connection, actor, space_id)
            turns = knowledge_turns.c
            partition = {"partition_by": turns.conversation}
            ranked = select(
                turns.conversation.label("id"), turns.question,
                func.row_number().over(**partition, order_by=(turns.created, turns.id)).label("rank"),
                func.max(turns.created).over(**partition).label("recent"),
            ).where(turns.space == space_id, turns.user == actor.user).subquery()
            rows = await connection.execute(select(ranked.c.id, ranked.c.question)
                .where(ranked.c.rank == 1).order_by(ranked.c.recent.desc(), ranked.c.id))
            return [dict(id=row.id, title=" ".join(row.question.split())[:60]) for row in rows]

    async def delete_knowledge_conversation(self, actor: Identity, space_id: str, conversation: str):
        async with self.transaction(actor) as connection:
            await self._space(connection, actor, space_id)
            turns = knowledge_turns.c
            removed = await connection.execute(delete(knowledge_turns).where(
                turns.space == space_id, turns.user == actor.user, turns.conversation == conversation,
            ))
            if removed.rowcount:
                await connection.execute(insert(knowledge_deleted).values(
                    space=space_id, user=actor.user, conversation=conversation,
                ))

    async def knowledge_history(self, actor: Identity, space_id: str, *, conversation="default"):
        async with self.transaction(actor) as connection:
            await self._space(connection, actor, space_id)
            rows = (await connection.execute(select(knowledge_turns).where(
                knowledge_turns.c.space == space_id, knowledge_turns.c.user == actor.user,
                knowledge_turns.c.conversation == conversation,
            ).order_by(knowledge_turns.c.created.desc(), knowledge_turns.c.id.desc()).limit(30))).mappings().all()
            result = []
            for row in reversed(rows):
                value = dict(row)
                for citation in value['sources']:
                    try:
                        entry = await self._file(connection, actor, citation['fileId'])
                        starred = await connection.scalar(select(file_preferences.c.starred).where(
                            file_preferences.c.file == entry['id'], file_preferences.c.user == actor.user))
                        if (not starred and citation.get('attachment') is not True) or entry['space'] != space_id:
                            raise OfficeError('office_knowledge_changed', '收藏范围已变化。')
                    except OfficeError:
                        value['answer'] = '来源文件权限或收藏范围已变化，此回答不再显示。'
                        value['citations'] = []
                        value['sources'] = []
                        break
                result.append(value)
            return result

    async def save_knowledge_turn(self, actor: Identity, space_id: str, question: str,
                                  answer: str, citations: list[dict], sources: list[dict], *, conversation="default"):
        async with self.transaction(actor) as connection:
            await self._space(connection, actor, space_id)
            deleted = knowledge_deleted.c
            if await connection.scalar(select(deleted.conversation).where(
                deleted.space == space_id, deleted.user == actor.user, deleted.conversation == conversation,
            )):
                raise OfficeError("office_knowledge_conversation_deleted", "会话已删除，请新建对话。", 409)
            for citation in sources:
                entry = await self._file(connection, actor, citation['fileId'])
                starred = await connection.scalar(select(file_preferences.c.starred).where(
                    file_preferences.c.file == entry['id'], file_preferences.c.user == actor.user))
                if ((not starred and citation.get('attachment') is not True)
                        or entry['space'] != space_id or entry['revision'] != citation['revision']):
                    raise OfficeError('office_knowledge_changed', '文件或收藏范围已变化，请重新提问。', 409)
            value = dict(id=str(uuid4()), space=space_id, user=actor.user, question=question,
                         answer=answer, citations=citations, sources=sources, conversation=conversation, created=int(self.clock() * 1000))
            await connection.execute(insert(knowledge_turns).values(**value))
            await self._audit(connection, actor, 'knowledge_answered', space=space_id,
                              turn=value['id'], files=[item['fileId'] for item in citations])
            return value
