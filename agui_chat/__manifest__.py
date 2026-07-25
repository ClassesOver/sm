# -*- coding: utf-8 -*-
{
    "name": "AG-UI 智能助手",
    "version": "12.0.8.8.11",
    "category": "生产力",
    "summary": "HRP智能助手",
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
