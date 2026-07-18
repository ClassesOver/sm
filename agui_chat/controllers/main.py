# -*- coding: utf-8 -*-
import base64
import json
import logging
import hashlib
import os

from odoo import http
from odoo.exceptions import AccessError, ValidationError
from odoo.http import content_disposition, request

from ..models.agui_chat_config import COMMAND_CATALOG_HASH, MODULE_VERSION, PROTOCOL
from ..models.agui_chat_mention import MentionTokenError
from ..models.agui_chat_tool import business_tool_catalog
from ..models.agui_chat_workspace import issue_workspace_capability


_logger = logging.getLogger(__name__)

ALLOWED_ATTACHMENT_TYPES = {
    "image/png": "image",
    "image/jpeg": "image",
    "image/webp": "image",
    "application/pdf": "document",
    "text/plain": "document",
    "text/csv": "document",
    "application/csv": "document",
    "application/vnd.ms-excel": "document",
    "application/json": "document",
    "application/jsonl": "document",
    "application/x-ndjson": "document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "document",
}
REPORT_ATTACHMENT_SUFFIXES = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
}
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024


def _attachment_type(mime_type, filename):
    mime_type = str(mime_type or "application/octet-stream").lower()
    modality = ALLOWED_ATTACHMENT_TYPES.get(mime_type)
    if modality:
        return mime_type, modality
    suffix = os.path.splitext(str(filename or ""))[1].lower()
    if mime_type == "application/octet-stream" and suffix in REPORT_ATTACHMENT_SUFFIXES:
        return REPORT_ATTACHMENT_SUFFIXES[suffix], "document"
    return mime_type, False


class ChatSessionNotFound(ValueError):
    pass


class AguiChatController(http.Controller):
    @http.route("/agui_chat/config", type="json", auth="user")
    def config(self):
        config = request.env["agui.chat.config"].sudo().get_active_config()
        return {
            "protocol": PROTOCOL,
            "module_version": MODULE_VERSION,
            "bundle_version": MODULE_VERSION,
            "command_catalog_hash": COMMAND_CATALOG_HASH,
            "chat_enabled": bool(config.chat_enabled),
            "host_tools_enabled": bool(config.host_tools_enabled),
            "write_tools_enabled": bool(config.write_tools_enabled),
            "enabled_commands": config.enabled_command_names(),
            "business_tools": business_tool_catalog(request.env, config) if (
                config.host_tools_enabled
            ) else [],
            "sensitive_fields": config.sensitive_fields(),
            "runtime_url": config.public_runtime_url(),
            "runtime_config_url": config.public_runtime_config_url(),
            "allow_cross_origin_dev": bool(config.allow_cross_origin_dev),
            "credentials": "include" if config.allow_cross_origin_dev else "same-origin",
            "default_agent_id": config.default_agent_id or False,
            "limits": {
                "request_bytes": config.max_request_bytes,
                "messages": config.max_messages,
                "sse_event_bytes": config.max_sse_event_bytes,
            },
            "tool_policy": {"default": "deny", "generic_rpc": False},
            "user_id": request.env.user.id,
            "user_name": request.env.user.name,
            "database": request.session.db,
        }

    @http.route("/agui_chat/attachment/upload", type="http", auth="user", methods=["POST"], csrf=False)
    def attachment_upload(self, **kwargs):
        try:
            session = self._load_session(kwargs.get("chat_session_id"))
            upload = request.httprequest.files.get("file")
            if not upload:
                raise ValueError("未提供附件。")
            mime_type, modality = _attachment_type(upload.mimetype, upload.filename)
            if not modality:
                raise ValueError("不支持此附件类型。")
            content = upload.read(MAX_ATTACHMENT_SIZE + 1)
            if len(content) > MAX_ATTACHMENT_SIZE:
                raise ValueError("附件大小超过 10 MB。")
            attachment = request.env["ir.attachment"].sudo().create({
                "name": upload.filename or "attachment",
                "datas_fname": upload.filename or "attachment",
                "mimetype": mime_type,
                "datas": base64.b64encode(content),
                "res_model": "agui.chat.session",
                "res_id": session.id,
            })
            return self._json_response({
                "attachment": self._attachment_ref(attachment, modality),
            })
        except (ValueError, AccessError) as error:
            return self._json_response({"error": str(error)}, status=400)

    @http.route("/agui_chat/attachment/<int:attachment_id>", type="http", auth="user", methods=["GET"])
    def attachment_read(self, attachment_id, **kwargs):
        try:
            attachment = self._load_attachment(attachment_id)
        except (ValueError, AccessError) as error:
            return self._json_response({"error": str(error)}, status=403)
        content = base64.b64decode(attachment.datas or b"")
        return request.make_response(content, headers=[
            ("Content-Type", attachment.mimetype or "application/octet-stream"),
            ("Content-Disposition", content_disposition(
                attachment.name or "attachment",
            ).replace("attachment;", "inline;", 1)),
            ("X-Content-Type-Options", "nosniff"),
        ])

    @http.route("/agui_chat/attachment/delete", type="http", auth="user", methods=["POST"], csrf=False)
    def attachment_delete(self, **kwargs):
        try:
            payload = json.loads(request.httprequest.data.decode("utf-8") or "{}")
            attachment = self._load_attachment(payload.get("attachment_id"))
            attachment.sudo().unlink()
            return self._json_response({"ok": True})
        except (ValueError, AccessError) as error:
            return self._json_response({"error": str(error)}, status=403)

    @http.route("/agui_chat/session/list", type="json", auth="user")
    def session_list(self, limit=20):
        sessions = request.env["agui.chat.session"].search([
            ("active", "=", True), ("protocol", "=", PROTOCOL),
        ], limit=min(max(self._safe_int(limit, 20), 1), 100))
        return {
            "ok": True,
            "sessions": [session.to_client(include_payload=False) for session in sessions],
        }

    @http.route("/agui_chat/session/create", type="json", auth="user")
    def session_create(self, name=None, surface=None, agent_id=None):
        session = request.env["agui.chat.session"]._create_session(
            name=name, surface=surface, agent_id=agent_id,
        )
        return {"ok": True, "session": session.to_client()}

    @http.route("/agui_chat/session/get", type="json", auth="user")
    def session_get(self, session_id):
        session = self._load_session(session_id)
        return {"ok": True, "session": session.to_client()}

    @http.route("/agui_chat/session/save", type="json", auth="user")
    def session_save(self, session_id=None, values=None, expected_session_revision=None):
        values = values if isinstance(values, dict) else {}
        if session_id:
            try:
                session = self._load_session(session_id)
            except ChatSessionNotFound:
                return {"ok": False, "error": "session_not_found"}
        else:
            session = request.env["agui.chat.session"]._create_session(
                name=values.get("name"),
                surface=values.get("surface"),
                agent_id=values.get("agent_id"),
            )
            if expected_session_revision is None:
                expected_session_revision = 0
        return session._save_from_client(values, expected_session_revision)

    @http.route("/agui_chat/session/archive", type="json", auth="user")
    def session_archive(self, session_id):
        session = self._load_session(session_id)
        session.sudo().write({"active": False})
        request.env["agui.chat.sandbox.cleanup"]._enqueue([session.thread_id])
        return {"ok": True}

    @http.route("/agui_chat/workspace/capability", type="json", auth="user")
    def workspace_capability(self, session_id):
        try:
            session = self._load_session(session_id)
            token, claims = issue_workspace_capability(
                request.env, session, getattr(request.session, "sid", ""),
            )
            return {
                "ok": True,
                "capability": token,
                "threadId": session.thread_id,
                "expiresAt": claims["exp"],
            }
        except (AccessError, ValueError, ValidationError) as error:
            return {
                "ok": False,
                "code": "workspace_capability_rejected",
                "error": str(error),
            }

    @http.route("/agui_chat/mention/search", type="json", auth="user")
    def mention_search(self, query="", scope="all", model_scope=None,
                       current_model=None, recent_models=None, current_filter=None):
        try:
            return request.env["agui.chat.mention.token"]._search_mentions(
                query, scope, model_scope, current_model,
                recent_models if isinstance(recent_models, list) else [],
                current_filter, self._session_key(),
            )
        except (AccessError, MentionTokenError, ValueError) as error:
            return {
                "ok": False,
                "code": getattr(error, "code", "mention_search_rejected"),
                "error": str(error),
            }

    @http.route("/agui_chat/mention/bind", type="json", auth="user")
    def mention_bind(self, candidate_token, action):
        try:
            reference = request.env["agui.chat.mention.token"]._bind_mention(
                candidate_token, action, self._session_key(),
            )
            return {"ok": True, "reference": reference}
        except (AccessError, MentionTokenError, ValueError) as error:
            return {
                "ok": False,
                "code": getattr(error, "code", "mention_bind_rejected"),
                "error": str(error),
            }

    @http.route("/agui_chat/mention/read", type="json", auth="user")
    def mention_read(self, tokens, authorization_token):
        try:
            authorization = self._load_authorization(authorization_token)
            if authorization.tool_name != "odoo.read_mentioned_records" or authorization.state != "executing":
                raise MentionTokenError("authorization_invalid", "读取授权无效。")
            stored = json.loads(authorization.arguments_json or "{}")
            if stored.get("tokens") != tokens:
                raise MentionTokenError("authorization_payload_mismatch", "读取授权与引用不匹配。")
            return request.env["agui.chat.mention.token"]._read_tokens(
                tokens, self._session_key(),
            )
        except (AccessError, MentionTokenError, ValueError) as error:
            return {
                "ok": False,
                "code": getattr(error, "code", "mention_read_rejected"),
                "error": str(error),
            }

    @http.route("/agui_chat/host_command", type="json", auth="user")
    def host_command(self, phase, call=None, authorization_id=None, approved=False, result=None):
        try:
            authorizations = request.env["agui.chat.tool.authorization"].with_context(
                agui_session_key=self._session_key()
            )
            if phase == "prepare":
                return authorizations._prepare_host_command(call)
            authorization = self._load_authorization(authorization_id)
            if phase == "confirm":
                return authorization._transition(bool(approved))
            if phase == "complete":
                return authorization._complete(result if isinstance(result, dict) else {})
            if phase == "undo_prepare":
                return authorization._prepare_undo()
            if phase == "undo_execute":
                return authorization._begin_undo_execution()
            return {"ok": False, "code": "unsupported_phase"}
        except (ValueError, AccessError, ValidationError) as error:
            return {"ok": False, "code": "host_command_rejected", "error": str(error)}
        except Exception:
            _logger.exception("AG-UI host command policy failed")
            return {"ok": False, "code": "host_command_failed"}

    @http.route("/agui_chat/business/prepare", type="json", auth="user")
    def business_prepare(self, call):
        try:
            return request.env["agui.chat.tool.authorization"].with_context(
                agui_session_key=self._session_key()
            )._prepare_business_command(call)
        except (ValueError, AccessError, ValidationError) as error:
            return {
                "ok": False,
                "code": "business_command_rejected",
                "error": str(error),
            }
        except Exception:
            _logger.exception("AG-UI business command preparation failed")
            return {"ok": False, "code": "business_command_failed"}

    @http.route("/agui_chat/business/execute", type="json", auth="user")
    def business_execute(self, command_name, payload, authorization_token, idempotency_key):
        try:
            return request.env["agui.chat.command.execution"].with_context(
                agui_session_key=self._session_key(),
                agui_odoo_session=str(getattr(request.session, "sid", "") or ""),
            )._execute_named(
                command_name,
                payload,
                authorization_token,
                idempotency_key,
            )
        except (ValueError, AccessError, ValidationError) as error:
            return {"ok": False, "code": "business_command_rejected", "error": str(error)}
        except Exception:
            _logger.exception("AG-UI business command failed")
            return {"ok": False, "code": "business_command_failed"}

    def _json_response(self, payload, status=200):
        response = request.make_response(
            json.dumps(payload), headers=[("Content-Type", "application/json")]
        )
        response.status_code = status
        return response

    def _attachment_ref(self, attachment, modality=None):
        mime_type = attachment.mimetype or "application/octet-stream"
        return {
            "id": str(attachment.id),
            "name": attachment.name,
            "mimeType": mime_type,
            "size": attachment.file_size,
            "modality": modality or ALLOWED_ATTACHMENT_TYPES.get(mime_type),
        }

    def _load_attachment(self, attachment_id):
        try:
            attachment_id = int(attachment_id)
        except (TypeError, ValueError):
            raise ValueError("附件 ID 无效。")
        attachment = request.env["ir.attachment"].sudo().browse(attachment_id).exists()
        if not attachment or attachment.res_model != "agui.chat.session":
            raise ValueError("未找到附件。")
        self._load_session(attachment.res_id)
        return attachment

    def _load_authorization(self, token):
        authorization = request.env["agui.chat.tool.authorization"].search([
            ("token", "=", token),
            ("user_id", "=", request.env.user.id),
            ("company_id", "=", request.env.user.company_id.id),
        ], limit=1)
        if not authorization:
            raise ValueError("未找到命令授权。")
        return authorization

    def _load_session(self, session_id):
        try:
            session_id = int(session_id)
        except (TypeError, ValueError):
            raise ValueError("对话会话 ID 无效。")
        session = request.env["agui.chat.session"].search([
            ("id", "=", session_id), ("protocol", "=", PROTOCOL),
            ("active", "=", True),
        ], limit=1)
        if not session:
            raise ChatSessionNotFound("未找到对话会话。")
        return session

    def _safe_int(self, value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _session_key(self):
        sid = str(getattr(request.session, "sid", "") or "")
        return hashlib.sha256(sid.encode("utf-8")).hexdigest()
