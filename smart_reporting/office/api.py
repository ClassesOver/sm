from __future__ import annotations

import base64
import hashlib
import hmac
import re
from uuid import uuid4
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import UploadFile

from asyncio import FIRST_COMPLETED, create_task, gather, to_thread, wait
from pwdlib import PasswordHash
from ..http.request_limits import install_streaming_body_limit, RequestBodyLimitError
from ..reporting.models import ReportingError
from .repository import Identity, OfficeError, OfficeRepository
from .provider_catalog import Capability, ProviderInput, ProviderTestInput

COOKIE = "genoffice_session"


def csrf_token(raw: str) -> str:
    return hmac.new(raw.encode(), b"genoffice-csrf-v1", hashlib.sha256).hexdigest()


def check_office_origin(request: Request, public_origin: str | None) -> None:
    configured = urlsplit(public_origin or "")
    if (configured.scheme not in {"http", "https"} or not configured.netloc
            or request.headers.get("origin") != f"{configured.scheme}://{configured.netloc}"):
        raise OfficeError("office_origin_invalid", "请求来源无效。")


class OfficeRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                if request.method not in {'GET', 'HEAD', 'OPTIONS'} and not request.headers.get('content-type', '').startswith('multipart/form-data'):
                    install_streaming_body_limit(request, 29 * 1024 * 1024 if self.path == "/office/api/admin/providers/{capability}/test" else 512 * 1024)
                response = await original(request)
            except RequestValidationError as error:
                # FastAPI's default response echoes the invalid input, including
                # credentials and source connection parameters.
                response = JSONResponse({"code": "office_input_invalid",
                    "message": "请求内容无效，请检查填写的字段。",
                    "detail": [{"loc": item["loc"], "type": item["type"]} for item in error.errors()],
                }, status_code=422)
            except OfficeError as error:
                response = JSONResponse(
                    {"code": error.code, "message": error.message}, status_code=error.status)
            except RequestBodyLimitError as error:
                response = JSONResponse({"code": error.code, "message": "上传请求过大。"},
                                        status_code=error.status_code)
            except ReportingError as error:
                status = 403 if error.code == "native_permission_denied" else (
                    404 if error.code.endswith("not_found") else (
                        409 if error.code.endswith("conflict") else 422))
                response = JSONResponse({"code": error.code, "message": error.message}, status_code=status)
            response.headers["Cache-Control"] = "no-store"
            return response
        return handler


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")



class SearchRerank(Input):
    query: str = Field(min_length=1, max_length=160)
    candidates: dict[str, int] = Field(min_length=2, max_length=20)


class BulkFiles(Input):
    action: Literal['star', 'unstar', 'delete', 'move', 'hide_recent', 'group']
    versions: dict[str, int] = Field(min_length=1, max_length=500)
    group: str | None = Field(default=None, max_length=80)
    destination: str | None = Field(default=None, min_length=1, max_length=36)
    folder: str | None = Field(default=None, min_length=1, max_length=36)


class CopyFile(Input):
    expectedVersion: int = Field(ge=1, strict=True)
    requestId: str = Field(min_length=1, max_length=128)


class LoginInput(Input):
    database: str = Field(min_length=1, max_length=256)
    company: str = Field(min_length=1, max_length=256)
    user: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=256)


class UserInput(Input):
    password: str = Field(min_length=12, max_length=256)
    user: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=200)


class PasswordReset(Input):
    password: str = Field(min_length=12, max_length=256)


class UserPatch(Input):
    role: Literal["admin", "user"] | None = None
    enabled: bool | None = None


class SpaceInput(Input):
    name: str = Field(min_length=1, max_length=200)
    owner: str = Field(min_length=1, max_length=256)


class SpacePatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    archived: bool | None = None


class MemberInput(Input):
    role: Literal["owner", "editor", "viewer"] | None


class FolderInput(Input):
    name: str = Field(min_length=1, max_length=200)
    parent: str | None = Field(default=None, max_length=36)


class FolderPatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent: str | None = Field(default=None, max_length=36)


class FilePatch(Input):
    expectedVersion: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    folder: str | None = Field(default=None, max_length=36)
    space: str | None = Field(default=None, min_length=36, max_length=36)
    deleted: bool | None = None


class FavoriteInput(Input):
    starred: bool


class OpenInput(Input):
    revision: int | None = Field(default=None, ge=1)


class KnowledgeInput(Input):
    question: str = Field(min_length=1, max_length=8000)
    conversation: str = Field(default="default", min_length=1, max_length=36, pattern=r"^[a-zA-Z0-9-]+$")
    attachmentIds: list[str] = Field(default_factory=list, max_length=10)


class PersonalSettingsInput(Input):
    theme: Literal['system', 'light', 'dark']
    disabledSkills: list[str] = Field(default_factory=list, max_length=1000)
    expectedVersion: int = Field(ge=0, strict=True)

class ImageGenerationInput(Input):
    prompt: str = Field(min_length=1, max_length=1000)


class GlobalSettingsInput(Input):
    modelId: str = Field(default='', max_length=200, pattern=r'^[^\s]*$')
    imageModel: str = Field(default='', max_length=200, pattern=r'^[^\s]*$')
    searchEnabled: bool = True
    integrationsEnabled: bool = True
    expectedVersion: int = Field(ge=0, strict=True)


def create_office_router(
    office: OfficeRepository, *, public_origin: str | None, cookie_secure=True,
    documents=None,
    source_vault=None, metadata_client=None,
    knowledge=None,
) -> APIRouter:
    router = APIRouter(route_class=OfficeRoute, prefix="/office/api")
    def origin(request: Request):
        check_office_origin(request, public_origin)

    async def actor(request: Request) -> Identity:
        raw = request.cookies.get(COOKIE, "")
        identity = await office.authenticate(raw)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin(request)
            if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), csrf_token(raw)):
                raise OfficeError("office_csrf_invalid", "请求校验失败，请刷新。")
        return identity

    from .settings import OfficeSettings
    settings_service = OfficeSettings(office)
    from .provider_settings import OfficeProviders
    office.providers = OfficeProviders(office, source_vault)

    @router.post('/media/images')
    async def generate_office_image(body: ImageGenerationInput, identity: Identity = Depends(actor)):
        content, media_type, _extension = await office.providers.generate(identity, body.prompt)
        return {'mediaType': media_type, 'previewDataUrl': f'data:{media_type};base64,{base64.b64encode(content).decode()}',
                'sha256': hashlib.sha256(content).hexdigest()}

    @router.get('/admin/providers')
    async def provider_settings(identity: Identity = Depends(actor)):
        return await office.providers.catalog(identity)

    @router.put('/admin/providers/{capability}')
    async def save_provider(capability: Capability, body: ProviderInput, identity: Identity = Depends(actor)):
        return await office.providers.save(identity, capability, body.model_dump())

    @router.post('/admin/providers/{capability}/test')
    async def test_provider(capability: Capability, body: ProviderTestInput, identity: Identity = Depends(actor)):
        return await office.providers.test(identity, capability, body.model_dump(exclude={'media'}), body.media)


    @router.get('/settings')
    async def personal_settings(identity: Identity = Depends(actor)):
        return await settings_service.personal(identity)

    @router.put('/settings')
    async def save_personal_settings(body: PersonalSettingsInput, identity: Identity = Depends(actor)):
        return await settings_service.save(identity, body.model_dump(exclude={'expectedVersion'}), body.expectedVersion)

    @router.get('/admin/settings')
    async def global_settings(identity: Identity = Depends(actor)):
        return await settings_service.global_settings(identity)

    @router.put('/admin/settings')
    async def save_global_settings(body: GlobalSettingsInput, identity: Identity = Depends(actor)):
        return await settings_service.save(identity, body.model_dump(exclude={'expectedVersion'}), body.expectedVersion, global_settings=True)

    @router.post("/session")
    async def login(body: LoginInput, request: Request):
        origin(request)
        identity = Identity(body.database, body.company, body.user)
        token = await office.login(identity, body.password)
        await office.logout(request.cookies.get(COOKIE, ""))
        response = JSONResponse({"user": await office.me(identity), "csrfToken": csrf_token(token)})
        response.set_cookie(COOKIE, token, httponly=True, secure=cookie_secure,
                            samesite="lax", path="/", max_age=3600)
        return response

    @router.get("/session")
    async def current(request: Request, identity: Identity = Depends(actor)):
        return {"user": await office.me(identity),
                "csrfToken": csrf_token(request.cookies[COOKIE])}

    @router.post("/logout")
    async def logout(request: Request, identity: Identity = Depends(actor)):
        await office.logout(request.cookies[COOKIE])
        response = JSONResponse({"loggedOut": True})
        response.delete_cookie(COOKIE, path="/", secure=cookie_secure, httponly=True, samesite="lax")
        return response

    @router.get("/admin/users")
    async def list_users(identity: Identity = Depends(actor)):
        return {"items": await office.list_users(identity)}

    @router.post("/admin/users", status_code=201)
    async def provision(body: UserInput, identity: Identity = Depends(actor)):
        password_hash = await to_thread(PasswordHash.recommended().hash, body.password)
        await office.provision(identity, body.user, body.name, password_hash=password_hash)
        return {"created": True}

    @router.patch("/admin/users/{user}")
    async def update_user(user: str, body: UserPatch, identity: Identity = Depends(actor)):
        await office.update_user(identity, user, **body.model_dump(exclude_none=True))
        return {"updated": True}

    @router.put("/admin/users/{user}/password")
    async def reset_password(user: str, body: PasswordReset, identity: Identity = Depends(actor)):
        if (await office.me(identity))["role"] != "admin":
            raise OfficeError("office_admin_required", "需要公司管理员权限。")
        password_hash = await to_thread(PasswordHash.recommended().hash, body.password)
        await office.reset_password(identity, user, password_hash)
        return {"updated": True}

    @router.post("/admin/users/{user}/revoke-sessions")
    async def revoke(user: str, identity: Identity = Depends(actor)):
        await office.revoke_sessions(identity, user)
        return {"revoked": True}

    @router.get("/workspaces")
    async def list_spaces(identity: Identity = Depends(actor)):
        return {"items": await office.spaces(identity)}

    @router.get("/admin/workspaces")
    async def company_spaces(identity: Identity = Depends(actor)):
        return {"items": await office.company_spaces(identity)}

    @router.post("/workspaces", status_code=201)
    async def create_space(body: SpaceInput, identity: Identity = Depends(actor)):
        return await office.create_space(identity, body.name, body.owner)

    @router.patch("/workspaces/{space}")
    async def update_space(space: str, body: SpacePatch, identity: Identity = Depends(actor)):
        await office.update_space(identity, space, **body.model_dump(exclude_none=True))
        return {"updated": True}

    @router.get("/workspaces/{space}/members")
    async def list_members(space: str, identity: Identity = Depends(actor)):
        return {"items": await office.list_members(identity, space)}

    @router.put("/workspaces/{space}/members/{user}")
    async def set_member(space: str, user: str, body: MemberInput, identity: Identity = Depends(actor)):
        await office.set_member(identity, space, user, body.role)
        return {"updated": True}

    @router.get("/workspaces/{space}/library")
    async def library(space: str, identity: Identity = Depends(actor)):
        return await office.library(identity, space)

    @router.post('/workspaces/{space}/files/bulk')
    async def bulk_files(space: str, body: BulkFiles, identity: Identity = Depends(actor)):
        if any(not 1 <= len(file_id) <= 36 or version < 1 for file_id, version in body.versions.items()):
            raise OfficeError('office_input_invalid', '批量文件身份无效。', 422)
        return await office.bulk_files(identity, space, body.versions, body.action,
                                       destination=body.destination, folder=body.folder, group=body.group)

    if documents is not None:
        from .search import OfficeSearch

        search = getattr(documents, 'search', None) or OfficeSearch(office, documents)

        @router.get("/workspaces/{space}/search")
        async def search_files(space: str, q: str = Query(min_length=1, max_length=160),
                               after: str = Query(default='', max_length=36), identity: Identity = Depends(actor)):
            if not q.strip():
                return {'hits': [], 'after': None, 'corpus': {'documents': 0, 'totalLength': 0, 'documentFrequencies': []}}
            if not (await settings_service.global_settings(identity, require_admin=False))['searchEnabled']:
                raise OfficeError('office_search_disabled', '管理员已关闭搜索。')
            return await search.page(identity, space, q, after)

        @router.post("/workspaces/{space}/search/rerank")
        async def rerank_search(space: str, body: SearchRerank, identity: Identity = Depends(actor)):
            if any(not 1 <= len(file_id) <= 36 or revision < 1 for file_id, revision in body.candidates.items()):
                raise OfficeError('office_search_candidates_invalid', '搜索结果已变更，请重新搜索。', 422)
            if not (await settings_service.global_settings(identity, require_admin=False))['searchEnabled']:
                raise OfficeError('office_search_disabled', '管理员已关闭搜索。')
            return {'order': await search.rerank(identity, space, body.query, body.candidates)}

    @router.post("/workspaces/{space}/folders", status_code=201)
    async def create_folder(space: str, body: FolderInput, identity: Identity = Depends(actor)):
        return await office.create_folder(identity, space, body.parent, body.name)

    @router.patch("/workspaces/{space}/folders/{folder}")
    async def update_folder(space: str, folder: str, body: FolderPatch, identity: Identity = Depends(actor)):
        changes = body.model_dump(exclude_unset=True)
        if "name" in changes and changes["name"] is None:
            raise OfficeError("office_name_invalid", "文件夹名称不能为空。", 422)
        await office.update_folder(identity, space, folder, **changes)
        return {"updated": True}

    @router.patch("/files/{file}")
    async def update_file(file: str, body: FilePatch, identity: Identity = Depends(actor)):
        changes = body.model_dump(exclude_unset=True)
        version = changes.pop("expectedVersion")
        if any(changes.get(key) is None for key in ("name", "deleted", "space") if key in changes):
            raise OfficeError("office_input_invalid", "文件字段不能为空。", 422)
        await office.update_file(identity, file, expected_version=version, **changes)
        return {"updated": True}

    @router.delete("/workspaces/{space}/folders/{folder}")
    async def delete_folder(space: str, folder: str, identity: Identity = Depends(actor)):
        return await office.delete_folder(identity, space, folder)

    @router.put("/files/{file}/favorite")
    async def favorite(file: str, body: FavoriteInput, identity: Identity = Depends(actor)):
        await office.favorite(identity, file, body.starred)
        return {"updated": True}

    @router.post("/workspaces/{space}/files", status_code=201)
    async def upload(space: str, request: Request, identity: Identity = Depends(actor)):
        if documents is None:
            raise OfficeError("office_documents_unavailable", "文件服务尚未配置。", 503)
        await office.space_access(identity, space, write=True)
        install_streaming_body_limit(request, 24 * 1024 * 1024 + 64 * 1024)
        async with request.form(max_files=1, max_fields=2, max_part_size=1024) as form:
            uploaded = form.get("file")
            request_id = form.get("requestId")
            folder = form.get("folder") or None
            if (not isinstance(uploaded, UploadFile) or not isinstance(request_id, str)
                    or not 0 < len(request_id) <= 256
                    or (folder is not None and not isinstance(folder, str))):
                raise OfficeError("office_upload_invalid", "上传参数无效。", 422)
            content = await uploaded.read(24 * 1024 * 1024 + 1)
            if len(content) > 24 * 1024 * 1024:
                raise OfficeError("office_file_too_large", "文件超过 24 MiB。", 413)
            return await documents.import_file(
                identity, space, folder, uploaded.filename or "未命名", content, request_id)

    @router.post("/files/{file}/open")
    async def open_file(file: str, body: OpenInput | None = None, identity: Identity = Depends(actor)):
        if documents is None:
            raise OfficeError("office_documents_unavailable", "文件服务尚未配置。", 503)
        return await documents.open(identity, file, revision=body.revision if body else None)

    @router.post('/files/{file}/copy')
    async def copy_file(file: str, body: CopyFile, identity: Identity = Depends(actor)):
        if documents is None:
            raise OfficeError('office_documents_unavailable', '文件服务尚未配置。', 503)
        return await documents.duplicate_file(identity, file, body.expectedVersion, body.requestId)

    @router.get('/workspaces/{space}/knowledge/conversations')
    async def knowledge_conversations(space: str, identity=Depends(actor)):
        return {'items': await office.knowledge_conversations(identity, space)}

    @router.delete('/workspaces/{space}/knowledge/conversations')
    async def knowledge_delete(space: str, conversation: str = Query(min_length=1, max_length=36,
                               pattern=r"^[a-zA-Z0-9-]+$"), identity=Depends(actor)):
        await office.delete_knowledge_conversation(identity, space, conversation)
        return {'deleted': True}

    @router.get('/workspaces/{space}/knowledge')
    async def knowledge_history(space: str, conversation: str = Query("default", min_length=1, max_length=36,
                                pattern=r"^[a-zA-Z0-9-]+$"), identity=Depends(actor)):
        return {'items': await office.knowledge_history(identity, space, conversation=conversation)}

    @router.post('/workspaces/{space}/knowledge')
    async def knowledge_ask(space: str, body: KnowledgeInput, request: Request, identity=Depends(actor)):
        if knowledge is None:
            raise OfficeError('office_knowledge_unavailable', '知识问答尚未配置。', 503)
        async def wait_for_disconnect():
            while (await request.receive())["type"] != "http.disconnect":
                pass

        answer = create_task(knowledge.ask(identity, space, body.question,
            attachment_ids=body.attachmentIds, conversation=body.conversation))
        disconnected = create_task(wait_for_disconnect())
        try:
            done, _ = await wait((answer, disconnected), return_when=FIRST_COMPLETED)
            if answer in done:
                return await answer
            return JSONResponse({"code": "office_knowledge_cancelled", "message": "已停止问答。"}, status_code=499)
        finally:
            for task in (answer, disconnected):
                if not task.done():
                    task.cancel()
            await gather(answer, disconnected, return_exceptions=True)

    @router.post('/workspaces/{space}/knowledge/{turn}/docx', status_code=201)
    async def knowledge_docx(space: str, turn: str, conversation: str = Query("default", min_length=1, max_length=36,
                             pattern=r"^[a-zA-Z0-9-]+$"), identity=Depends(actor)):
        if documents is None:
            raise OfficeError("office_documents_unavailable", "文件服务尚未配置。", 503)
        await office.space_access(identity, space, write=True)

        async def current_answer():
            history = await office.knowledge_history(identity, space, conversation=conversation)
            answer = next((item for item in history if item["id"] == turn and item["sources"]), None)
            if answer is None:
                raise OfficeError("office_knowledge_answer_unavailable", "回答已删除或来源不可访问。", 404)
            return answer

        from .knowledge_docx import render_knowledge_docx
        answer = await current_answer()
        name = re.sub(r'[^\w -]', '_', ' '.join(answer["question"].split())[:60]).strip(' _')
        content = await to_thread(render_knowledge_docx, answer["answer"])
        await current_answer()
        return await documents.import_file(identity, space, None, (name or "知识问答") + ".docx", content, str(uuid4()))

    if source_vault is not None:
        from .source_api import mount_source_routes
        mount_source_routes(router, actor, office, source_vault, metadata_client)
    return router
