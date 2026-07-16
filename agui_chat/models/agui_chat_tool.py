# -*- coding: utf-8 -*-
import hashlib
import json
import re
import uuid
from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import api, fields, models

from .agui_chat_config import HOST_COMMAND_NAMES, PROTOCOL


WRITE_COMMANDS = {
    "odoo.patch_current_form",
    "odoo.save_current_form",
    "odoo.discard_current_form",
}
CONFIRMATION_COMMANDS = {
    "odoo.save_current_form",
    "odoo.discard_current_form",
}
RELATION_FIELD_TYPES = {"many2one", "many2many"}
UNDO_FIELD_TYPES = {
    "boolean", "char", "date", "datetime", "float", "html", "integer",
    "many2many", "many2one", "monetary", "selection", "text",
}
SECRET_KEYS = re.compile(r"(cookie|session|token|secret|password|api[_-]?key)", re.I)
MAX_ARGUMENT_BYTES = 64 * 1024
MAX_RESULT_BYTES = 128 * 1024
MAX_HOST_RESULT_BYTES = 512 * 1024
BUSINESS_COMMANDS = {}


def canonical_json(value):
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def payload_hash(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_host_arguments(tool_name, arguments):
    normalized = dict(arguments) if isinstance(arguments, dict) else {}
    domain = normalized.get("domain")
    if (
        tool_name == "odoo.apply_filter" and
        isinstance(domain, list) and len(domain) == 3 and
        isinstance(domain[0], str) and isinstance(domain[1], str)
    ):
        normalized["domain"] = [domain]
    patch = normalized.get("patch")
    if tool_name != "odoo.patch_current_form" or not isinstance(patch, str):
        return normalized
    try:
        patch = json.loads(patch)
    except ValueError:
        raise ValueError("表单 patch 必须是 JSON 对象或数组。")
    if not isinstance(patch, (dict, list)):
        raise ValueError("表单 patch 必须是 JSON 对象或数组。")
    normalized["patch"] = patch
    return normalized


def redact(value, depth=0):
    if depth > 5:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            str(key): "[redacted]" if SECRET_KEYS.search(str(key)) else redact(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return value[:2000]
    return value


def register_business_command(name, schema, handler):
    if not name.startswith("odoo.business.") or not callable(handler):
        raise ValueError("业务命令必须使用 odoo.business.* 名称并提供可调用处理器。")
    BUSINESS_COMMANDS[name] = {"schema": schema or {}, "handler": handler}


class AguiChatToolPolicy(models.Model):
    _name = "agui.chat.tool.policy"
    _description = "AG-UI 工具策略"
    _order = "sequence, id"

    name = fields.Char(string="策略名称", required=True)
    active = fields.Boolean(string="启用", default=True)
    sequence = fields.Integer(string="顺序", default=10)
    group_ids = fields.Many2many("res.groups", string="允许的用户组")
    tool_name = fields.Char(string="工具名称", required=True, help="填写一个已注册命令的完整名称。")
    access_level = fields.Selection([
        ("read", "读取"), ("navigation", "导航"), ("write", "写入"),
    ], string="访问级别", required=True, default="read")
    model_name = fields.Char(string="模型名称", help="可选，填写完整的 Odoo 模型技术名称。")
    field_names = fields.Char(string="允许的字段", help="可选，填写以逗号分隔的字段白名单。")
    confirmation_mode = fields.Selection([
        ("risk", "按风险确认"), ("always", "始终确认"), ("never", "无需确认"),
    ], string="确认模式", required=True, default="risk")
    high_risk_field_names = fields.Char(
        string="高风险字段", help="填写以逗号分隔、必须确认的字段名。",
    )

    @api.model
    def _patch_field_names(self, arguments):
        patch = arguments.get("patch") or {}
        if isinstance(patch, list):
            return {
                item.get("field") for item in patch
                if isinstance(item, dict) and item.get("field")
            }
        if isinstance(patch, dict):
            return set(patch.keys())
        return set()

    @api.model
    def _patch_risk(self, policy, model_name, field_names):
        reasons = []
        field_types = {}
        if len(field_names) > 1:
            reasons.append("multiple_fields")
        high_risk_fields = {
            item.strip() for item in (policy.high_risk_field_names or "").split(",")
            if item.strip()
        }
        if field_names.intersection(high_risk_fields):
            reasons.append("policy_high_risk_field")
        if field_names and model_name:
            definitions = self.env["ir.model.fields"].sudo().search([
                ("model", "=", model_name), ("name", "in", list(field_names)),
            ])
            field_types = {definition.name: definition.ttype for definition in definitions}
        if any(field_types.get(name) in RELATION_FIELD_TYPES for name in field_names):
            reasons.append("relation_field")
        if field_names and set(field_types.keys()) != field_names:
            reasons.append("field_type_unknown")
        return reasons, field_types

    @api.model
    def evaluate(self, tool_name, arguments):
        if tool_name not in HOST_COMMAND_NAMES and tool_name not in BUSINESS_COMMANDS:
            return {"allowed": False, "reason": "unsupported_command"}
        arguments = arguments if isinstance(arguments, dict) else {}
        target = arguments.get("target") if isinstance(arguments.get("target"), dict) else {}
        model_name = target.get("model") or arguments.get("model")
        field_names = self._patch_field_names(arguments)
        if arguments.get("field"):
            field_names.add(arguments.get("field"))
        user_groups = set(self.env.user.groups_id.ids)
        policies = self.sudo().search([("active", "=", True), ("tool_name", "=", tool_name)])
        policies = policies.filtered(
            lambda policy: not policy.model_name or policy.model_name == model_name
        )
        if not policies:
            return {
                "allowed": True,
                "requires_confirmation": False,
                "policy_id": False,
                "risk_reasons": [],
                "field_types": {},
            }
        mismatches = set()
        for policy in policies:
            if policy.group_ids and not user_groups.intersection(policy.group_ids.ids):
                mismatches.add("group_mismatch")
                continue
            allowed_fields = {
                item.strip() for item in (policy.field_names or "").split(",") if item.strip()
            }
            if allowed_fields and not field_names.issubset(allowed_fields):
                mismatches.add("field_mismatch")
                continue
            risk_reasons = []
            field_types = {}
            if tool_name == "odoo.patch_current_form":
                risk_reasons, field_types = self._patch_risk(
                    policy, model_name, field_names
                )
            elif tool_name in CONFIRMATION_COMMANDS:
                risk_reasons = ["destructive_command"]
            mode = policy.confirmation_mode or "risk"
            requires_confirmation = (
                mode == "always" or mode == "risk" and bool(risk_reasons)
            )
            return {
                "allowed": True,
                "requires_confirmation": requires_confirmation,
                "policy_id": policy.id,
                "risk_reasons": risk_reasons,
                "field_types": field_types,
            }
        return {
            "allowed": False,
            "reason": "policy_denied",
            "policy_mismatches": sorted(mismatches),
        }


class AguiChatToolAuthorization(models.Model):
    _name = "agui.chat.tool.authorization"
    _description = "AG-UI 绑定命令授权"
    _order = "create_date desc"

    token = fields.Char(string="授权令牌", required=True, index=True, default=lambda self: str(uuid.uuid4()))
    idempotency_key = fields.Char(string="幂等键", required=True, index=True)
    payload_hash = fields.Char(string="载荷摘要", required=True, index=True)
    user_id = fields.Many2one(
        "res.users", string="用户", required=True, default=lambda self: self.env.user, index=True
    )
    company_id = fields.Many2one(
        "res.company", string="公司", required=True, default=lambda self: self.env.user.company_id
    )
    tool_call_id = fields.Char(string="工具调用 ID", required=True, index=True)
    tool_name = fields.Char(string="工具名称", required=True)
    arguments_json = fields.Text(string="参数", default="{}")
    context_json = fields.Text(string="上下文", default="{}")
    result_json = fields.Text(string="结果", default="{}")
    preview_json = fields.Text(string="确认预览", default="{}")
    risk_reasons_json = fields.Text(string="风险原因", default="[]")
    policy_id = fields.Many2one("agui.chat.tool.policy", string="工具策略", ondelete="set null")
    authorization_kind = fields.Selection([
        ("command", "页面命令"), ("undo", "撤销"),
    ], string="授权类型", required=True, default="command", index=True)
    parent_authorization_id = fields.Many2one(
        "agui.chat.tool.authorization", string="原始授权", ondelete="cascade",
    )
    confirmation_required = fields.Boolean(string="需要确认", default=False)
    state = fields.Selection([
        ("pending", "待确认"), ("approved", "已批准"),
        ("executing", "执行中"), ("consumed", "已使用"),
        ("rejected", "已拒绝"), ("expired", "已过期"),
    ], string="状态", required=True, default="pending", index=True)
    expires_at = fields.Datetime(string="过期时间", required=True)

    _sql_constraints = [
        ("token_unique", "unique(token)", "授权令牌必须唯一。"),
        (
            "idempotency_key_unique", "unique(idempotency_key)",
            "命令授权幂等键必须唯一。",
        ),
    ]

    @api.model
    def _host_idempotency_key(self, call):
        context = call.get("context") if isinstance(call.get("context"), dict) else {}
        tool_call_id = str(call.get("id") or "")
        thread_id = str(context.get("threadId") or "")
        run_id = str(context.get("runId") or "")
        if not tool_call_id or not thread_id or not run_id:
            return False
        arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
        target = arguments.get("target") if isinstance(arguments.get("target"), dict) else {}
        material = "%s:%s:%s:%s:%s:%s:%s:%s" % (
            PROTOCOL, self.env.user.id, self.env.user.company_id.id,
            thread_id, run_id, tool_call_id,
            target.get("snapshotId") or "", target.get("hostRevision") or "",
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @api.model
    def _normalize_preview(self, preview, arguments):
        control = arguments.get("__control") if isinstance(arguments.get("__control"), dict) else {}
        if control:
            return {"control": redact({
                "type": control.get("type"),
                "label": str(control.get("label") or "")[:160],
                "recordLabel": str(control.get("recordLabel") or "")[:160],
            })}
        if not isinstance(preview, dict):
            return {}
        target = arguments.get("target") or {}
        preview_target = preview.get("target") if isinstance(preview.get("target"), dict) else {}
        binding_keys = (
            "snapshotId", "hostRevision", "controllerId", "dataPointId", "model", "resId",
        )
        if any(preview_target.get(key) != target.get(key) for key in binding_keys):
            return {}
        expected_fields = self.env["agui.chat.tool.policy"]._patch_field_names(arguments)
        changes = preview.get("changes") if isinstance(preview.get("changes"), list) else []
        preview_fields = {
            change.get("field") for change in changes
            if isinstance(change, dict) and change.get("field")
        }
        if preview_fields != expected_fields:
            return {}
        sensitive = set(
            self.env["agui.chat.config"].sudo().get_active_config().sensitive_fields()
        )
        normalized_changes = []
        for change in changes:
            item = dict(change)
            name = str(item.get("field") or "")
            is_sensitive = bool(item.get("sensitive")) or name in sensitive or SECRET_KEYS.search(name)
            item["sensitive"] = is_sensitive
            if is_sensitive:
                item["oldValue"] = "[redacted]"
                item["newValue"] = "[redacted]"
            normalized_changes.append(redact(item))
        return {
            "target": {key: target.get(key) for key in binding_keys},
            "changes": normalized_changes,
        }

    def _preview_with_risk(self):
        self.ensure_one()
        preview = json.loads(self.preview_json or "{}")
        reasons = json.loads(self.risk_reasons_json or "[]")
        preview["riskReasons"] = reasons
        field_types = {}
        if self.policy_id and self.tool_name == "odoo.patch_current_form":
            arguments = json.loads(self.arguments_json or "{}")
            _, field_types = self.env["agui.chat.tool.policy"]._patch_risk(
                self.policy_id,
                (arguments.get("target") or {}).get("model"),
                self.env["agui.chat.tool.policy"]._patch_field_names(arguments),
            )
        for change in preview.get("changes") or []:
            name = change.get("field")
            change["fieldType"] = change.get("fieldType") or field_types.get(name)
            change["riskReasons"] = list(reasons) if (
                len(preview.get("changes") or []) > 1 or
                field_types.get(name) in RELATION_FIELD_TYPES or
                "policy_high_risk_field" in reasons
            ) else []
        return preview

    @api.model
    def prepare_host_command(self, call):
        call = call if isinstance(call, dict) else {}
        tool_name = call.get("tool")
        try:
            arguments = normalize_host_arguments(tool_name, call.get("arguments"))
        except ValueError as error:
            return {"ok": False, "code": "invalid_arguments", "error": str(error)}
        config = self.env["agui.chat.config"].sudo().get_active_config()
        if not config.chat_enabled or not config.host_tools_enabled:
            return {"ok": False, "code": "host_tools_disabled"}
        if tool_name not in config.enabled_command_names():
            return {"ok": False, "code": "command_disabled"}
        control = arguments.get("__control") if isinstance(arguments.get("__control"), dict) else {}
        if tool_name == "odoo.activate_view_control":
            if control.get("type") not in ("open", "edit", "action", "object"):
                return {"ok": False, "code": "invalid_control_token"}
            control["label"] = str(control.get("label") or "")[:160]
            control["recordLabel"] = str(control.get("recordLabel") or "")[:160]
            arguments["__control"] = control
        else:
            arguments.pop("__control", None)
        if (tool_name in WRITE_COMMANDS or control.get("type") == "object") and not config.write_tools_enabled:
            return {"ok": False, "code": "write_tools_disabled"}
        if tool_name not in HOST_COMMAND_NAMES:
            return {"ok": False, "code": "unsupported_command"}
        target = arguments.get("target") if isinstance(arguments.get("target"), dict) else {}
        target_keys = {"snapshotId", "hostRevision"} if tool_name == "odoo.open_menu" else {
            "snapshotId", "hostRevision", "controllerId", "dataPointId", "model", "resId",
        }
        if not target_keys.issubset(set(target.keys())):
            return {"ok": False, "code": "invalid_target"}
        key = self._host_idempotency_key(call)
        if not key:
            return {"ok": False, "code": "missing_idempotency_context"}
        binding = {
            "tool": tool_name,
            "arguments": arguments,
            "id": str(call.get("id")),
            "message_id": call.get("message_id") or False,
            "context": call.get("context") or {},
            "preview": call.get("preview") or {},
        }
        binding_json = canonical_json(binding)
        if len(binding_json.encode("utf-8")) > MAX_ARGUMENT_BYTES:
            return {"ok": False, "code": "arguments_too_large"}
        preview = self._normalize_preview(call.get("preview"), arguments)
        binding_hash = payload_hash({
            "tool": tool_name, "arguments": arguments, "preview": preview,
        })
        existing = self.search([
            ("idempotency_key", "=", key),
            ("user_id", "=", self.env.user.id),
            ("company_id", "=", self.env.user.company_id.id),
        ], limit=1)
        if existing:
            return existing._existing_decision(binding_hash)
        decision = self.env["agui.chat.tool.policy"].evaluate(tool_name, arguments)
        if not decision.get("allowed"):
            self.env["agui.chat.tool.audit"].log(
                tool_name, "denied", details={
                    "reason": decision.get("reason"),
                    "policy_mismatches": decision.get("policy_mismatches") or [],
                    "arguments": arguments,
                },
                **self._audit_values(call)
            )
            return {"ok": False, "code": decision.get("reason") or "policy_denied"}
        if control.get("type") == "object":
            decision["requires_confirmation"] = True
            decision["risk_reasons"] = list(decision.get("risk_reasons") or []) + [
                "object_button"
            ]
        if decision.get("requires_confirmation") and tool_name == "odoo.patch_current_form" and not preview:
            return {"ok": False, "code": "preview_required"}
        expires_at = fields.Datetime.to_string(
            fields.Datetime.from_string(fields.Datetime.now()) + timedelta(minutes=5)
        )
        values = {
            "idempotency_key": key,
            "payload_hash": binding_hash,
            "tool_call_id": str(call.get("id")),
            "tool_name": tool_name,
            "arguments_json": canonical_json(arguments),
            "context_json": canonical_json(call.get("context") or {}),
            "policy_id": decision.get("policy_id") or False,
            "preview_json": canonical_json(preview),
            "risk_reasons_json": canonical_json(decision.get("risk_reasons") or []),
            "confirmation_required": bool(decision.get("requires_confirmation")),
            "state": "pending" if decision.get("requires_confirmation") else "approved",
            "expires_at": expires_at,
        }
        try:
            with self.env.cr.savepoint():
                authorization = self.create(values)
        except IntegrityError:
            authorization = self.search([
                ("idempotency_key", "=", key),
                ("user_id", "=", self.env.user.id),
                ("company_id", "=", self.env.user.company_id.id),
            ], limit=1)
            return authorization._existing_decision(binding_hash)
        self.env["agui.chat.tool.audit"].log(
            tool_name, "allowed", details={"arguments": arguments},
            authorization_id=authorization.id, **self._audit_values(call)
        )
        if decision.get("requires_confirmation"):
            return authorization._confirmation_decision()
        return authorization.begin_execution()

    def _existing_decision(self, binding_hash):
        self.ensure_one()
        if self.payload_hash != binding_hash:
            return {"ok": False, "code": "idempotency_payload_mismatch"}
        if self.state == "consumed":
            return {
                "ok": True,
                "authorization_id": self.token,
                "replay_result": self._json_result(),
            }
        if self.state == "pending":
            return self._confirmation_decision()
        if self.state == "approved":
            return self.begin_execution()
        if self.state == "executing":
            return {"ok": False, "code": "command_in_progress"}
        return {"ok": False, "code": "authorization_%s" % self.state}

    def _confirmation_decision(self):
        self.ensure_one()
        arguments = json.loads(self.arguments_json or "{}")
        return {
            "ok": False,
            "needs_confirmation": True,
            "authorization_id": self.token,
            "expires_at": self.expires_at,
            "operation": self.tool_name,
            "target": arguments.get("target") or {},
            "patch": arguments.get("patch") or {},
            "preview": self._preview_with_risk(),
            "risk_reasons": json.loads(self.risk_reasons_json or "[]"),
            "code": "confirmation_required",
        }

    def transition(self, approved):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT state, expires_at FROM agui_chat_tool_authorization WHERE id = %s FOR UPDATE",
            (self.id,),
        )
        state, expires_at = self.env.cr.fetchone()
        if state == "consumed":
            return {
                "ok": True,
                "authorization_id": self.token,
                "replay_result": self._json_result(),
            }
        if state == "executing":
            return {"ok": False, "code": "command_in_progress"}
        if state == "rejected" and not approved:
            return {"ok": False, "code": "authorization_rejected", "replay": True}
        if state != "pending":
            return {"ok": False, "code": "authorization_not_pending"}
        expires_at = (
            expires_at if hasattr(expires_at, "tzinfo")
            else fields.Datetime.from_string(expires_at)
        )
        if expires_at <= fields.Datetime.from_string(fields.Datetime.now()):
            self.write({"state": "expired"})
            return {"ok": False, "code": "authorization_expired"}
        if not approved:
            self.write({"state": "rejected"})
            return {"ok": False, "code": "authorization_rejected"}
        self.write({"state": "approved"})
        return self.begin_execution()

    def begin_execution(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT state, expires_at FROM agui_chat_tool_authorization WHERE id = %s FOR UPDATE",
            (self.id,),
        )
        state, expires_at = self.env.cr.fetchone()
        if state != "approved":
            return {"ok": False, "code": "authorization_invalid"}
        expires_at = (
            expires_at if hasattr(expires_at, "tzinfo")
            else fields.Datetime.from_string(expires_at)
        )
        if expires_at <= fields.Datetime.from_string(fields.Datetime.now()):
            self.write({"state": "expired"})
            return {"ok": False, "code": "authorization_expired"}
        self.write({"state": "executing"})
        return {
            "ok": True,
            "authorization_id": self.token,
            "confirmation_required": bool(self.confirmation_required),
            "preview": self._preview_with_risk(),
            "bound_call": {
                "id": self.tool_call_id,
                "tool": self.tool_name,
                "arguments": json.loads(self.arguments_json or "{}"),
                "context": json.loads(self.context_json or "{}"),
            },
        }

    def complete(self, result):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT state FROM agui_chat_tool_authorization WHERE id = %s FOR UPDATE",
            (self.id,),
        )
        state = self.env.cr.fetchone()[0]
        if state == "consumed":
            stored_result = self._json_result()
            if stored_result.get("code") == "result_too_large":
                return {"ok": False, "code": "result_too_large"}
            return {"ok": True, "replay_result": stored_result}
        if state != "executing":
            return {"ok": False, "code": "authorization_invalid"}
        result_json = canonical_json(result if isinstance(result, dict) else {})
        result_too_large = len(result_json.encode("utf-8")) > MAX_HOST_RESULT_BYTES
        if result_too_large:
            result_json = canonical_json({"ok": False, "code": "result_too_large"})
        self.write({"state": "consumed", "result_json": result_json})
        context = json.loads(self.context_json or "{}")
        arguments = json.loads(self.arguments_json or "{}")
        call = {"id": self.tool_call_id, "context": context, "arguments": arguments}
        self.env["agui.chat.tool.audit"].log(
            self.tool_name,
            "ok" if isinstance(result, dict) and result.get("ok") else "error",
            details=result,
            authorization_id=self.id,
            **self._audit_values(call)
        )
        if result_too_large:
            return {"ok": False, "code": "result_too_large"}
        return {"ok": True}

    def prepare_undo(self):
        self.ensure_one()
        if self.authorization_kind != "command" or self.tool_name != "odoo.patch_current_form" or self.state != "consumed":
            return {"ok": False, "code": "undo_unavailable"}
        result = self._json_result()
        undo = result.get("undo_payload") if isinstance(result, dict) else None
        if not result.get("ok") or not isinstance(undo, dict):
            return {"ok": False, "code": "undo_unavailable"}
        target = undo.get("target") if isinstance(undo.get("target"), dict) else {}
        patch = undo.get("patch") if isinstance(undo.get("patch"), dict) else {}
        expected = undo.get("expected") if isinstance(undo.get("expected"), dict) else {}
        field_names = set(patch.keys())
        if not field_names or field_names != set(expected.keys()):
            return {"ok": False, "code": "undo_unavailable"}
        definitions = self.env["ir.model.fields"].sudo().search([
            ("model", "=", target.get("model")), ("name", "in", list(field_names)),
        ])
        field_types = {definition.name: definition.ttype for definition in definitions}
        sensitive = set(
            self.env["agui.chat.config"].sudo().get_active_config().sensitive_fields()
        )
        if (
            set(field_types.keys()) != field_names or
            any(field_types[name] not in UNDO_FIELD_TYPES for name in field_names) or
            any(name in sensitive or SECRET_KEYS.search(name) for name in field_names)
        ):
            return {"ok": False, "code": "undo_unavailable"}
        arguments = {"target": target, "patch": patch, "expected": expected}
        policy = self.env["agui.chat.tool.policy"].evaluate(
            "odoo.patch_current_form", arguments
        )
        if not policy.get("allowed"):
            return {"ok": False, "code": "policy_denied"}
        key = hashlib.sha256(("undo:%s" % self.token).encode("utf-8")).hexdigest()
        existing = self.search([
            ("idempotency_key", "=", key),
            ("user_id", "=", self.env.user.id),
            ("company_id", "=", self.env.user.company_id.id),
        ], limit=1)
        if existing:
            return existing._undo_decision()
        expires_at = fields.Datetime.to_string(
            fields.Datetime.from_string(fields.Datetime.now()) + timedelta(minutes=10)
        )
        authorization = self.create({
            "idempotency_key": key,
            "payload_hash": payload_hash(arguments),
            "tool_call_id": "%s:undo" % self.tool_call_id,
            "tool_name": "odoo.undo_current_form",
            "arguments_json": canonical_json(arguments),
            "context_json": self.context_json or "{}",
            "policy_id": policy.get("policy_id") or False,
            "authorization_kind": "undo",
            "parent_authorization_id": self.id,
            "state": "approved",
            "expires_at": expires_at,
        })
        return authorization._undo_decision()

    def _undo_decision(self):
        self.ensure_one()
        if self.authorization_kind != "undo":
            return {"ok": False, "code": "undo_unavailable"}
        if self.state == "consumed":
            return {"ok": True, "replay_result": self._json_result()}
        if self.state == "executing":
            return {"ok": False, "code": "command_in_progress"}
        if self.state != "approved":
            return {"ok": False, "code": "undo_unavailable"}
        return {
            "ok": True,
            "undo_authorization_id": self.token,
            "expires_at": self.expires_at,
        }

    def begin_undo_execution(self):
        self.ensure_one()
        if self.authorization_kind != "undo":
            return {"ok": False, "code": "undo_unavailable"}
        if self.state == "consumed":
            return {"ok": True, "replay_result": self._json_result()}
        return self.begin_execution()

    def _json_result(self):
        self.ensure_one()
        try:
            return json.loads(self.result_json or "{}")
        except ValueError:
            return {"ok": False, "code": "stored_result_invalid"}

    @api.model
    def _audit_values(self, call):
        context = call.get("context") if isinstance(call.get("context"), dict) else {}
        arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
        target = arguments.get("target") if isinstance(arguments.get("target"), dict) else {}
        return {
            "request_id": context.get("requestId"),
            "run_id": context.get("runId"),
            "thread_id": context.get("threadId"),
            "tool_call_id": call.get("id") or False,
            "target_model": target.get("model") or arguments.get("model"),
            "target_record": str(target.get("resId") or arguments.get("resId") or "")[:128],
        }


class AguiChatCommandExecution(models.Model):
    _name = "agui.chat.command.execution"
    _description = "AG-UI 业务命令执行记录"
    _order = "create_date desc"

    user_id = fields.Many2one(
        "res.users", string="用户", required=True, default=lambda self: self.env.user, index=True
    )
    company_id = fields.Many2one(
        "res.company", string="公司", required=True, default=lambda self: self.env.user.company_id
    )
    command_name = fields.Char(string="命令名称", required=True, index=True)
    idempotency_key = fields.Char(string="幂等键", required=True, index=True)
    payload_hash = fields.Char(string="载荷摘要", required=True, index=True)
    authorization_id = fields.Many2one(
        "agui.chat.tool.authorization", string="命令授权", required=True, ondelete="restrict"
    )
    state = fields.Selection([
        ("running", "执行中"), ("success", "成功"), ("error", "失败"),
    ], string="状态", required=True, default="running", index=True)
    result_json = fields.Text(string="结果", default="{}")
    error_code = fields.Char(string="错误代码")

    _sql_constraints = [
        (
            "business_idempotency_unique",
            "unique(user_id, company_id, command_name, idempotency_key)",
            "同一用户和公司下的业务命令幂等键必须唯一。",
        ),
    ]

    @api.model
    def execute_named(self, command_name, payload, authorization_token, idempotency_key):
        payload = payload if isinstance(payload, dict) else {}
        spec = BUSINESS_COMMANDS.get(command_name)
        config = self.env["agui.chat.config"].sudo().get_active_config()
        if not spec or command_name not in config.enabled_business_command_names():
            return {"ok": False, "code": "unsupported_business_command"}
        validation = self._validate_schema(payload, spec.get("schema") or {}, "payload")
        if validation:
            return {"ok": False, "code": "schema_validation_failed", "error": validation}
        value_hash = payload_hash(payload)
        authorization = self.env["agui.chat.tool.authorization"].search([
            ("token", "=", authorization_token),
            ("user_id", "=", self.env.user.id),
            ("company_id", "=", self.env.user.company_id.id),
            ("tool_name", "=", command_name),
        ], limit=1)
        if not authorization or authorization.payload_hash != value_hash:
            return {"ok": False, "code": "authorization_invalid"}
        existing = self.search([
            ("user_id", "=", self.env.user.id),
            ("company_id", "=", self.env.user.company_id.id),
            ("command_name", "=", command_name),
            ("idempotency_key", "=", idempotency_key),
        ], limit=1)
        if existing:
            if existing.payload_hash != value_hash:
                return {"ok": False, "code": "idempotency_payload_mismatch"}
            return existing._stored_result()
        try:
            with self.env.cr.savepoint():
                execution = self.create({
                    "command_name": command_name,
                    "idempotency_key": idempotency_key,
                    "payload_hash": value_hash,
                    "authorization_id": authorization.id,
                })
        except IntegrityError:
            existing = self.search([
                ("user_id", "=", self.env.user.id),
                ("company_id", "=", self.env.user.company_id.id),
                ("command_name", "=", command_name),
                ("idempotency_key", "=", idempotency_key),
            ], limit=1)
            return existing._stored_result()
        self.env.cr.execute(
            "SELECT state FROM agui_chat_tool_authorization WHERE id = %s FOR UPDATE",
            (authorization.id,),
        )
        if self.env.cr.fetchone()[0] != "approved":
            execution.write({"state": "error", "error_code": "authorization_invalid"})
            return execution._stored_result()
        authorization.write({"state": "executing"})
        try:
            with self.env.cr.savepoint():
                result = spec["handler"](self.env, payload)
                result_json = canonical_json(result if result is not None else {})
                if len(result_json.encode("utf-8")) > MAX_RESULT_BYTES:
                    raise ValueError("result_too_large")
            execution.write({"state": "success", "result_json": result_json})
            authorization.write({"state": "consumed", "result_json": result_json})
        except Exception as error:
            code = getattr(error, "code", False) or "business_command_failed"
            execution.write({
                "state": "error",
                "error_code": code,
                "result_json": canonical_json({"ok": False, "code": code}),
            })
            authorization.write({"state": "consumed"})
        self.env["agui.chat.tool.audit"].log(
            command_name,
            "ok" if execution.state == "success" else "error",
            details=execution._stored_result(),
            authorization_id=authorization.id,
        )
        return execution._stored_result()

    def _stored_result(self):
        self.ensure_one()
        if self.state == "running":
            return {"ok": False, "code": "command_in_progress"}
        try:
            result = json.loads(self.result_json or "{}")
        except ValueError:
            result = {}
        if self.state == "success":
            return {"ok": True, "result": result}
        return {"ok": False, "code": self.error_code or "business_command_failed", "result": result}

    @api.model
    def _validate_schema(self, value, schema, path):
        expected = schema.get("type")
        type_checks = {
            "object": lambda item: isinstance(item, dict),
            "array": lambda item: isinstance(item, list),
            "string": lambda item: isinstance(item, str),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
            "boolean": lambda item: isinstance(item, bool),
        }
        if expected and expected in type_checks and not type_checks[expected](value):
            return "%s 必须是 %s 类型" % (path, expected)
        if expected == "object":
            properties = schema.get("properties") or {}
            for name in schema.get("required") or []:
                if name not in value:
                    return "%s.%s 为必填项" % (path, name)
            if schema.get("additionalProperties") is False:
                unknown = set(value.keys()) - set(properties.keys())
                if unknown:
                    return "%s 包含不支持的字段" % path
            for name, item in value.items():
                if name in properties:
                    error = self._validate_schema(item, properties[name], "%s.%s" % (path, name))
                    if error:
                        return error
        if expected == "array" and schema.get("items"):
            for index, item in enumerate(value):
                error = self._validate_schema(item, schema["items"], "%s[%s]" % (path, index))
                if error:
                    return error
        return False


class AguiChatToolAudit(models.Model):
    _name = "agui.chat.tool.audit"
    _description = "AG-UI 工具审计"
    _order = "create_date desc"

    user_id = fields.Many2one(
        "res.users", string="用户", required=True, default=lambda self: self.env.user, index=True
    )
    company_id = fields.Many2one(
        "res.company", string="公司", required=True, default=lambda self: self.env.user.company_id
    )
    request_id = fields.Char(string="请求 ID", index=True)
    run_id = fields.Char(string="运行 ID", index=True)
    thread_id = fields.Char(string="线程 ID", index=True)
    tool_call_id = fields.Char(string="工具调用 ID", index=True)
    tool_name = fields.Char(string="工具名称", required=True)
    target_model = fields.Char(string="目标模型")
    target_record = fields.Char(string="目标记录")
    authorization_id = fields.Many2one(
        "agui.chat.tool.authorization", string="命令授权", ondelete="set null"
    )
    result = fields.Selection([
        ("allowed", "已允许"), ("denied", "已拒绝"),
        ("ok", "成功"), ("error", "失败"),
    ], string="结果", required=True)
    details_json = fields.Text(string="详情", default="{}")

    @api.model
    def log(self, tool_name, result, details=None, **values):
        values.update({
            "user_id": self.env.user.id,
            "company_id": self.env.user.company_id.id,
            "tool_name": tool_name or "unknown",
            "result": result,
            "details_json": canonical_json(redact(details or {}))[:8192],
        })
        return self.sudo().create(values)

    @api.model
    def cleanup_expired(self):
        config = self.env["agui.chat.config"].sudo().get_active_config()
        now = fields.Datetime.from_string(fields.Datetime.now())
        session_cutoff = fields.Datetime.to_string(
            now - timedelta(days=max(config.session_retention_days or 180, 1))
        )
        audit_cutoff = fields.Datetime.to_string(
            now - timedelta(days=max(config.audit_retention_days or 180, 1))
        )
        self.env["agui.chat.session"].sudo().search([
            ("write_date", "<", session_cutoff)
        ]).unlink()
        self.sudo().search([("create_date", "<", audit_cutoff)]).unlink()
        self.env["agui.chat.tool.authorization"].sudo().search([
            ("create_date", "<", audit_cutoff)
        ]).unlink()
        self.env["agui.chat.command.execution"].sudo().search([
            ("create_date", "<", audit_cutoff)
        ]).unlink()
        return True
