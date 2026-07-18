# -*- coding: utf-8 -*-
from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests.common import TransactionCase

from odoo.addons.agui_chat.controllers import main as controller_main
from ..models.agui_chat_workspace import (
    WORKSPACE_SECRET_PARAM,
    decode_workspace_capability,
    issue_workspace_capability,
)


SECRET = "0123456789abcdef0123456789abcdef"


class TestWorkspaceCapability(TransactionCase):

    def setUp(self):
        super(TestWorkspaceCapability, self).setUp()
        self.env["ir.config_parameter"].sudo().set_param(
            WORKSPACE_SECRET_PARAM, SECRET,
        )
        self.config = self.env["agui.chat.config"].sudo().get_active_config()
        self.config.write({"agentos_internal_url": "http://agentos:7777"})
        self.session = self.env["agui.chat.session"].create_session()

    def test_capability_claims_and_tamper_expiry(self):
        token, issued = issue_workspace_capability(
            self.env, self.session, "odoo-session", now=1000,
        )
        claims = decode_workspace_capability(token, SECRET, now=1200)

        self.assertEqual(claims["database"], self.env.cr.dbname)
        self.assertEqual(claims["user"], self.env.user.id)
        self.assertEqual(claims["company"], self.env.user.company_id.id)
        self.assertEqual(claims["thread"], self.session.thread_id)
        self.assertEqual(claims["exp"] - claims["iat"], 600)
        self.assertEqual(issued, claims)
        with self.assertRaisesRegex(ValueError, "capability_invalid"):
            decode_workspace_capability(token[:-1] + "A", SECRET, now=1200)
        with self.assertRaisesRegex(ValueError, "capability_expired"):
            decode_workspace_capability(token, SECRET, now=1600)

    def _request(self):
        return SimpleNamespace(
            env=self.env,
            session=SimpleNamespace(sid="odoo-session"),
        )

    def test_archive_deactivates_session_and_enqueues_cleanup(self):
        controller = controller_main.AguiChatController()
        with patch(
            "odoo.addons.agui_chat.controllers.main.request", new=self._request(),
        ):
            result = controller.session_archive(self.session.id)

        self.assertEqual(result, {"ok": True})
        self.assertFalse(self.session.active)
        task = self.env["agui.chat.sandbox.cleanup"].sudo().search([
            ("thread_id", "=", self.session.thread_id),
        ])
        self.assertTrue(task)

    def test_direct_session_unlink_enqueues_cleanup(self):
        thread_id = self.session.thread_id
        self.session.unlink()

        task = self.env["agui.chat.sandbox.cleanup"].sudo().search([
            ("thread_id", "=", thread_id),
        ])
        self.assertTrue(task)
