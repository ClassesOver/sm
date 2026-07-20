# -*- coding: utf-8 -*-
{
    "name": "AG-UI One2many 批量导入",
    "version": "12.0.8.7.0",
    "category": "生产力",
    "summary": "受控校验并原子导入 One2many 明细",
    "depends": ["agui_chat", "base_import"],
    "data": [
        "security/agui_chat_import_security.xml",
        "security/ir.model.access.csv",
        "data/agui_chat_import_command.xml",
        "data/agui_chat_import_policy.xml",
        "data/agui_chat_import_cron.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
