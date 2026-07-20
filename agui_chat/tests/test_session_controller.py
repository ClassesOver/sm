# -*- coding: utf-8 -*-
import base64
import json
from types import SimpleNamespace
from unittest.mock import patch

from odoo import api
from odoo.tests.common import TransactionCase

from odoo.addons.agui_chat.controllers import main as controller_main


class TestAguiChatSessionController(TransactionCase):

    def test_attachment_routes_use_odoo_csrf_validation(self):
        upload_routing = controller_main.AguiChatController.attachment_upload.routing
        delete_routing = controller_main.AguiChatController.attachment_delete.routing

        self.assertTrue(upload_routing.get("csrf", True))
        self.assertTrue(delete_routing.get("csrf", True))

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

    def test_fork_truncates_history_and_copies_referenced_attachments(self):
        session = self.env["agui.chat.session"]._create_session(
            name="采购讨论", surface="standalone", agent_id="odoo-assistant",
        )
        attachment = self.env["ir.attachment"].sudo().create({
            "name": "数据.csv",
            "datas_fname": "数据.csv",
            "mimetype": "text/csv",
            "datas": base64.b64encode(b"name\nA\n"),
            "res_model": "agui.chat.session",
            "res_id": session.id,
        })
        messages = [
            {
                "id": "user-1", "role": "user", "content": "分析附件",
                "attachments": [{
                    "id": str(attachment.id), "name": "数据.csv",
                    "mimeType": "text/csv", "size": 7, "modality": "document",
                }],
            },
            {
                "id": "answer-1", "role": "assistant", "content": "第一轮回答",
                "extra_data": {"agent_run_id": "run-1"},
            },
            {"id": "user-2", "role": "user", "content": "继续"},
            {
                "id": "answer-2", "role": "assistant", "content": "第二轮回答",
                "extra_data": {"agent_run_id": "run-2"},
            },
        ]
        session._save_from_client({
            "messages": messages,
            "agentState": {"mode": "analysis"},
            "uiPreferences": {"sidebar": False},
        }, 0)
        source_thread = session.thread_id

        result = session._fork_from_client("answer-1", "run-1", 1)

        self.assertTrue(result["ok"])
        branch = self.env["agui.chat.session"].browse(result["session"]["id"])
        self.assertEqual(branch.parent_session_id, session)
        self.assertEqual(branch.name, "采购讨论（分支）")
        self.assertNotEqual(branch.thread_id, source_thread)
        self.assertEqual(branch.surface, "standalone")
        self.assertEqual(branch.agent_id, "odoo-assistant")
        retained = json.loads(branch.messages_json)
        self.assertEqual([message["id"] for message in retained], ["user-1"])
        copied_id = int(retained[0]["attachments"][0]["id"])
        self.assertNotEqual(copied_id, attachment.id)
        copied = self.env["ir.attachment"].sudo().browse(copied_id)
        self.assertEqual((copied.res_model, copied.res_id), ("agui.chat.session", branch.id))
        self.assertEqual(base64.b64decode(copied.datas), b"name\nA\n")
        self.assertEqual(json.loads(session.messages_json), messages)
        self.assertTrue(session.active)

    def test_fork_rejects_revision_conflict_and_non_final_answer(self):
        session = self.env["agui.chat.session"]._create_session()
        session._save_from_client({"messages": [{
            "id": "answer", "role": "assistant", "content": "回答",
            "extra_data": {"agent_run_id": "run"},
            "tool_calls": [{"id": "tool", "status": "pending"}],
        }]}, 0)

        conflict = session._fork_from_client("answer", "run", 0)
        rejected = session._fork_from_client("answer", "run", 1)

        self.assertEqual(conflict["error"], "session_revision_conflict")
        self.assertEqual(rejected["error"], "branch_target_not_final")
        self.assertFalse(self.env["agui.chat.session"].search([
            ("parent_session_id", "=", session.id),
        ]))

    def test_fork_reads_the_locked_database_snapshot_instead_of_cached_messages(self):
        session = self.env["agui.chat.session"]._create_session()
        session._save_from_client({"messages": [{
            "id": "cached", "role": "assistant", "content": "旧回答",
            "extra_data": {"agent_run_id": "old-run"},
        }]}, 0)
        session.messages_json
        latest = [
            {"id": "latest-user", "role": "user", "content": "最新问题"},
            {
                "id": "latest-answer", "role": "assistant", "content": "最新回答",
                "extra_data": {"agent_run_id": "latest-run"},
            },
        ]
        self.env.cr.execute(
            "UPDATE agui_chat_session SET messages_json = %s, session_revision = 2 "
            "WHERE id = %s",
            (json.dumps(latest), session.id),
        )

        result = session._fork_from_client(
            "latest-answer", "latest-run", 2,
        )

        self.assertTrue(result["ok"])
        branch = self.env["agui.chat.session"].browse(result["session"]["id"])
        self.assertEqual(json.loads(branch.messages_json), [latest[0]])

    def test_fork_controller_respects_session_record_rules(self):
        session = self.env["agui.chat.session"]._create_session()
        other = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "分支隔离用户",
            "login": "agui-branch-isolation-user",
            "email": "agui-branch-isolation-user@example.com",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            "company_id": self.env.user.company_id.id,
            "company_ids": [(6, 0, [self.env.user.company_id.id])],
        })
        controller = controller_main.AguiChatController()

        with patch(
            "odoo.addons.agui_chat.controllers.main.request",
            new=SimpleNamespace(env=api.Environment(
                self.env.cr, other.id, dict(self.env.context),
            )),
        ):
            result = controller.session_fork(
                session.id, "answer", "run", 0,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "branch_rejected")

    def test_protocol_upgrade_archives_active_sessions_and_queues_workspaces(self):
        first = self.env["agui.chat.session"]._create_session(name="旧会话一")
        second = self.env["agui.chat.session"]._create_session(name="旧会话二")

        archived_ids = self.env["agui.chat.session"]._archive_for_protocol_upgrade()

        self.assertIn(first.id, archived_ids)
        self.assertIn(second.id, archived_ids)
        self.assertFalse(first.active)
        self.assertFalse(second.active)
        tasks = self.env["agui.chat.sandbox.cleanup"].sudo().search([
            ("thread_id", "in", [first.thread_id, second.thread_id]),
        ])
        self.assertEqual(set(tasks.mapped("thread_id")), {
            first.thread_id, second.thread_id,
        })
