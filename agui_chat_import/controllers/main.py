# -*- coding: utf-8 -*-
import base64
import logging

from odoo import http
from odoo.exceptions import AccessError, ValidationError
from odoo.http import content_disposition
from odoo.http import request

from ..models.import_job import X2ManyImportError


_logger = logging.getLogger(__name__)


class AguiChatImportController(http.Controller):

    @http.route("/agui_chat_import/prepare", type="json", auth="user")
    def prepare(self, parent_model, parent_id, field_name, attachment_id,
                schema_hash):
        try:
            return request.env["agui.chat.x2many.import.job"]._prepare_job(
                parent_model, parent_id, field_name, attachment_id, schema_hash
            )
        except (X2ManyImportError, AccessError, ValidationError, ValueError) as error:
            return {
                "ok": False,
                "code": getattr(error, "code", False) or "x2many_import_rejected",
                "error": str(error),
            }
        except Exception:
            _logger.exception("AG-UI One2many import preparation failed")
            return {"ok": False, "code": "x2many_import_failed"}

    @http.route("/agui_chat_import/status", type="json", auth="user")
    def status(self, job_token):
        try:
            return request.env["agui.chat.x2many.import.job"]._job_status(job_token)
        except (X2ManyImportError, AccessError, ValidationError, ValueError) as error:
            return {
                "ok": False,
                "code": getattr(error, "code", False) or "x2many_import_rejected",
                "error": str(error),
            }

    @http.route(
        "/agui_chat_import/error/<string:job_token>",
        type="http", auth="user", methods=["GET"],
    )
    def error_report(self, job_token, **kwargs):
        try:
            job = request.env["agui.chat.x2many.import.job"]._owned_job(job_token)
            attachment = job.error_attachment_id
            if not attachment:
                raise X2ManyImportError("error_report_unavailable")
            return request.make_response(
                base64.b64decode(attachment.datas or b""),
                headers=[
                    ("Content-Type", attachment.mimetype or "application/json"),
                    ("Content-Disposition", content_disposition(
                        attachment.name or "import-errors.json"
                    )),
                    ("X-Content-Type-Options", "nosniff"),
                ],
            )
        except (X2ManyImportError, AccessError, ValidationError, ValueError):
            return request.not_found()
