# -*- coding: utf-8 -*-
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import requests

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from ..models.agui_chat_sandbox_cleanup import MAX_CLEANUP_ERROR_CHARS
from ..models.agui_chat_workspace import WORKSPACE_SECRET_PARAM


SECRET = "0123456789abcdef0123456789abcdef"


class TestSandboxCleanup(TransactionCase):

    def setUp(self):
        super(TestSandboxCleanup, self).setUp()
        self.env["ir.config_parameter"].sudo().set_param(WORKSPACE_SECRET_PARAM, SECRET)
        self.config = self.env["agui.chat.config"].sudo().get_active_config()
        self.config.write({"agentos_internal_url": "http://agentos:7777"})

    def _task(self, thread_id="cleanup-thread"):
        return self.env["agui.chat.sandbox.cleanup"].sudo().enqueue([thread_id])

    def test_failure_is_retained_with_backoff_then_retried(self):
        task = self._task()
        now = fields.Datetime.from_string("2026-07-18 10:00:00")
        with patch(
            "odoo.addons.agui_chat.models.agui_chat_sandbox_cleanup.requests.delete",
            side_effect=requests.ConnectionError("offline"),
        ):
            task._process_one(now)

        self.assertTrue(task.exists())
        self.assertEqual(task.attempt_count, 1)
        self.assertEqual(
            fields.Datetime.from_string(task.next_attempt_at), now + timedelta(minutes=5),
        )

        with patch(
            "odoo.addons.agui_chat.models.agui_chat_sandbox_cleanup.requests.delete",
            return_value=SimpleNamespace(status_code=204),
        ):
            task._process_one(now + timedelta(minutes=5))
        self.assertFalse(task.exists())

    def test_not_found_is_success_and_errors_are_bounded(self):
        missing = self._task("missing-thread")
        with patch(
            "odoo.addons.agui_chat.models.agui_chat_sandbox_cleanup.requests.delete",
            return_value=SimpleNamespace(status_code=404),
        ):
            missing._process_one(fields.Datetime.from_string("2026-07-18 10:00:00"))
        self.assertFalse(missing.exists())

        failed = self._task("failed-thread")
        with patch(
            "odoo.addons.agui_chat.models.agui_chat_sandbox_cleanup.requests.delete",
            side_effect=requests.ConnectionError("x" * (MAX_CLEANUP_ERROR_CHARS + 500)),
        ):
            failed._process_one(fields.Datetime.from_string("2026-07-18 10:00:00"))
        self.assertLessEqual(len(failed.last_error), MAX_CLEANUP_ERROR_CHARS)

        failed.write({"attempt_count": 20})
        retry_at = fields.Datetime.from_string("2026-07-18 11:00:00")
        with patch(
            "odoo.addons.agui_chat.models.agui_chat_sandbox_cleanup.requests.delete",
            side_effect=requests.ConnectionError("offline"),
        ):
            failed._process_one(retry_at)
        self.assertEqual(
            fields.Datetime.from_string(failed.next_attempt_at),
            retry_at + timedelta(hours=24),
        )

    def test_retention_unlink_enqueues_cleanup(self):
        session = self.env["agui.chat.session"].create_session()
        thread_id = session.thread_id
        self.config.write({"session_retention_days": 1})
        self.env.cr.execute(
            "UPDATE agui_chat_session SET write_date = %s WHERE id = %s",
            ("2000-01-01 00:00:00", session.id),
        )

        self.env["agui.chat.tool.audit"].cleanup_expired()

        self.assertFalse(session.exists())
        self.assertTrue(self.env["agui.chat.sandbox.cleanup"].sudo().search([
            ("thread_id", "=", thread_id),
        ]))


class TestFailClosedConfig(TransactionCase):

    def test_new_config_defaults_and_enable_validation(self):
        config = self.env["agui.chat.config"].sudo().create({
            "name": "失败关闭测试", "active": False,
        })
        self.assertFalse(config.chat_enabled)
        self.assertFalse(config.allow_cross_origin_dev)
        self.assertFalse(config.runtime_url)
        self.assertFalse(config.agentos_internal_url)

        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            config.write({"chat_enabled": True})

        self.env["ir.config_parameter"].sudo().set_param(WORKSPACE_SECRET_PARAM, SECRET)
        config.write({
            "runtime_url": "/agent/agui",
            "agentos_internal_url": "http://agentos:7777",
            "chat_enabled": True,
        })
        self.assertTrue(config.chat_enabled)

        config.write({"chat_enabled": False})
        self.env["ir.config_parameter"].sudo().set_param(WORKSPACE_SECRET_PARAM, "")
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            config.write({"chat_enabled": True})
