# -*- coding: utf-8 -*-
import json
import uuid
from copy import deepcopy

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .agui_chat_config import PROTOCOL


MAX_MESSAGES_BYTES = 2 * 1024 * 1024
MAX_AGENT_STATE_BYTES = 512 * 1024
MAX_UI_PREFERENCES_BYTES = 64 * 1024


class AguiChatSession(models.Model):
    _name = "agui.chat.session"
    _description = "AG-UI 对话会话"
    _order = "write_date desc, id desc"

    name = fields.Char(string="会话名称", required=True, default="新对话")
    active = fields.Boolean(string="有效", default=True)
    protocol = fields.Char(string="协议", required=True, default=PROTOCOL, index=True, readonly=True)
    user_id = fields.Many2one(
        "res.users", string="用户", required=True, default=lambda self: self.env.user,
        index=True, ondelete="cascade",
    )
    thread_id = fields.Char(string="线程 ID", required=True, index=True, default=lambda self: str(uuid.uuid4()))
    parent_session_id = fields.Many2one(
        "agui.chat.session", string="父会话", readonly=True, index=True,
        ondelete="set null",
    )
    agent_id = fields.Char(string="智能体 ID")
    surface = fields.Selection(
        [("dock", "停靠窗口"), ("standalone", "浮动窗口")],
        string="界面模式", default="dock", required=True,
    )
    messages_json = fields.Text(string="消息数据", default="[]")
    agent_state_json = fields.Text(string="智能体状态", default="{}")
    ui_preferences_json = fields.Text(string="界面偏好", default="{}")
    session_revision = fields.Integer(string="会话版本", default=0)

    _sql_constraints = [
        ("thread_id_unique", "unique(thread_id)", "AG-UI 线程 ID 必须唯一。"),
    ]

    @api.model
    def _json_loads(self, value, default):
        if not value:
            return default
        try:
            return json.loads(value)
        except ValueError:
            return default

    @api.model
    def _json_dumps(self, value, limit, default):
        payload = json.dumps(
            value if value is not None else default,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if len(payload.encode("utf-8")) > limit:
            raise ValidationError("对话会话数据超过存储上限。")
        return payload

    @api.model
    def _create_session(self, name=None, surface=None, agent_id=None):
        session = self.sudo().create({
            "name": (name or "新对话")[:256],
            "surface": surface if surface in ("dock", "standalone") else "dock",
            "agent_id": agent_id or False,
            "user_id": self.env.user.id,
            "protocol": PROTOCOL,
        })
        return self.browse(session.id)

    def to_client(self, include_payload=True):
        self.ensure_one()
        result = {
            "id": self.id,
            "name": self.name,
            "thread_id": self.thread_id,
            "parent_session_id": self.parent_session_id.id or False,
            "agent_id": self.agent_id or False,
            "surface": self.surface,
            "active": self.active,
            "protocol": self.protocol,
            "write_date": fields.Datetime.to_string(self.write_date) if self.write_date else False,
            "sessionRevision": self.session_revision,
        }
        if include_payload:
            result.update({
                "messages": self._json_loads(self.messages_json, []),
                "agentState": self._json_loads(self.agent_state_json, {}),
                "uiPreferences": self._json_loads(self.ui_preferences_json, {}),
            })
        return result

    def unlink(self):
        self.check_access_rights("unlink")
        self.check_access_rule("unlink")
        self.env["agui.chat.sandbox.cleanup"]._enqueue(self.mapped("thread_id"))
        attachments = self.env["ir.attachment"].sudo().search([
            ("res_model", "=", self._name),
            ("res_id", "in", self.ids),
        ])
        result = super(AguiChatSession, self).unlink()
        attachments.unlink()
        return result

    def _save_from_client(self, values, expected_session_revision):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT session_revision, active FROM agui_chat_session WHERE id = %s FOR UPDATE",
            (self.id,),
        )
        row = self.env.cr.fetchone()
        if not row or not row[1]:
            return {"ok": False, "error": "session_not_found"}
        self.invalidate_cache([
            "name", "thread_id", "agent_id", "surface", "user_id",
            "messages_json", "agent_state_json", "ui_preferences_json",
            "session_revision",
        ])
        current_revision = row[0]
        try:
            expected = int(expected_session_revision)
        except (TypeError, ValueError):
            expected = -1
        if expected != current_revision:
            return {
                "ok": False,
                "error": "session_revision_conflict",
                "sessionRevision": current_revision,
                "session": self.to_client(include_payload=False),
            }

        vals = {"session_revision": current_revision + 1}
        values = values if isinstance(values, dict) else {}
        if values.get("name"):
            vals["name"] = values["name"][:256]
        if values.get("surface") in ("dock", "standalone"):
            vals["surface"] = values["surface"]
        if "agent_id" in values:
            vals["agent_id"] = values.get("agent_id") or False
        if "messages" in values:
            vals["messages_json"] = self._json_dumps(
                values.get("messages"), MAX_MESSAGES_BYTES, []
            )
        if "agentState" in values:
            vals["agent_state_json"] = self._json_dumps(
                values.get("agentState"), MAX_AGENT_STATE_BYTES, {}
            )
        if "uiPreferences" in values:
            vals["ui_preferences_json"] = self._json_dumps(
                values.get("uiPreferences"), MAX_UI_PREFERENCES_BYTES, {}
            )
        self.sudo().write(vals)
        return {"ok": True, "session": self.to_client()}

    @api.model
    def _attachment_ids_in_messages(self, messages):
        result = set()
        for message in messages if isinstance(messages, list) else []:
            if not isinstance(message, dict):
                continue
            for attachment in message.get("attachments") or []:
                if not isinstance(attachment, dict):
                    continue
                try:
                    result.add(int(attachment.get("id")))
                except (TypeError, ValueError):
                    continue
        return result

    @api.model
    def _rewrite_attachment_ids(self, messages, attachment_ids):
        result = deepcopy(messages)
        for message in result:
            if not isinstance(message, dict):
                continue
            for attachment in message.get("attachments") or []:
                if not isinstance(attachment, dict):
                    continue
                try:
                    source_id = int(attachment.get("id"))
                except (TypeError, ValueError):
                    continue
                if source_id in attachment_ids:
                    attachment["id"] = str(attachment_ids[source_id])
        return result

    def _fork_from_client(self, target_message_id, source_run_id,
                          expected_session_revision):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT session_revision, active FROM agui_chat_session "
            "WHERE id = %s FOR UPDATE",
            (self.id,),
        )
        row = self.env.cr.fetchone()
        if not row or not row[1]:
            return {"ok": False, "error": "session_not_found"}
        self.invalidate_cache([
            "name", "thread_id", "agent_id", "surface", "user_id",
            "messages_json", "agent_state_json", "ui_preferences_json",
            "session_revision",
        ])
        try:
            expected = int(expected_session_revision)
        except (TypeError, ValueError):
            expected = -1
        if expected != row[0]:
            return {
                "ok": False,
                "error": "session_revision_conflict",
                "sessionRevision": row[0],
                "session": self.to_client(include_payload=False),
            }

        messages = self._json_loads(self.messages_json, [])
        target_index = -1
        for index, message in enumerate(messages):
            extra_data = message.get("extra_data") if isinstance(message, dict) else None
            if (
                isinstance(message, dict)
                and message.get("id") == target_message_id
                and message.get("role") in ("assistant", "agent")
                and isinstance(extra_data, dict)
                and extra_data.get("agent_run_id") == source_run_id
            ):
                target_index = index
                break
        if target_index < 0:
            return {"ok": False, "error": "branch_target_not_found"}

        target = messages[target_index]
        pending_statuses = {"pending", "running", "needs_confirmation"}
        pending_tools = any(
            isinstance(tool, dict) and tool.get("status") in pending_statuses
            for tool in target.get("tool_calls") or []
        )
        later_same_run = any(
            isinstance(message, dict)
            and message.get("role") in ("assistant", "agent")
            and isinstance(message.get("extra_data"), dict)
            and message["extra_data"].get("agent_run_id") == source_run_id
            for message in messages[target_index + 1:]
        )
        if (
            not target.get("content") or target.get("streaming_error")
            or pending_tools or later_same_run
        ):
            return {"ok": False, "error": "branch_target_not_final"}

        retained_messages = messages[:target_index]
        branch = self.sudo().create({
            "name": ("%s（分支）" % self.name)[:256],
            "parent_session_id": self.id,
            "agent_id": self.agent_id or False,
            "surface": self.surface,
            "user_id": self.user_id.id,
            "protocol": PROTOCOL,
            "agent_state_json": self.agent_state_json or "{}",
            "ui_preferences_json": self.ui_preferences_json or "{}",
        })

        try:
            referenced_ids = self._attachment_ids_in_messages(retained_messages)
            attachment_map = {}
            if referenced_ids:
                attachments = self.env["ir.attachment"].sudo().search([
                    ("id", "in", list(referenced_ids)),
                    ("res_model", "=", self._name),
                    ("res_id", "=", self.id),
                ])
                if set(attachments.ids) != referenced_ids:
                    branch.unlink()
                    return {"ok": False, "error": "branch_attachment_invalid"}
                for attachment in attachments:
                    copied = attachment.copy({"res_id": branch.id})
                    attachment_map[attachment.id] = copied.id

            retained_messages = self._rewrite_attachment_ids(
                retained_messages, attachment_map,
            )
            branch.sudo().write({
                "messages_json": self._json_dumps(
                    retained_messages, MAX_MESSAGES_BYTES, [],
                ),
            })
        except Exception:
            if branch.exists():
                branch.unlink()
            raise
        return {
            "ok": True,
            "session": branch.to_client(),
            "branch": {
                "sourceThreadId": self.thread_id,
                "sourceRunId": source_run_id,
                "targetMessageId": target_message_id,
            },
        }

    @api.model
    def _archive_for_protocol_upgrade(self):
        sessions = self.sudo().search([("active", "=", True)])
        if sessions:
            sessions.write({"active": False})
            self.env["agui.chat.sandbox.cleanup"]._enqueue(
                sessions.mapped("thread_id"),
            )
        return sessions.ids
