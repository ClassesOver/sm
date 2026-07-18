# -*- coding: utf-8 -*-
import base64

from odoo.tests.common import TransactionCase

from odoo.addons.agui_chat_import.models.import_job import COMMAND_NAME


MODEL_NAME = "agui.chat.test.document"


class TestX2ManyImport(TransactionCase):

    def setUp(self):
        super(TestX2ManyImport, self).setUp()
        self.config = self.env["agui.chat.config"].sudo().get_active_config()
        enabled = set(self.config.enabled_business_command_names())
        enabled.add(COMMAND_NAME)
        self.config.write({
            "chat_enabled": True,
            "host_tools_enabled": True,
            "write_tools_enabled": True,
            "enabled_business_commands": ",".join(sorted(enabled)),
        })
        self.document = self.env[MODEL_NAME].create({
            "name": "批量导入测试",
            "required_code": "IMPORT-1",
        })
        self.session = self.env["agui.chat.session"].create({
            "name": "批量导入测试会话",
        })

    def _attachment(self, rows):
        content = "明细名称,数量,关系域键\n%s\n" % "\n".join(rows)
        return self.env["ir.attachment"].sudo().create({
            "name": "lines.csv",
            "datas_fname": "lines.csv",
            "mimetype": "text/csv",
            "datas": base64.b64encode(content.encode("utf-8")),
            "res_model": "agui.chat.session",
            "res_id": self.session.id,
        })

    def _prepare_job(self, rows):
        attachment = self._attachment(rows)
        result = self.env["agui.chat.x2many.import.job"]._prepare_job(
            MODEL_NAME,
            self.document.id,
            "detail_item_ids",
            attachment.id,
            "a" * 64,
        )
        job = self.env["agui.chat.x2many.import.job"].sudo().search([
            ("token", "=", result["jobToken"]),
        ])
        self.assertEqual(job.state, "validating")
        job._validate_job()
        return job

    def _call(self, token, call_id):
        return {
            "id": call_id,
            "tool": COMMAND_NAME,
            "arguments": {"jobToken": token},
            "context": {
                "requestId": "request-%s" % call_id,
                "runId": "run-%s" % call_id,
                "threadId": "thread-%s" % call_id,
            },
        }

    def _authorize_and_queue(self, job, call_id):
        authorizations = self.env["agui.chat.tool.authorization"]
        decision = authorizations._prepare_business_command(
            self._call(job.token, call_id)
        )
        self.assertTrue(decision["needs_confirmation"])
        authorization = authorizations.search([
            ("token", "=", decision["authorization_id"]),
        ])
        authorization._transition(True)
        result = self.env["agui.chat.command.execution"]._execute_named(
            COMMAND_NAME,
            {"jobToken": job.token},
            authorization.token,
            authorization.token,
        )
        self.assertTrue(result["ok"])
        job.invalidate_cache(["state"])
        self.assertEqual(job.state, "queued")
        return decision

    def test_hundreds_of_rows_use_trusted_preview_and_one_atomic_parent_write(self):
        rows = ["明细 %s,%s,standard" % (index, index) for index in range(1, 301)]
        job = self._prepare_job(rows)
        self.assertEqual(job.state, "ready")
        self.assertEqual(job.row_count, 300)

        decision = self._authorize_and_queue(job, "bulk-300")
        preview = decision["preview"]["import"]
        self.assertEqual(preview["fileName"], "lines.csv")
        self.assertEqual(preview["rowCount"], 300)
        self.assertEqual(preview["sha256"], job.file_sha256)
        self.assertEqual(preview["target"]["field"], "detail_item_ids")

        self.assertTrue(job._run_job(), job.result_json)
        job.invalidate_cache(["state"])
        self.document.invalidate_cache(["detail_item_ids"])
        self.assertEqual(job.state, "done")
        self.assertEqual(len(self.document.detail_item_ids), 300)

    def test_execution_error_rolls_back_every_child_row(self):
        job = self._prepare_job(["有效明细,1,standard", "第二明细,2,standard"])
        self.assertEqual(job.state, "ready")
        job.sudo().write({
            "rows_json": '[{"name":"有效明细","domain_key":"standard"},'
                         '{"name":false,"domain_key":"standard"}]',
        })
        self._authorize_and_queue(job, "bulk-rollback")

        self.assertFalse(job._run_job())
        job.invalidate_cache(["state", "result_json"])
        self.document.invalidate_cache(["detail_item_ids"])
        self.assertEqual(job.state, "failed")
        self.assertFalse(self.document.detail_item_ids)

    def test_write_date_conflict_rejects_confirmation_preview(self):
        job = self._prepare_job(["待冲突明细,1,standard"])
        self.document.write({"name": "其他用户已修改"})
        job.sudo().write({"parent_write_date": "2000-01-01 00:00:00"})

        decision = self.env[
            "agui.chat.tool.authorization"
        ]._prepare_business_command(self._call(job.token, "bulk-conflict"))
        self.assertFalse(decision["ok"])
        self.assertEqual(decision["code"], "write_date_conflict")

    def test_validation_errors_never_become_ready(self):
        job = self._prepare_job(["缺少数量,not-an-int,standard"])
        self.assertEqual(job.state, "failed")
        self.assertTrue(job.error_attachment_id)
        self.assertEqual(job.rows_json, "[]")
