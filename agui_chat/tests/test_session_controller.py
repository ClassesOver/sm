# -*- coding: utf-8 -*-
from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests.common import TransactionCase

from odoo.addons.agui_chat.controllers import main as controller_main


class TestAguiChatSessionController(TransactionCase):

    def test_save_returns_structured_result_when_session_was_deleted(self):
        session = self.env["agui.chat.session"]._create_session()
        session_id = session.id
        session.unlink()
        controller = controller_main.AguiChatController()

        with patch(
            "odoo.addons.agui_chat.controllers.main.request",
            new=SimpleNamespace(env=self.env),
        ):
            result = controller.session_save(
                session_id=session_id,
                values={"messages": []},
                expected_session_revision=0,
            )

        self.assertEqual(result, {"ok": False, "error": "session_not_found"})
