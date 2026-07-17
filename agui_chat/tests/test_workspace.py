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

    def test_archive_destroys_workspace_before_deactivation(self):
        response = SimpleNamespace(status_code=204)
        controller = controller_main.AguiChatController()
        with patch(
            "odoo.addons.agui_chat.controllers.main.request", new=self._request(),
        ), patch(
            "odoo.addons.agui_chat.controllers.main.requests.delete", return_value=response,
        ) as delete:
            result = controller.session_archive(self.session.id)

        self.assertEqual(result, {"ok": True})
        self.assertFalse(self.session.active)
        self.assertEqual(delete.call_args[0][0], "http://agentos:7777/workspace/sandbox")
        self.assertEqual(
            delete.call_args[1]["json"], {"threadId": self.session.thread_id},
        )

    def test_archive_fails_closed_when_cleanup_fails(self):
        response = SimpleNamespace(status_code=503)
        controller = controller_main.AguiChatController()
        with patch(
            "odoo.addons.agui_chat.controllers.main.request", new=self._request(),
        ), patch(
            "odoo.addons.agui_chat.controllers.main.requests.delete", return_value=response,
        ):
            result = controller.session_archive(self.session.id)

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "workspace_cleanup_failed")
        self.assertTrue(self.session.active)
