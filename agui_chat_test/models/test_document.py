# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.agui_chat.models.agui_chat_config import HOST_COMMAND_NAMES


DOMAIN_KEYS = [
    ("standard", "标准"),
    ("special", "特殊"),
]


class AguiChatTestOption(models.Model):
    _name = "agui.chat.test.option"
    _description = "AG-UI 测试关系候选"
    _order = "domain_key, name, id"

    name = fields.Char(string="候选名称", required=True)
    domain_key = fields.Selection(
        DOMAIN_KEYS, string="域键", required=True, index=True
    )
    active = fields.Boolean(string="有效", default=True)


class AguiChatTestDocument(models.Model):
    _name = "agui.chat.test.document"
    _description = "AG-UI 通用测试单据"
    _order = "id desc"

    name = fields.Char(string="单据名称", required=True)
    required_code = fields.Char(string="必填编码", required=True)
    description = fields.Text(string="说明")
    enabled = fields.Boolean(string="启用", default=True)
    quantity = fields.Integer(string="数量", default=1)
    amount = fields.Monetary(string="金额", currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency",
        string="币种",
        required=True,
        default=lambda self: self.env.user.company_id.currency_id,
    )
    document_date = fields.Date(
        string="单据日期", default=fields.Date.context_today
    )
    priority = fields.Selection(
        [("low", "低"), ("normal", "普通"), ("high", "高")],
        string="优先级",
        default="normal",
    )
    document_type = fields.Selection(
        DOMAIN_KEYS, string="单据类型", required=True, default="standard"
    )
    domain_key = fields.Selection(
        DOMAIN_KEYS, string="关系域键", required=True, default="standard"
    )
    candidate_id = fields.Many2one(
        "agui.chat.test.option", string="主候选", ondelete="restrict"
    )
    tag_ids = fields.Many2many(
        "agui.chat.test.option",
        "agui_chat_test_document_option_rel",
        "document_id",
        "option_id",
        string="候选标签",
    )
    line_ids = fields.One2many(
        "agui.chat.test.line", "document_id", string="明细"
    )
    detail_item_ids = fields.One2many(
        "agui.chat.test.line", "document_id", string="通用明细"
    )
    show_extra = fields.Boolean(string="显示附加字段")
    dynamic_note = fields.Char(string="动态附加字段")
    locked_note = fields.Char(string="状态锁定字段")
    state = fields.Selection(
        [("draft", "草稿"), ("confirmed", "已确认")],
        string="状态",
        required=True,
        default="draft",
    )
    secret_token = fields.Char(string="敏感令牌", default="e2e-secret-token")
    phone_number = fields.Char(string="手机号", default="13800138000")
    bank_account = fields.Char(string="银行卡号", default="6222020000000000")
    tax_id = fields.Char(string="税号", default="91310000TEST")
    identity_number = fields.Char(string="身份证号", default="310101199001010000")

    configured_secret = fields.Char(
        string="配置敏感值", default="configured-sensitive-value"
    )
    @api.onchange("document_type")
    def _onchange_document_type(self):
        for record in self:
            record.domain_key = record.document_type

    def action_confirm(self):
        self.write({"state": "confirmed"})
        return True

    @api.constrains("amount")
    def _check_amount(self):
        for record in self:
            if record.amount < 0:
                raise ValidationError("金额不能为负数。")

    @api.model
    def cleanup_e2e(self, marker, document_ids=None, session_ids=None):
        if marker != "agui_chat_test":
            raise ValidationError("测试清理标记无效。")
        document_ids = [int(record_id) for record_id in (document_ids or [])]
        session_ids = [int(session_id) for session_id in (session_ids or [])]
        documents = self.sudo().browse(document_ids).exists() | self.sudo().search([
            ("name", "like", "AGUI-E2E-%"),
        ])
        documents = documents.filtered(
            lambda record: (record.name or "").startswith("AGUI-E2E-")
        )
        sessions = self.env["agui.chat.session"].sudo().with_context(
            active_test=False
        ).search([
            ("id", "in", session_ids),
            ("user_id", "=", self.env.user.id),
        ])
        thread_ids = sessions.mapped("thread_id")
        authorizations = self.env["agui.chat.tool.authorization"].sudo().search([
            ("user_id", "=", self.env.user.id),
        ]).filtered(lambda authorization:
            (authorization.tool_call_id or "").startswith(("e2e-", "validate-")) or
            '"model":"agui.chat.test.document"' in (authorization.arguments_json or "") or
            any(thread_id in (authorization.context_json or "") for thread_id in thread_ids)
        )
        executions = self.env["agui.chat.command.execution"].sudo().search([
            ("authorization_id", "in", authorizations.ids),
        ])
        audits = self.env["agui.chat.tool.audit"].sudo().search([
            ("user_id", "=", self.env.user.id),
        ]).filtered(lambda audit:
            audit.authorization_id.id in authorizations.ids or
            (audit.tool_call_id or "").startswith(("e2e-", "validate-")) or
            audit.target_model == "agui.chat.test.document" or
            (audit.thread_id or "") in thread_ids
        )
        attachments = self.env["ir.attachment"].sudo().search([
            ("res_model", "=", "agui.chat.session"),
            ("res_id", "in", sessions.ids),
        ])
        counts = {
            "documents": len(documents),
            "sessions": len(sessions),
            "authorizations": len(authorizations),
            "audits": len(audits),
            "attachments": len(attachments),
        }
        executions.unlink()
        audits.unlink()
        authorizations.unlink()
        attachments.unlink()
        sessions.unlink()
        documents.unlink()
        return counts


class AguiChatTestLine(models.Model):
    _name = "agui.chat.test.line"
    _description = "AG-UI 通用测试单据明细"
    _order = "id"

    document_id = fields.Many2one(
        "agui.chat.test.document",
        string="单据",
        required=True,
        ondelete="cascade",
    )
    name = fields.Char(string="明细名称", required=True)
    quantity = fields.Integer(string="数量", default=1)
    domain_key = fields.Selection(
        DOMAIN_KEYS, string="关系域键", required=True, default="standard"
    )
    candidate_id = fields.Many2one(
        "agui.chat.test.option", string="明细候选", ondelete="restrict"
    )
    tag_ids = fields.Many2many(
        "agui.chat.test.option",
        "agui_chat_test_line_option_rel",
        "line_id", "option_id", string="明细标签",
    )
    secret_token = fields.Char(string="明细敏感令牌")


class AguiChatTestConfig(models.Model):
    _inherit = "agui.chat.config"

    @api.model
    def configure_test_environment(self):
        config = self.sudo().get_active_config()
        config.write({
            "chat_enabled": True,
            "host_tools_enabled": True,
            "write_tools_enabled": True,
            "enabled_commands": ",".join(HOST_COMMAND_NAMES),
            "enabled_business_commands": "odoo.business.test_document.confirm",
            "sensitive_field_names": "secret_token,configured_secret",
        })
        patch_policy = self.env.ref(
            "agui_chat_test.policy_test_patch", raise_if_not_found=False
        )
        if patch_policy:
            patch_policy.sudo().write({
                "sequence": 1,
                "confirmation_mode": "never",
            })
        return True
