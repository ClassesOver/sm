# -*- coding: utf-8 -*-
import hashlib
import json

from odoo import api, fields, models
from odoo.exceptions import ValidationError


PROTOCOL = "agui.odoo.v2"
MODULE_VERSION = "12.0.8.8.3"
COMMAND_CATALOG_REVISION = 11
DEFAULT_SENSITIVE_FIELD_NAMES = (
    "phone", "mobile", "phone_number", "mobile_number",
    "bank_account", "bank_account_id", "acc_number", "card_number",
    "vat", "tax_id", "identity_number", "id_card", "id_number",
)
HOST_COMMAND_NAMES = (
    "odoo.read_mentioned_records",
    "odoo.open_mentioned_menu",
    "odoo.open_mentioned_record",
    "odoo.apply_mentioned_filter",
    "odoo.search_menu",
    "odoo.open_menu",
    "odoo.apply_filter",
    "odoo.apply_group",
    "odoo.open_record",
    "odoo.open_create",
    "odoo.open_x2many_record",
    "odoo.open_x2many_create",
    "odoo.prepare_x2many_import",
    "odoo.get_x2many_import_status",
    "odoo.reload_current_form",
    "odoo.enter_edit_mode",
    "odoo.activate_view_control",
    "odoo.search_relation",
    "odoo.stage_current_form",
    "odoo.patch_current_form",
    "odoo.validate_current_form",
    "odoo.save_current_form",
    "odoo.discard_current_form",
)
COMMAND_CATALOG_HASH = hashlib.sha256(json.dumps(
    {
        "protocol": PROTOCOL,
        "commands": HOST_COMMAND_NAMES,
        "revision": COMMAND_CATALOG_REVISION,
    },
    ensure_ascii=True,
    separators=(",", ":"),
    sort_keys=True,
).encode("utf-8")).hexdigest()


class AguiChatConfig(models.Model):
    _name = "agui.chat.config"
    _description = "智能助手配置"

    name = fields.Char(string="配置名称", required=True, default="默认配置")
    active = fields.Boolean(string="启用", default=True)
    chat_enabled = fields.Boolean(string="启用聊天", default=False)
    host_tools_enabled = fields.Boolean(string="启用页面工具", default=False)
    write_tools_enabled = fields.Boolean(string="启用写入工具", default=False)
    enabled_commands = fields.Char(
        string="兼容页面命令字符串",
        help="填写以逗号分隔的完整页面命令名；留空表示不启用页面命令。",
    )
    enabled_business_commands = fields.Char(
        string="兼容业务命令字符串",
        help="填写以逗号分隔的已注册业务命令完整名称。",
    )
    enabled_command_ids = fields.Many2many(
        "agui.chat.command",
        relation="agui_chat_config_enabled_page_command_rel",
        string="已启用页面命令",
        compute="_compute_enabled_command_ids",
        inverse="_inverse_enabled_command_ids",
    )
    enabled_business_command_ids = fields.Many2many(
        "agui.chat.command",
        relation="agui_chat_config_enabled_business_command_rel",
        string="已启用业务命令",
        compute="_compute_enabled_business_command_ids",
        inverse="_inverse_enabled_business_command_ids",
    )
    runtime_url = fields.Char(
        string="AG-UI 运行服务地址",
        default="",
        help="开发环境可直接填写 AgentOS 的 /agui 地址；协议配置地址会自动推导为同路径下的 /config。",
    )
    agentos_internal_url = fields.Char(
        string="AgentOS 内部服务地址",
        default="",
        help="仅供 HRP 服务端销毁工作区使用，不会发送到浏览器。",
    )
    allow_cross_origin_dev = fields.Boolean(
        string="允许跨域开发服务",
        help="仅限开发环境。允许携带凭据访问 HTTP(S) 绝对地址。",
        default=False,
    )
    default_agent_id = fields.Char(string="默认智能体 ID", default="odoo-assistant")
    mention_model_id = fields.Many2one(
        "ir.model",
        string="业务模型白名单",
        ondelete="set null",
        help="仅允许引用所选业务模型；留空表示允许菜单中可读的全部业务类型。",
    )
    sensitive_field_names = fields.Char(
        string="敏感字段",
        help="填写以逗号分隔的 HRP 字段名，这些字段在页面快照中会被脱敏。",
    )
    max_request_bytes = fields.Integer(string="请求最大字节数", default=2 * 1024 * 1024)
    max_messages = fields.Integer(string="单次请求最大消息数", default=200)
    max_sse_event_bytes = fields.Integer(string="SSE 事件最大字节数", default=1024 * 1024)
    session_retention_days = fields.Integer(string="会话保留天数", default=180)
    audit_retention_days = fields.Integer(string="审计保留天数", default=180)

    @api.constrains(
        "chat_enabled", "runtime_url", "allow_cross_origin_dev", "agentos_internal_url",
    )
    def _check_runtime_urls(self):
        for record in self:
            value = (record.runtime_url or "").strip()
            is_absolute = value.startswith("http://") or value.startswith("https://")
            is_relative = value.startswith("/") and not value.startswith("//") and "://" not in value
            if value and not is_relative and not (record.allow_cross_origin_dev and is_absolute):
                raise ValidationError(
                    "运行服务地址必须是同源路径，除非已启用跨域开发服务。"
                )
            if value and not value.rstrip("/").endswith("/agui"):
                raise ValidationError("AG-UI 运行服务地址必须以 /agui 结尾。")
            internal = (record.agentos_internal_url or "").strip()
            if internal and not internal.startswith(("http://", "https://")):
                raise ValidationError("AgentOS 内部服务地址必须是 HTTP(S) 绝对地址。")
            if "@" in internal.split("://", 1)[-1].split("/", 1)[0]:
                raise ValidationError("AgentOS 内部服务地址不能包含认证信息。")
            if record.chat_enabled:
                if not value or not internal:
                    raise ValidationError(
                        "启用聊天前必须配置 AG-UI 运行服务地址和 AgentOS 内部服务地址。"
                    )
                from .agui_chat_workspace import workspace_secret
                workspace_secret(record.env)

    @api.constrains("enabled_commands")
    def _check_enabled_commands(self):
        allowed = set(HOST_COMMAND_NAMES)
        for record in self:
            unknown = set(record._configured_command_names("enabled_commands")) - allowed
            if unknown:
                raise ValidationError("存在未知的 AG-UI 页面命令：%s" % ", ".join(sorted(unknown)))

    @api.depends("enabled_commands")
    def _compute_enabled_command_ids(self):
        command_model = self.env["agui.chat.command"].with_context(active_test=False)
        for record in self:
            record.enabled_command_ids = command_model.search([
                ("code", "in", record.enabled_command_names()),
                ("command_type", "=", "page"),
            ])

    def _inverse_enabled_command_ids(self):
        for record in self:
            record.enabled_commands = ",".join(
                record._selected_command_codes(record.enabled_command_ids, "page")
            )

    @api.depends("enabled_business_commands")
    def _compute_enabled_business_command_ids(self):
        command_model = self.env["agui.chat.command"].with_context(active_test=False)
        for record in self:
            record.enabled_business_command_ids = command_model.search([
                ("code", "in", record.enabled_business_command_names()),
                ("command_type", "=", "business"),
            ])

    def _inverse_enabled_business_command_ids(self):
        for record in self:
            record.enabled_business_commands = ",".join(
                record._selected_command_codes(
                    record.enabled_business_command_ids, "business"
                )
            )

    def _selected_command_codes(self, commands, command_type):
        invalid = commands.filtered(lambda command: command.command_type != command_type)
        if invalid:
            raise ValidationError("页面命令与业务命令不能混用。")
        return commands.sorted(
            key=lambda command: (command.sequence, command.code)
        ).mapped("code")

    def public_runtime_url(self):
        self.ensure_one()
        return (self.runtime_url or "").strip()

    def public_runtime_config_url(self):
        self.ensure_one()
        runtime_url = self.public_runtime_url().rstrip("/")
        return runtime_url[:-len("/agui")] + "/config" if runtime_url.endswith("/agui") else ""

    def internal_agentos_url(self):
        self.ensure_one()
        return (self.agentos_internal_url or "").strip().rstrip("/")

    def enabled_command_names(self):
        self.ensure_one()
        return self._effective_command_names("enabled_commands", "page")

    def enabled_business_command_names(self):
        self.ensure_one()
        return self._effective_command_names(
            "enabled_business_commands", "business"
        )

    def _configured_command_names(self, field_name):
        self.ensure_one()
        return [
            item.strip()
            for item in (self[field_name] or "").split(",")
            if item.strip()
        ]

    def _effective_command_names(self, field_name, command_type):
        configured = self._configured_command_names(field_name)
        if not configured:
            return []
        active = set(self.env["agui.chat.command"].sudo().search([
            ("active", "=", True),
            ("command_type", "=", command_type),
            ("code", "in", configured),
        ]).mapped("code"))
        return [name for name in configured if name in active]

    def mention_model_names(self):
        self.ensure_one()
        return [self.mention_model_id.model] if self.mention_model_id else []

    def sensitive_fields(self):
        self.ensure_one()
        configured = {
            item.strip() for item in (self.sensitive_field_names or "").split(",") if item.strip()
        }
        return sorted(configured.union(DEFAULT_SENSITIVE_FIELD_NAMES))

    @api.model
    def get_active_config(self):
        config = self.search([("active", "=", True)], limit=1)
        if config:
            return config
        return self.create({"name": "默认配置"})
