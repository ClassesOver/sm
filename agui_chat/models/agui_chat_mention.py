# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import re
import uuid
from datetime import timedelta

from lxml import etree

from odoo import api, fields, models, tools
from odoo.exceptions import AccessError
from odoo.tools.mail import html2plaintext


CANDIDATE_TTL_MINUTES = 5
BOUND_TTL_HOURS = 2
MAX_CANDIDATES = 100
MAX_BOUND_TOKENS = 200
MAX_SEARCH_MODELS = 20
MAX_MODEL_SCOPES = 100
MAX_SEARCH_RESULTS = 20
MAX_GLOBAL_RECORDS_PER_MODEL = 5
GLOBAL_RESULT_QUOTAS = {
    "menu": 4,
    "record": 10,
    "saved_filter": 5,
    "current_filter": 1,
}
GLOBAL_RESULT_PRIORITY = ("record", "menu", "saved_filter", "current_filter")
MAX_READ_FIELDS = 20
MAX_READ_RESULT_BYTES = 64 * 1024
MAX_CURRENT_FILTER_BYTES = 16 * 1024
SECRET_FIELD = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|private[_-]?key|cookie|session)", re.I
)
PAGE_ACTIONS = {"open", "create", "view", "edit", "apply"}
ALLOWED_ACTIONS = {
    "menu": {"open", "create"},
    "record": {"read", "view", "edit"},
    "saved_filter": {"apply"},
    "current_filter": {"apply"},
}
TOOL_BINDINGS = {
    "odoo.open_mentioned_menu": {"menu": {"open", "create"}},
    "odoo.open_mentioned_record": {"record": {"view", "edit"}},
    "odoo.apply_mentioned_filter": {
        "saved_filter": {"apply"}, "current_filter": {"apply"},
    },
}


class MentionTokenError(ValueError):
    def __init__(self, code, message=None, audit_details=None):
        super(MentionTokenError, self).__init__(message or code)
        self.code = code
        self.audit_details = audit_details or {}


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _now():
    return fields.Datetime.from_string(fields.Datetime.now())


class AguiChatMentionToken(models.Model):
    _name = "agui.chat.mention.token"
    _description = "AG-UI 对象引用令牌"
    _order = "create_date desc, id desc"

    token = fields.Char(required=True, index=True, default=lambda self: str(uuid.uuid4()))
    token_kind = fields.Selection([
        ("candidate", "候选"), ("bound", "已绑定"),
    ], required=True, index=True)
    resource_kind = fields.Selection([
        ("menu", "菜单"), ("record", "记录"),
        ("saved_filter", "收藏筛选"), ("current_filter", "当前筛选"),
    ], required=True, index=True)
    bound_action = fields.Selection([
        ("read", "引用数据"), ("open", "打开"), ("create", "新建"),
        ("view", "查看"), ("edit", "编辑"), ("apply", "应用"),
    ], index=True)
    resource_key = fields.Char(required=True, index=True)
    model_name = fields.Char(index=True)
    label = fields.Char(required=True)
    detail = fields.Char()
    payload_json = fields.Text(required=True, default="{}")
    session_key = fields.Char(required=True, index=True)
    user_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, index=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.user.company_id,
        index=True, ondelete="cascade",
    )
    expires_at = fields.Datetime(required=True, index=True)
    state = fields.Selection([
        ("active", "有效"), ("expired", "已过期"),
    ], required=True, default="active", index=True)

    _sql_constraints = [
        ("mention_token_unique", "unique(token)", "对象引用令牌必须唯一。"),
    ]

    @api.model
    def search_mentions(self, query, scope, model_scope, current_model,
                        recent_models, current_filter, session_key):
        query = str(query or "").strip()[:120]
        scope = scope if scope in (
            "all", "menu", "record", "saved_filter", "current_filter"
        ) else "all"
        empty_browse_scopes = {"menu", "saved_filter", "current_filter"}
        if len(query) < 2 and scope not in empty_browse_scopes:
            return {
                "candidates": [],
                "modelScopes": self._model_scopes(current_model, recent_models),
            }

        catalog = self._menu_catalog()
        enabled_actions = self._enabled_reference_actions()
        model_entries = self._ordered_model_entries(
            catalog, current_model, recent_models, model_scope
        )
        if not model_scope:
            model_entries = model_entries[:MAX_SEARCH_MODELS]
        buckets = {
            "menu": [], "record": [], "saved_filter": [], "current_filter": [],
        }

        if scope in ("all", "menu"):
            for item in catalog:
                if query and query.lower() not in item["fullPath"].lower():
                    continue
                actions = ["open"] if "open" in enabled_actions else []
                model = item.get("model")
                if "create" in enabled_actions and item.get("can_create"):
                    actions.append("create")
                if not actions:
                    continue
                buckets["menu"].append(self._create_candidate(
                    "menu", item["fullPath"], item["fullPath"], model, actions,
                    item, session_key,
                ))
                if len(buckets["menu"]) >= MAX_SEARCH_RESULTS:
                    break

        if len(query) >= 2 and scope in ("all", "record"):
            record_limit = MAX_SEARCH_RESULTS if model_scope else MAX_GLOBAL_RECORDS_PER_MODEL
            for entry in model_entries:
                if len(buckets["record"]) >= MAX_SEARCH_RESULTS:
                    break
                model = entry["model"]
                if not self._can(model, "read") or not self.env[model]._rec_name:
                    continue
                limit = min(
                    record_limit, MAX_SEARCH_RESULTS - len(buckets["record"]),
                )
                try:
                    matches = self.env[model].name_search(
                        name=query, args=[], operator="ilike", limit=limit,
                    )
                except (AccessError, ValueError):
                    continue
                for record_id, display_name in matches:
                    actions = [
                        action for action in ("read", "view") if action in enabled_actions
                    ]
                    if "edit" in enabled_actions and self._can_record(model, record_id, "write"):
                        actions.append("edit")
                    if not actions:
                        continue
                    payload = dict(entry, record_id=record_id)
                    buckets["record"].append(self._create_candidate(
                        "record", display_name, entry["label"], model, actions,
                        payload, session_key,
                    ))

        if scope == "saved_filter":
            filter_entries = []
            for model_entry in model_entries:
                for menu_entry in catalog:
                    if menu_entry["model"] == model_entry["model"]:
                        filter_entries.append({
                            "model": menu_entry["model"],
                            "label": menu_entry["fullPath"],
                            "menu_id": menu_entry["menu_id"],
                            "action_id": menu_entry["action_id"],
                        })
            seen_filters = set()
            for entry in filter_entries:
                if len(buckets["saved_filter"]) >= MAX_SEARCH_RESULTS:
                    break
                try:
                    filters = self.env["ir.filters"].get_filters(
                        entry["model"], entry.get("action_id") or None,
                    )
                except AccessError:
                    continue
                for item in filters:
                    if item["id"] in seen_filters:
                        continue
                    if query.lower() not in str(item.get("name") or "").lower():
                        continue
                    if "apply" not in enabled_actions:
                        continue
                    seen_filters.add(item["id"])
                    owner = "个人收藏" if item.get("user_id") else "共享收藏"
                    payload = dict(entry, filter_id=item["id"])
                    buckets["saved_filter"].append(self._create_candidate(
                        "saved_filter", item["name"], "%s · %s" % (entry["label"], owner),
                        entry["model"], ["apply"], payload, session_key,
                    ))
                    if len(buckets["saved_filter"]) >= MAX_SEARCH_RESULTS:
                        break

        if scope == "current_filter":
            payload = self._normalize_current_filter(current_filter, catalog)
            if payload and "apply" in enabled_actions and (
                    not query or query.lower() in payload["label"].lower()):
                buckets["current_filter"].append(self._create_candidate(
                    "current_filter", payload["label"], payload["menu_label"],
                    payload["model"], ["apply"], payload, session_key,
                ))

        if scope == "all":
            results = []
            offsets = {}
            for kind in GLOBAL_RESULT_PRIORITY:
                quota = GLOBAL_RESULT_QUOTAS[kind]
                selected = buckets[kind][:quota]
                results.extend(selected)
                offsets[kind] = len(selected)
            while len(results) < MAX_SEARCH_RESULTS:
                added = False
                for kind in GLOBAL_RESULT_PRIORITY:
                    offset = offsets[kind]
                    if offset >= len(buckets[kind]):
                        continue
                    results.append(buckets[kind][offset])
                    offsets[kind] = offset + 1
                    added = True
                    if len(results) >= MAX_SEARCH_RESULTS:
                        break
                if not added:
                    break
        else:
            results = buckets[scope]

        self._enforce_token_limit("candidate", MAX_CANDIDATES)
        return {
            "candidates": results[:MAX_SEARCH_RESULTS],
            "modelScopes": self._model_scopes(current_model, recent_models, catalog),
        }

    @api.model
    def bind_mention(self, candidate_token, action, session_key):
        candidate = self._load_token(candidate_token, "candidate", session_key)
        payload = json.loads(candidate.payload_json or "{}")
        allowed = set(payload.get("allowed_actions") or [])
        if action not in allowed or action not in ALLOWED_ACTIONS[candidate.resource_kind]:
            raise MentionTokenError("mention_action_not_allowed", "该候选不支持所选动作。")
        self._revalidate_payload(candidate.resource_kind, payload, action)
        expires = _now() + timedelta(hours=BOUND_TTL_HOURS)
        bound = self.sudo().create({
            "token_kind": "bound",
            "resource_kind": candidate.resource_kind,
            "bound_action": action,
            "resource_key": candidate.resource_key,
            "model_name": candidate.model_name,
            "label": candidate.label,
            "detail": candidate.detail,
            "payload_json": candidate.payload_json,
            "session_key": session_key,
            "user_id": self.env.user.id,
            "company_id": self.env.user.company_id.id,
            "expires_at": fields.Datetime.to_string(expires),
        })
        self._enforce_token_limit("bound", MAX_BOUND_TOKENS)
        return self._public_reference(bound)

    @api.model
    def resolve_tool_arguments(self, tool_name, arguments, session_key):
        arguments = dict(arguments or {})
        arguments.pop("__mention", None)
        if tool_name == "odoo.read_mentioned_records":
            tokens = arguments.get("tokens")
            if not isinstance(tokens, list) or not 1 <= len(tokens) <= 5:
                raise MentionTokenError("mention_limit_exceeded", "记录引用数量必须为 1 至 5 个。")
            if len(set(tokens)) != len(tokens):
                raise MentionTokenError("duplicate_mention", "不能重复引用同一对象。")
            bindings = [
                self._resolved_binding(token, "record", "read", session_key)
                for token in tokens
            ]
        elif tool_name in TOOL_BINDINGS:
            token = arguments.get("token")
            if not isinstance(token, str) or not token:
                raise MentionTokenError("invalid_mention_token", "缺少对象引用令牌。")
            bound = self._load_token(token, "bound", session_key)
            allowed = TOOL_BINDINGS[tool_name].get(bound.resource_kind) or set()
            if bound.bound_action not in allowed:
                raise MentionTokenError("mention_action_mismatch", "对象引用动作与工具不匹配。")
            bindings = [self._resolved_binding(
                token, bound.resource_kind, bound.bound_action, session_key,
            )]
        else:
            return arguments, False
        arguments["__mention"] = bindings
        return arguments, self.audit_details(tool_name, arguments)

    @api.model
    def read_tokens(self, tokens, session_key):
        arguments, _audit = self.resolve_tool_arguments(
            "odoo.read_mentioned_records", {"tokens": tokens}, session_key,
        )
        records = []
        truncated = False
        for binding in arguments["__mention"]:
            model_name = binding["model"]
            record = self.env[model_name].browse(binding["record_id"]).exists()
            self._check_record(record, "read")
            field_names = self._read_field_names(model_name)
            definitions = record.fields_get(field_names)
            values = record.read(field_names)[0]
            item = {
                "reference": binding["label"],
                "model": model_name,
                "label": record.display_name,
                "fields": [],
            }
            for name in field_names:
                definition = definitions.get(name)
                if not definition:
                    continue
                item["fields"].append({
                    "name": name,
                    "label": definition.get("string") or name,
                    "type": definition.get("type"),
                    "value": self._safe_value(definition.get("type"), values.get(name)),
                })
            records.append(item)
            while len(_json({"records": records}).encode("utf-8")) > MAX_READ_RESULT_BYTES:
                if not item["fields"]:
                    records.pop()
                    break
                item["fields"].pop()
                truncated = True
        result = {
            "ok": True,
            "operation": "odoo.read_mentioned_records",
            "count": len(records),
            "records": records,
            "truncated": truncated or len(records) < len(arguments["__mention"]),
        }
        if len(_json(result).encode("utf-8")) > MAX_READ_RESULT_BYTES:
            raise MentionTokenError("result_too_large", "记录读取结果超过大小限制。")
        return result

    @api.model
    def audit_details(self, tool_name, arguments, result=None):
        bindings = arguments.get("__mention") if isinstance(arguments, dict) else []
        bindings = bindings if isinstance(bindings, list) else []
        details = {
            "resource_categories": sorted(set(
                item.get("kind") for item in bindings if item.get("kind")
            )),
            "models": sorted(set(item.get("model") for item in bindings if item.get("model"))),
            "actions": sorted(set(item.get("action") for item in bindings if item.get("action"))),
            "count": len(bindings),
        }
        if tool_name == "odoo.read_mentioned_records" and isinstance(result, dict):
            details["field_names"] = sorted(set(
                field.get("name")
                for record in result.get("records") or []
                for field in record.get("fields") or []
                if field.get("name")
            ))
        return details

    @api.model
    def _create_candidate(self, kind, label, detail, model_name, actions, payload, session_key):
        payload = dict(payload)
        payload["allowed_actions"] = actions
        resource_key = self._resource_key(kind, payload)
        record = self.sudo().create({
            "token_kind": "candidate",
            "resource_kind": kind,
            "resource_key": resource_key,
            "model_name": model_name or False,
            "label": str(label or "")[:256],
            "detail": str(detail or "")[:512],
            "payload_json": _json(payload),
            "session_key": session_key,
            "user_id": self.env.user.id,
            "company_id": self.env.user.company_id.id,
            "expires_at": fields.Datetime.to_string(
                _now() + timedelta(minutes=CANDIDATE_TTL_MINUTES)
            ),
        })
        return {
            "candidateToken": record.token,
            "resourceKey": resource_key,
            "kind": kind,
            "label": record.label,
            "detail": record.detail or "",
            "model": model_name or False,
            "actions": actions,
            "expiresAt": fields.Datetime.to_string(record.expires_at),
        }

    @api.model
    def _public_reference(self, record):
        return {
            "id": record.token,
            "token": record.token,
            "resourceKey": record.resource_key,
            "kind": record.resource_kind,
            "action": record.bound_action,
            "label": record.label,
            "detail": record.detail or "",
            "model": record.model_name or False,
            "expiresAt": fields.Datetime.to_string(record.expires_at),
            "valid": True,
            "pageAction": record.bound_action in PAGE_ACTIONS,
        }

    @api.model
    def _load_token(self, token, token_kind, session_key):
        record = self.search([
            ("token", "=", str(token or "")),
            ("token_kind", "=", token_kind),
            ("user_id", "=", self.env.user.id),
            ("company_id", "=", self.env.user.company_id.id),
            ("session_key", "=", session_key),
            ("state", "=", "active"),
        ], limit=1)
        if not record:
            raise MentionTokenError("invalid_mention_token", "对象引用令牌无效。")
        expires = fields.Datetime.from_string(record.expires_at)
        if expires <= _now():
            record.sudo().write({"state": "expired"})
            raise MentionTokenError("mention_token_expired", "对象引用令牌已过期。")
        return record

    @api.model
    def _resolved_binding(self, token, kind, action, session_key):
        record = self._load_token(token, "bound", session_key)
        if record.resource_kind != kind or record.bound_action != action:
            raise MentionTokenError("mention_action_mismatch", "对象引用动作不匹配。")
        payload = json.loads(record.payload_json or "{}")
        try:
            self._revalidate_payload(kind, payload, action)
        except MentionTokenError as error:
            error.audit_details = {
                "resource_categories": [kind],
                "models": [record.model_name] if record.model_name else [],
                "actions": [action],
                "count": 1,
            }
            raise
        if kind == "saved_filter":
            filters = self.env["ir.filters"].get_filters(
                payload.get("model"), payload.get("action_id") or None,
            )
            saved = next(
                item for item in filters if item.get("id") == payload.get("filter_id")
            )
            payload.update({
                "domain": saved.get("domain") or "[]",
                "context": saved.get("context") or "{}",
                "sort": saved.get("sort") or "[]",
            })
        binding = dict(payload)
        binding.update({
            "token": record.token,
            "kind": kind,
            "action": action,
            "label": record.label,
        })
        binding.pop("allowed_actions", None)
        return binding

    @api.model
    def _revalidate_payload(self, kind, payload, action):
        if kind == "menu":
            menu = self._catalog_item(payload.get("menu_id"))
            if not menu or menu.get("action_id") != payload.get("action_id"):
                raise MentionTokenError("mention_resource_unavailable", "菜单已删除或无权访问。")
            if action == "create" and not self._can(menu.get("model"), "create"):
                raise MentionTokenError("mention_permission_revoked", "已无权新建该对象。")
            return
        if kind == "record":
            menu = self._catalog_item(payload.get("menu_id"))
            if not menu or menu.get("model") != payload.get("model"):
                raise MentionTokenError("mention_resource_unavailable", "记录入口已不可用。")
            record = self.env[payload["model"]].browse(payload.get("record_id")).exists()
            self._check_record(record, "write" if action == "edit" else "read")
            return
        if kind == "saved_filter":
            filters = self.env["ir.filters"].get_filters(
                payload.get("model"), payload.get("action_id") or None,
            )
            if not any(item.get("id") == payload.get("filter_id") for item in filters):
                raise MentionTokenError("mention_resource_unavailable", "收藏筛选已删除或无权访问。")
            if not self._catalog_item(payload.get("menu_id")):
                raise MentionTokenError("mention_resource_unavailable", "筛选所属菜单已不可用。")
            return
        if kind == "current_filter":
            if not self._catalog_item(payload.get("menu_id")):
                raise MentionTokenError("mention_resource_unavailable", "筛选所属菜单已不可用。")

    @api.model
    def _check_record(self, record, operation):
        if not record:
            raise MentionTokenError("mention_resource_unavailable", "记录已删除或无权访问。")
        try:
            record.check_access_rights(operation)
            record.check_access_rule(operation)
        except AccessError:
            raise MentionTokenError("mention_permission_revoked", "记录权限已被撤销。")

    @api.model
    def _can_record(self, model_name, record_id, operation):
        try:
            self._check_record(self.env[model_name].browse(record_id).exists(), operation)
            return True
        except MentionTokenError:
            return False

    @api.model
    def _can(self, model_name, operation):
        return bool(
            model_name in self.env and
            self.env[model_name].check_access_rights(operation, raise_exception=False)
        )

    @api.model
    def _enabled_reference_actions(self):
        config = self.env["agui.chat.config"].sudo().get_active_config()
        if not config.chat_enabled or not config.host_tools_enabled:
            return set()
        commands = set(config.enabled_command_names())
        actions = set()
        if "odoo.read_mentioned_records" in commands:
            actions.add("read")
        if "odoo.open_mentioned_menu" in commands:
            actions.update(("open", "create"))
        if "odoo.open_mentioned_record" in commands:
            actions.update(("view", "edit"))
        if "odoo.apply_mentioned_filter" in commands:
            actions.add("apply")
        return actions

    @api.model
    @tools.ormcache("self.env.uid", "self.env.user.company_id.id")
    def _menu_catalog(self):
        root = self.env["ir.ui.menu"].load_menus(False)
        catalog = []

        def visit(node, path):
            name = str(node.get("name") or "").strip()
            next_path = path + ([name] if name else [])
            action = str(node.get("action") or "")
            parts = action.split(",")
            if len(parts) == 2 and parts[0] == "ir.actions.act_window":
                try:
                    action_id = int(parts[1])
                    menu_id = int(node.get("id"))
                except (TypeError, ValueError):
                    action_id = menu_id = 0
                window = self.env["ir.actions.act_window"].sudo().browse(action_id).exists()
                if menu_id and window and window.res_model:
                    catalog.append({
                        "menu_id": menu_id,
                        "action_id": action_id,
                        "model": window.res_model,
                        "can_create": self._can(window.res_model, "create"),
                        "label": name,
                        "path": next_path,
                        "fullPath": " / ".join(next_path),
                    })
            for child in node.get("children") or []:
                visit(child, next_path)

        for child in root.get("children") or []:
            visit(child, [])
        return catalog

    @api.model
    def _catalog_item(self, menu_id):
        try:
            menu_id = int(menu_id)
        except (TypeError, ValueError):
            return False
        return next((item for item in self._menu_catalog() if item["menu_id"] == menu_id), False)

    @api.model
    def _ordered_model_entries(self, catalog, current_model, recent_models, model_scope):
        by_model = {}
        for item in catalog:
            by_model.setdefault(item["model"], item)
        order = [current_model] + list(recent_models or []) + [item["model"] for item in catalog]
        seen = set()
        entries = []
        for model_name in order:
            if model_name in seen or model_name not in by_model:
                continue
            seen.add(model_name)
            item = by_model[model_name]
            entries.append({
                "model": model_name,
                "label": item["fullPath"],
                "menu_id": item["menu_id"],
                "action_id": item["action_id"],
            })
        allowed_models = set(
            self.env["agui.chat.config"].sudo().get_active_config().mention_model_names()
        )
        if allowed_models:
            entries = [item for item in entries if item["model"] in allowed_models]
        if model_scope:
            entries = [item for item in entries if item["model"] == model_scope]
        return entries

    @api.model
    def _model_scopes(self, current_model, recent_models, catalog=None):
        catalog = catalog or self._menu_catalog()
        return [
            {"model": item["model"], "label": item["label"]}
            for item in self._ordered_model_entries(catalog, current_model, recent_models, False)
        ][:MAX_MODEL_SCOPES]

    @api.model
    def _normalize_current_filter(self, value, catalog):
        if not isinstance(value, dict):
            return False
        if len(_json(value).encode("utf-8")) > MAX_CURRENT_FILTER_BYTES:
            return False
        model_name = value.get("model")
        try:
            menu_id = int(value.get("menuId"))
        except (TypeError, ValueError):
            return False
        menu = next((item for item in catalog if item["menu_id"] == menu_id), False)
        if not menu or menu["model"] != model_name:
            return False
        domain = value.get("domain")
        context = value.get("context")
        group_by = value.get("groupBy") or []
        sort = value.get("sort") or []
        if not isinstance(domain, list) or not isinstance(context, dict):
            return False
        if not isinstance(group_by, list) or not isinstance(sort, list):
            return False
        if len(group_by) > 10 or len(sort) > 10:
            return False
        if not all(isinstance(item, str) and len(item) <= 128 for item in group_by + sort):
            return False
        context = dict(context)
        for key in ("uid", "company_id", "allowed_company_ids", "lang", "tz", "bin_size"):
            context.pop(key, None)
        return {
            "label": str(value.get("label") or "当前筛选")[:120],
            "menu_label": menu["fullPath"],
            "model": model_name,
            "menu_id": menu_id,
            "action_id": menu["action_id"],
            "domain": domain,
            "context": context,
            "group_by": group_by,
            "sort": sort,
        }

    @api.model
    def _resource_key(self, kind, payload):
        material = {
            "menu": [payload.get("menu_id")],
            "record": [payload.get("model"), payload.get("record_id")],
            "saved_filter": [payload.get("filter_id")],
            "current_filter": [payload.get("menu_id"), payload.get("domain"), payload.get("context"), payload.get("group_by"), payload.get("sort")],
        }[kind]
        secret = self.env["ir.config_parameter"].sudo().get_param("database.secret") or "agui"
        return hmac.new(
            secret.encode("utf-8"), _json([kind, material]).encode("utf-8"), hashlib.sha256,
        ).hexdigest()

    @api.model
    def _read_field_names(self, model_name):
        sensitive = set(
            self.env["agui.chat.config"].sudo().get_active_config().sensitive_fields()
        )
        policies = self.env["agui.chat.tool.policy"].sudo().search([
            ("active", "=", True),
            ("tool_name", "=", "odoo.read_mentioned_records"),
            ("model_name", "=", model_name),
        ], order="sequence, id")
        groups = set(self.env.user.groups_id.ids)
        policy = next((item for item in policies if not item.group_ids or groups.intersection(item.group_ids.ids)), False)
        names = [
            name.strip() for name in (policy.field_names or "").split(",") if name.strip()
        ] if policy else []
        if not names:
            view = self.env[model_name].fields_view_get(view_type="form")
            arch = etree.fromstring(view["arch"].encode("utf-8"))
            names = []
            for node in arch.xpath("//field[@name]"):
                name = node.get("name")
                if name not in names:
                    names.append(name)
        definitions = self.env[model_name].fields_get(names)
        return [
            name for name in names
            if name in definitions and
            definitions[name].get("type") != "binary" and
            name not in sensitive and not SECRET_FIELD.search(name)
        ][:MAX_READ_FIELDS]

    @api.model
    def _safe_value(self, field_type, value):
        if field_type == "many2one":
            return value[1] if isinstance(value, (list, tuple)) and len(value) > 1 else False
        if field_type in ("one2many", "many2many"):
            return len(value or [])
        if field_type == "html":
            value = html2plaintext(value or "")
        if isinstance(value, str):
            return value[:2000]
        if isinstance(value, (bool, int, float)) or value is None:
            return value
        return str(value or "")[:2000]

    @api.model
    def _enforce_token_limit(self, token_kind, limit):
        expired = self.sudo().search([
            ("user_id", "=", self.env.user.id),
            ("company_id", "=", self.env.user.company_id.id),
            ("token_kind", "=", token_kind),
            "|", ("state", "=", "expired"), ("expires_at", "<=", fields.Datetime.now()),
        ])
        expired.unlink()
        records = self.sudo().search([
            ("user_id", "=", self.env.user.id),
            ("company_id", "=", self.env.user.company_id.id),
            ("token_kind", "=", token_kind),
        ], order="create_date desc, id desc")
        if len(records) > limit:
            records[limit:].unlink()
