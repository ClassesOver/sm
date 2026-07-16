# -*- coding: utf-8 -*-
{
    "name": "AG-UI 智能助手",
    "version": "12.0.7.0.0",
    "category": "生产力",
    "summary": "面向 Odoo 12 的 React AG-UI 智能助手",
    "depends": ["web"],
    "data": [
        "security/ir.model.access.csv",
        "security/agui_chat_security.xml",
        "data/agui_chat_command.xml",
        "data/agui_chat_tool_policy.xml",
        "data/agui_chat_cron.xml",
        "views/agui_chat_views.xml",
        "views/assets.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
