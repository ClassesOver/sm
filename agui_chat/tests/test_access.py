# -*- coding: utf-8 -*-
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from odoo import api, fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase

from odoo.addons.agui_chat.controllers import main as controller_main


class TestServerStateAccess(TransactionCase):

    def setUp(self):
        super(TestServerStateAccess, self).setUp()
        self.user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "服务端状态权限用户",
            "login": "agui-state-access-user",
            "email": "agui-state-access-user@example.com",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            "company_id": self.env.user.company_id.id,
            "company_ids": [(6, 0, [self.env.user.company_id.id])],
        })
        self.user_env = api.Environment(
            self.env.cr, self.user.id, dict(self.env.context),
        )
        expires_at = fields.Datetime.to_string(
            fields.Datetime.from_string(fields.Datetime.now()) + timedelta(minutes=5)
        )
        self.session = self.user_env["agui.chat.session"]._create_session()
        self.authorization = self.env["agui.chat.tool.authorization"].sudo().create({
            "user_id": self.user.id,
            "company_id": self.user.company_id.id,
            "idempotency_key": "access-authorization",
            "payload_hash": "access-payload",
            "tool_call_id": "access-tool-call",
            "tool_name": "odoo.navigate_menu",
            "state": "approved",
            "expires_at": expires_at,
        })
        self.audit = self.env["agui.chat.tool.audit"].sudo().create({
            "user_id": self.user.id,
            "company_id": self.user.company_id.id,
            "tool_name": "odoo.navigate_menu",
            "result": "allowed",
        })
        self.execution = self.env["agui.chat.command.execution"].sudo().create({
            "user_id": self.user.id,
            "company_id": self.user.company_id.id,
            "command_name": "odoo.business.access.test",
            "idempotency_key": "access-execution",
            "payload_hash": "access-payload",
            "authorization_id": self.authorization.id,
        })
        self.mention = self.env["agui.chat.mention.token"].sudo().create({
            "token_kind": "candidate",
            "resource_kind": "menu",
            "resource_key": "access-menu",
            "label": "权限测试菜单",
            "payload_json": "{}",
            "session_key": "access-session",
            "user_id": self.user.id,
            "company_id": self.user.company_id.id,
            "expires_at": expires_at,
        })

    def test_internal_user_cannot_create_or_write_server_state(self):
        records = {
            "agui.chat.session": (self.session.id, {"name": "伪造会话"}),
            "agui.chat.tool.authorization": (
                self.authorization.id, {"state": "consumed"},
            ),
            "agui.chat.tool.audit": (self.audit.id, {"request_id": "forged"}),
            "agui.chat.command.execution": (
                self.execution.id, {"error_code": "forged"},
            ),
            "agui.chat.mention.token": (self.mention.id, {"label": "伪造引用"}),
        }
        for model_name, (record_id, values) in records.items():
            model = self.user_env[model_name]
            self.assertTrue(model.browse(record_id).exists())
            with self.assertRaises(AccessError), self.env.cr.savepoint():
                model.create({})
            with self.assertRaises(AccessError), self.env.cr.savepoint():
                model.browse(record_id).write(values)

    def test_session_controller_uses_controlled_state_writes(self):
        controller = controller_main.AguiChatController()
        with patch(
            "odoo.addons.agui_chat.controllers.main.request",
            new=SimpleNamespace(env=self.user_env),
        ):
            created = controller.session_create(name="受控会话")
            saved = controller.session_save(
                session_id=created["session"]["id"],
                values={"name": "已保存会话", "messages": []},
                expected_session_revision=0,
            )
            archived = controller.session_archive(created["session"]["id"])

        self.assertTrue(created["ok"])
        self.assertTrue(saved["ok"])
        self.assertEqual(archived, {"ok": True})
        session = self.env["agui.chat.session"].sudo().browse(
            created["session"]["id"]
        )
        self.assertEqual(session.user_id, self.user)
        self.assertFalse(session.active)
        self.assertTrue(self.env["agui.chat.sandbox.cleanup"].sudo().search([
            ("thread_id", "=", session.thread_id),
        ]))
