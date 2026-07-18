# -*- coding: utf-8 -*-
from ..models.agui_chat_workspace import WORKSPACE_SECRET_PARAM


TEST_WORKSPACE_SECRET = "0123456789abcdef0123456789abcdef"


def configure_test_runtime(env):
    env["ir.config_parameter"].sudo().set_param(
        WORKSPACE_SECRET_PARAM, TEST_WORKSPACE_SECRET,
    )
    config = env["agui.chat.config"].sudo().get_active_config()
    config.write({
        "runtime_url": "/agent/agui",
        "agentos_internal_url": "http://agentos:7777",
    })
    return config
