# -*- coding: utf-8 -*-
from odoo.addons.agui_chat.models.agui_chat_tool import register_business_command


COMMAND_NAME = "odoo.business.test_document.confirm"
MODEL_NAME = "agui.chat.test.document"


class BusinessCommandError(Exception):
    def __init__(self, code):
        super(BusinessCommandError, self).__init__(code)
        self.code = code


def confirm_test_document(env, payload):
    document = env[MODEL_NAME].browse(payload["document_id"]).exists()
    if not document:
        raise BusinessCommandError("record_unavailable")
    document.check_access_rights("write")
    document.check_access_rule("write")
    if document.state != payload["expected_state"]:
        raise BusinessCommandError("state_conflict")
    document.action_confirm()
    return {
        "document_id": document.id,
        "state": document.state,
        "phone_number": document.phone_number,
        "configured_secret": document.configured_secret,
    }


register_business_command(
    COMMAND_NAME,
    {
        "type": "object",
        "additionalProperties": False,
        "required": ["model", "document_id", "expected_state"],
        "properties": {
            "model": {
                "type": "string",
                "enum": [MODEL_NAME],
            },
            "document_id": {
                "type": "integer",
                "minimum": 1,
            },
            "expected_state": {
                "type": "string",
                "enum": ["draft"],
            },
        },
    },
    confirm_test_document,
    description="确认当前用户可写且仍为草稿的通用测试单据。",
)
