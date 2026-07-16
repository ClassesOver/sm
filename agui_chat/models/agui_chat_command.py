# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .agui_chat_config import HOST_COMMAND_NAMES


class AguiChatCommand(models.Model):
    _name = "agui.chat.command"
    _description = "智能助手命令主数据"
    _order = "sequence, code, id"

    name = fields.Char(string="命令名称", required=True)
    code = fields.Char(string="命令编码", required=True, index=True)
    command_type = fields.Selection([
        ("page", "页面命令"),
        ("business", "业务命令"),
    ], string="命令类型", required=True, default="page")
    description = fields.Text(string="说明")
    sequence = fields.Integer(string="顺序", default=10)
    active = fields.Boolean(string="启用", default=True)

    _sql_constraints = [
        ("code_unique", "unique(code)", "命令编码必须唯一。"),
    ]

    @api.constrains("code", "command_type")
    def _check_code(self):
        for record in self:
            code = record.code or ""
            if record.command_type == "page" and code not in HOST_COMMAND_NAMES:
                raise ValidationError("页面命令必须属于系统已注册的页面命令。")
            if record.command_type == "business" and not code.startswith("odoo.business."):
                raise ValidationError("业务命令必须使用 odoo.business.* 前缀。")
