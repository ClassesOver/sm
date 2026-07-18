# -*- coding: utf-8 -*-
from datetime import timedelta

import requests
from psycopg2 import IntegrityError

from odoo import api, fields, models

from .agui_chat_workspace import issue_thread_capability


WORKSPACE_CLEANUP_TIMEOUT = 8
MAX_CLEANUP_ERROR_CHARS = 1024
MAX_CLEANUP_BACKOFF_MINUTES = 24 * 60


class AguiChatSandboxCleanup(models.Model):
    _name = "agui.chat.sandbox.cleanup"
    _description = "AG-UI 沙箱清理任务"
    _order = "next_attempt_at, id"

    thread_id = fields.Char(string="线程 ID", required=True, index=True)
    attempt_count = fields.Integer(string="尝试次数", default=0, required=True)
    next_attempt_at = fields.Datetime(
        string="下次执行时间", default=fields.Datetime.now, required=True, index=True,
    )
    last_error = fields.Char(string="最近错误", size=MAX_CLEANUP_ERROR_CHARS)

    _sql_constraints = [
        ("thread_id_unique", "unique(thread_id)", "同一线程只能有一个沙箱清理任务。"),
    ]

    @api.model
    def _enqueue(self, thread_ids):
        threads = sorted({str(value or "").strip() for value in thread_ids if value})
        if not threads:
            return self.browse()
        existing = set(self.sudo().search([
            ("thread_id", "in", threads),
        ]).mapped("thread_id"))
        created = self.browse()
        for thread_id in threads:
            if thread_id not in existing:
                try:
                    with self.env.cr.savepoint():
                        created |= self.sudo().create({"thread_id": thread_id})
                except IntegrityError:
                    created |= self.sudo().search([
                        ("thread_id", "=", thread_id),
                    ], limit=1)
        return created

    @api.model
    def _process_pending(self, limit=50, now=None):
        now_value = fields.Datetime.from_string(now or fields.Datetime.now())
        tasks = self.sudo().search([
            ("next_attempt_at", "<=", fields.Datetime.to_string(now_value)),
        ], order="next_attempt_at, id", limit=min(max(int(limit or 50), 1), 50))
        for task in tasks:
            task._process_one(now_value)
        return True

    def _process_one(self, now_value):
        self.ensure_one()
        try:
            config = self.env["agui.chat.config"].sudo().get_active_config()
            base_url = config.internal_agentos_url()
            if not base_url:
                raise ValueError("AgentOS 内部服务地址未配置。")
            capability, _claims = issue_thread_capability(
                self.env, self.thread_id, "agui-sandbox-cleanup",
            )
            response = requests.delete(
                "%s/workspace/sandbox" % base_url,
                json={"threadId": self.thread_id},
                headers={
                    "X-AGUI-Capability": capability,
                    "X-AGUI-Thread": self.thread_id,
                },
                timeout=WORKSPACE_CLEANUP_TIMEOUT,
            )
            if response.status_code not in (200, 204, 404):
                raise ValueError("AgentOS 工作区清理返回 HTTP %s。" % response.status_code)
        except Exception as error:
            attempts = self.attempt_count + 1
            exponent = min(max(attempts - 1, 0), 9)
            delay = min(5 * (2 ** exponent), MAX_CLEANUP_BACKOFF_MINUTES)
            self.write({
                "attempt_count": attempts,
                "next_attempt_at": fields.Datetime.to_string(
                    now_value + timedelta(minutes=delay)
                ),
                "last_error": str(error)[:MAX_CLEANUP_ERROR_CHARS],
            })
            return False
        self.unlink()
        return True
