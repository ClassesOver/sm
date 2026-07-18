# -*- coding: utf-8 -*-
{
    "name": "AG-UI 通用单据测试",
    "version": "12.0.2.0.0",
    "category": "测试",
    "summary": "仅供 E2E 数据库使用的 AG-UI 通用单据测试模型",
    "depends": ["agui_chat", "agui_chat_import"],
    "data": [
        "security/ir.model.access.csv",
        "data/test_data.xml",
        "views/test_document_views.xml",
        "views/assets.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
    "license": "LGPL-3",
}
